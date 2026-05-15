from __future__ import annotations

import json
from uuid import uuid4

from app.services.db import Database, utc_now


class ChatStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_sessions(self, user_id: str | None = None) -> list[dict]:
        with self.db.connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    """
                    SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) AS messages_count
                    FROM sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) AS messages_count
                    FROM sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    WHERE s.user_id = ?
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                    """,
                    (user_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def create_session(self, title: str = "Новый диалог", user_id: str | None = None) -> dict:
        session_id = str(uuid4())
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, user_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, user_id, now, now),
            )
        return {"id": session_id, "title": title, "user_id": user_id, "created_at": now, "updated_at": now}

    def ensure_session(self, session_id: str | None, user_id: str | None = None) -> str:
        if session_id:
            with self.db.connect() as conn:
                row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return session_id
        return self.create_session(user_id=user_id)["id"]

    def collect_image_paths(self, session_id: str) -> list[str]:
        from app.services.multimodal import extract_image_paths

        paths: list[str] = []
        for msg in self.get_messages(session_id):
            if msg.get("role") != "user":
                continue
            paths.extend(extract_image_paths(msg.get("content") or ""))
        seen: set[str] = set()
        ordered: list[str] = []
        for p in paths:
            key = p.strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

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
        from app.services.multimodal import strip_image_note

        now = utc_now()
        title_source = strip_image_note(content) if role == "user" else content
        title_candidate = title_source.strip()[:80] or "Прикрепленные файлы"
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
                (now, title_candidate, session_id),
            )

    def update_session_title(self, session_id: str, title: str) -> None:
        clean = (title or "").strip()[:80]
        if not clean:
            return
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (clean, now, session_id),
            )

    def delete_session(self, session_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0
