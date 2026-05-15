from __future__ import annotations

from uuid import uuid4

from app.services.db import Database, utc_now


VALID_ROLES = {"user", "admin"}


class UserStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- users ---

    def count_users(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def count_admins(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'").fetchone()["n"]

    def create_user(
        self,
        email: str,
        password_hash: str,
        role: str = "user",
        display_name: str | None = None,
    ) -> dict:
        if role not in VALID_ROLES:
            role = "user"
        user_id = str(uuid4())
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, role, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, email, password_hash, role, display_name, now, now),
            )
        return {
            "id": user_id,
            "email": email,
            "role": role,
            "display_name": display_name,
            "created_at": now,
        }

    def get_by_email(self, email: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def get_by_id(self, user_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, email, role, display_name, created_at, updated_at "
                "FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_role(self, user_id: str, role: str) -> bool:
        if role not in VALID_ROLES:
            return False
        with self.db.connect() as conn:
            cursor = conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, utc_now(), user_id),
            )
            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return cursor.rowcount > 0

    # --- invite codes ---

    def create_invite(
        self,
        code: str,
        role: str = "user",
        max_uses: int = 1,
        expires_at: str | None = None,
        note: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        if role not in VALID_ROLES:
            role = "user"
        invite_id = str(uuid4())
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO invite_codes
                    (id, code, role, max_uses, used_count, expires_at, note, created_by, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (invite_id, code, role, max_uses, expires_at, note, created_by, now),
            )
        return {
            "id": invite_id,
            "code": code,
            "role": role,
            "max_uses": max_uses,
            "used_count": 0,
            "expires_at": expires_at,
            "note": note,
            "created_by": created_by,
            "created_at": now,
        }

    def find_valid_invite(self, code: str) -> dict | None:
        code = (code or "").strip()
        if not code:
            return None
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        invite = dict(row)
        if invite["max_uses"] > 0 and invite["used_count"] >= invite["max_uses"]:
            return None
        if invite["expires_at"] and invite["expires_at"] < utc_now():
            return None
        return invite

    def consume_invite(self, invite_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE invite_codes SET used_count = used_count + 1 WHERE id = ?",
                (invite_id,),
            )

    def list_invites(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM invite_codes ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_invite(self, invite_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM invite_codes WHERE id = ?", (invite_id,))
            return cursor.rowcount > 0
