"""Dual-mode database layer.

Uses Postgres (via psycopg3) when DATABASE_URL is set, otherwise falls back to
local SQLite. All store code keeps using `?` placeholders — the Postgres adapter
translates them to `%s` at execution time.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Postgres adapter (mimics sqlite3 API surface used by stores) ----------


class _RowProxy:
    """Behaves like sqlite3.Row: supports item access by both string and int."""

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def __contains__(self, key) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data.values())

    def keys(self):
        return self._data.keys()

    def get(self, key, default=None):
        return self._data.get(key, default)


def _translate_placeholders(sql: str) -> str:
    """Replace ? with %s. Stores must not put ? inside string literals."""
    return sql.replace("?", "%s")


def _sanitize_param(value):
    """Strip NUL bytes from strings — Postgres TEXT does not allow them."""
    if isinstance(value, str) and "\x00" in value:
        return value.replace("\x00", "")
    return value


def _sanitize_params(params):
    if not params:
        return params
    if isinstance(params, (list, tuple)):
        return type(params)(_sanitize_param(p) for p in params)
    return params


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql: str, params: tuple | list | None = None):
        self._cur.execute(_translate_placeholders(sql), _sanitize_params(params) or ())
        return self

    def executemany(self, sql: str, seq):
        self._cur.executemany(_translate_placeholders(sql), [_sanitize_params(row) for row in seq])
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return _RowProxy(row) if row else None

    def fetchall(self):
        return [_RowProxy(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def close(self) -> None:
        self._cur.close()


class _PgConnection:
    """Adapter giving psycopg connection a sqlite3-Connection-compatible surface."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: tuple | list | None = None):
        cur = self._conn.cursor(row_factory=dict_row)
        wrapper = _PgCursor(cur)
        wrapper.execute(sql, params)
        return wrapper

    def executescript(self, script: str) -> None:
        # psycopg can handle multi-statement scripts; execute as-is (no ? translation here).
        cur = self._conn.cursor()
        cur.execute(script)
        cur.close()

    def cursor(self):
        return _PgCursor(self._conn.cursor(row_factory=dict_row))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


# ---------- Database facade ----------


class Database:
    def __init__(self, path: Path, postgres_url: str | None = None) -> None:
        self.url = (postgres_url or "").strip() or None
        self.mode = "postgres" if self.url else "sqlite"
        self.path = path
        if self.mode == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.mode == "postgres":
            with psycopg.connect(self.url) as conn:
                adapter = _PgConnection(conn)
                try:
                    yield adapter
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        else:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def init(self) -> None:
        if self.mode == "postgres":
            self._init_postgres()
        else:
            self._init_sqlite()

    # ---------- SQLite schema (kept identical to existing setup) ----------

    def _init_sqlite(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    path TEXT,
                    chunks_count INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    page_number INTEGER,
                    text TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id
                    ON source_chunks(source_id);

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    display_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

                CREATE TABLE IF NOT EXISTS invite_codes (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'user',
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    note TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_chunks)").fetchall()}
            if "page_number" not in columns:
                conn.execute("ALTER TABLE source_chunks ADD COLUMN page_number INTEGER")
            session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "user_id" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")

    # ---------- Postgres schema ----------

    def _init_postgres(self) -> None:
        with self.connect() as conn:
            # Ensure pgvector extension (idempotent)
            conn.executescript("CREATE EXTENSION IF NOT EXISTS vector;")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    user_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    path TEXT,
                    chunks_count INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    page_number INTEGER,
                    text TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    embedding vector,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id
                    ON source_chunks(source_id);

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    display_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

                CREATE TABLE IF NOT EXISTS invite_codes (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'user',
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    note TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
                """
            )
            # Defensive column adds for environments where tables already existed.
            for sql in (
                "ALTER TABLE source_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER",
                "ALTER TABLE source_chunks ADD COLUMN IF NOT EXISTS embedding vector",
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT",
            ):
                conn.executescript(sql + ";")
