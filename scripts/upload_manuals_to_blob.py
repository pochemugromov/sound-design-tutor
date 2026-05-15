"""One-off migration: upload local manual PDFs to Vercel Blob and store URLs in Neon.

Run locally (where you have both data/manual/*.pdf and access to Neon):
    python scripts/upload_manuals_to_blob.py

Requirements:
- BLOB_READ_WRITE_TOKEN must be set in .env (or environment)
- DATABASE_URL must point to the same Neon DB that Vercel uses
- Manual PDFs must exist in data/manual/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env manually so this works whether or not python-dotenv has been set up.
ROOT = Path(__file__).resolve().parent.parent
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip('"'))

sys.path.insert(0, str(ROOT))

import httpx
import psycopg
from app.config import get_settings


def upload_pdf_to_blob(filename: str, body: bytes, token: str) -> str:
    """Upload PDF bytes to Vercel Blob and return the public URL."""
    pathname = f"manuals/{filename}"
    url = f"https://blob.vercel-storage.com/{pathname}"
    response = httpx.put(
        url,
        content=body,
        headers={
            "authorization": f"Bearer {token}",
            "access": "public",
            "x-content-type": "application/pdf",
            "x-api-version": "7",
            "x-add-random-suffix": "0",
        },
        timeout=300,  # 5 minutes for big files
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Vercel Blob API {response.status_code}: {response.text[:300]}")
    return response.json()["url"]


def main() -> None:
    settings = get_settings()

    if not settings.blob_read_write_token:
        print("ERROR: BLOB_READ_WRITE_TOKEN is not set in .env")
        sys.exit(1)
    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env")
        sys.exit(1)

    manual_dir = settings.manual_dir
    pdfs = sorted(manual_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {manual_dir}")
        sys.exit(0)

    print(f"Found {len(pdfs)} PDF(s) in {manual_dir}\n")

    with psycopg.connect(settings.database_url) as conn:
        for pdf_path in pdfs:
            source_id = f"manual-{pdf_path.stem.lower().replace(' ', '-')}"
            size_mb = pdf_path.stat().st_size / 1024 / 1024
            print(f"[{source_id}] {pdf_path.name} ({size_mb:.1f} MB)")

            # Check if already uploaded
            with conn.cursor() as cur:
                cur.execute("SELECT blob_url FROM sources WHERE id = %s", (source_id,))
                row = cur.fetchone()
            if row and row[0]:
                print(f"  already uploaded → {row[0]}")
                continue

            print(f"  uploading to Vercel Blob...")
            body = pdf_path.read_bytes()
            try:
                blob_url = upload_pdf_to_blob(pdf_path.name, body, settings.blob_read_write_token)
            except Exception as exc:
                print(f"  FAILED: {exc}")
                continue
            print(f"  → {blob_url}")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sources SET blob_url = %s WHERE id = %s",
                    (blob_url, source_id),
                )
                if cur.rowcount == 0:
                    print(f"  WARNING: no sources row for {source_id} — run reindex first.")
                else:
                    print(f"  updated DB row")
            conn.commit()
            print()

    print("Done.")


if __name__ == "__main__":
    main()
