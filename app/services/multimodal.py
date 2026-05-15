from __future__ import annotations

import base64
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import ROOT_DIR, Settings


ATTACHMENT_NOTE_RE = re.compile(r"\n\n\[Прикрепленные изображения: (?P<paths>.*?)\]\s*$", re.DOTALL)
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_INLINE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 4


def append_image_note(message: str, image_paths: list[str]) -> str:
    paths = [path.strip() for path in image_paths if path.strip()]
    if not paths:
        return message
    return message + "\n\n[Прикрепленные изображения: " + ", ".join(paths) + "]"


def strip_image_note(content: str) -> str:
    return ATTACHMENT_NOTE_RE.sub("", content).strip()


def extract_image_paths(content: str) -> list[str]:
    match = ATTACHMENT_NOTE_RE.search(content)
    if not match:
        return []
    return [path.strip() for path in match.group("paths").split(",") if path.strip()]


def build_message_content(
    text: str,
    image_paths: list[str],
    settings: Settings,
) -> str | list[dict[str, Any]]:
    clean_text = strip_image_note(text)
    images = image_content_parts(image_paths, settings)
    if not images:
        return clean_text
    return [{"type": "text", "text": clean_text}, *images]


def image_content_parts(image_paths: list[str], settings: Settings) -> list[dict[str, Any]]:
    parts = []
    for image_path in image_paths[:MAX_IMAGES_PER_MESSAGE]:
        # Public Blob URLs can be passed straight to the LLM.
        if image_path.startswith("http://") or image_path.startswith("https://"):
            parts.append({"type": "image_url", "image_url": {"url": image_path}})
            continue
        encoded = image_data_url(image_path, settings)
        if encoded:
            parts.append({"type": "image_url", "image_url": {"url": encoded}})
    return parts


def image_data_url(image_path: str, settings: Settings) -> str | None:
    path = resolve_uploaded_image(image_path, settings)
    if path is None or not path.exists() or not path.is_file():
        return None
    if path.stat().st_size > MAX_INLINE_IMAGE_BYTES:
        return None

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        return None

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def resolve_uploaded_image(image_path: str, settings: Settings) -> Path | None:
    raw = image_path.strip().strip('"').strip("'")
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    requested = Path(normalized)
    upload_roots = [
        (settings.data_dir / "uploads" / "images").resolve(),
        (ROOT_DIR / "data" / "uploads" / "images").resolve(),
    ]
    candidates = []
    if requested.is_absolute():
        candidates.append(requested)
    candidates.extend(
        [
            ROOT_DIR / requested,
            settings.data_dir / requested,
            settings.data_dir / "uploads" / "images" / requested.name,
        ]
    )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if any(_is_relative_to(resolved, root) for root in upload_roots):
            return resolved
    return None


def uploaded_image_reference(path: Path, settings: Settings) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path.relative_to(settings.data_dir))


def delete_uploaded_image(image_path: str, settings: Settings) -> bool:
    # Blob URL: best-effort delete via Vercel Blob API.
    if image_path.startswith("http://") or image_path.startswith("https://"):
        if settings.blob_read_write_token:
            return _vercel_blob_delete(image_path, settings.blob_read_write_token)
        return False
    resolved = resolve_uploaded_image(image_path, settings)
    if resolved is None or not resolved.exists():
        return False
    try:
        resolved.unlink()
        return True
    except OSError:
        return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------- Vercel Blob HTTP API ----------

def vercel_blob_upload(filename: str, body: bytes, content_type: str, token: str) -> dict:
    """Upload bytes to Vercel Blob storage. Returns dict with at least 'url'."""
    # Unique-ify the pathname so different uploads don't collide.
    safe_name = Path(filename or "image").name
    pathname = f"uploads/{uuid.uuid4().hex}-{safe_name}"
    url = f"https://blob.vercel-storage.com/{pathname}"
    response = httpx.put(
        url,
        content=body,
        headers={
            "authorization": f"Bearer {token}",
            "x-content-type": content_type or "application/octet-stream",
            "x-api-version": "7",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _vercel_blob_delete(blob_url: str, token: str) -> bool:
    try:
        response = httpx.post(
            "https://blob.vercel-storage.com/delete",
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "x-api-version": "7",
            },
            json={"urls": [blob_url]},
            timeout=30,
        )
        return response.status_code < 400
    except Exception:
        return False
