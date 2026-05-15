from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LEN = 6
_BCRYPT_MAX_BYTES = 72


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def _prepare_password(password: str) -> bytes:
    # bcrypt operates on bytes and silently uses only the first 72 bytes.
    # We truncate explicitly to avoid surprises and stay deterministic.
    raw = (password or "").encode("utf-8")
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_prepare_password(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_invite_code() -> str:
    return secrets.token_urlsafe(9).replace("_", "").replace("-", "")[:12].upper()


def create_access_token(
    user_id: str,
    role: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    expires_hours: int = 168,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError:
        return None
