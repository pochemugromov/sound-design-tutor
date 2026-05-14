from __future__ import annotations

import json
from uuid import uuid4

from app.services.db import Database, utc_now


class ChatStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_sessions(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) AS messages_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_session(self, title: str = "Новый диалог") -> dict:
        session_id = str(uuid4())
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return {"id": session_id, "title": title, "created_at": now, "updated_at": now}

    def ensure_session(self, session_id: str | None) -> str:
        if session_id:
            with self.db.connect() as conn:
                row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return session_id
        return self.create_session()["id"]

    def get_messages(self, session_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, citations_json, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item["citations"] = json.loads(item.pop("citations_json") or "[]")
            messages.append(item)
        return messages

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict] | None = None,
    ) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(citations or [], ensure_ascii=False), now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ?, title = COALESCE(NULLIF(title, 'Новый диалог'), ?) WHERE id = ?",
                (now, content[:80], session_id),
            )

    def delete_session(self, session_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0
