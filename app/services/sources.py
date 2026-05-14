from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlparse

from app.config import ROOT_DIR, Settings
from app.services.db import Database, utc_now


class SourceStore:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.sources_file = settings.data_dir / "sources.json"

    def configured_sources(self) -> list[dict]:
        if not self.sources_file.exists():
            return []
        return json.loads(self.sources_file.read_text(encoding="utf-8"))

    def save_configured_sources(self, sources: list[dict]) -> None:
        self.sources_file.write_text(
            json.dumps(sources, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def make_source_id(self, title: str, url: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", f"{title}-{urlparse(url).netloc}".lower()).strip("-")
        return base[:72] or "custom-source"

    def add_web_source(self, title: str, url: str, source_type: str = "web") -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Нужна корректная ссылка http или https.")
        sources = self.configured_sources()
        if any(item["url"] == url for item in sources):
            raise ValueError("Источник с такой ссылкой уже есть.")
        source_id = self.make_source_id(title, url)
        existing_ids = {item["id"] for item in sources}
        if source_id in existing_ids:
            suffix = 2
            while f"{source_id}-{suffix}" in existing_ids:
                suffix += 1
            source_id = f"{source_id}-{suffix}"
        item = {
            "id": source_id,
            "title": title.strip(),
            "url": url.strip(),
            "type": source_type.strip() or "web",
            "priority": "custom",
        }
        sources.append(item)
        self.save_configured_sources(sources)
        self.sync_metadata()
        return item

    def manual_sources(self) -> list[dict]:
        items = []
        for path in sorted(self.settings.manual_dir.glob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf"}:
                items.append(
                    {
                        "id": f"manual-{path.stem.lower().replace(' ', '-')}",
                        "title": path.stem,
                        "url": str(path.relative_to(ROOT_DIR)),
                        "type": f"manual{path.suffix.lower()}",
                        "path": str(path),
                        "origin": "manual",
                    }
                )
        return items

    def sync_metadata(self) -> None:
        now = utc_now()
        manual_items = self.manual_sources()
        manual_ids = [item["id"] for item in manual_items]
        with self.db.connect() as conn:
            if manual_ids:
                placeholders = ",".join("?" for _ in manual_ids)
                conn.execute(
                    f"DELETE FROM sources WHERE origin = 'manual' AND id NOT IN ({placeholders})",
                    manual_ids,
                )
            else:
                conn.execute("DELETE FROM sources WHERE origin = 'manual'")
            for item in self.configured_sources():
                conn.execute(
                    """
                    INSERT INTO sources (id, title, url, type, status, origin, path, chunks_count, note, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        url = excluded.url,
                        type = excluded.type,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item["id"],
                        item["title"],
                        item["url"],
                        item["type"],
                        "pending",
                        "web",
                        None,
                        0,
                        "Ожидает индексации.",
                        now,
                    ),
                )
            for item in manual_items:
                conn.execute(
                    """
                    INSERT INTO sources (id, title, url, type, status, origin, path, chunks_count, note, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        url = excluded.url,
                        type = excluded.type,
                        origin = excluded.origin,
                        path = excluded.path,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item["id"],
                        item["title"],
                        item["url"],
                        item["type"],
                        "pending",
                        "manual",
                        item["path"],
                        0,
                        "Локальный материал ожидает индексации.",
                        now,
                    ),
                )

    def list_sources(self) -> list[dict]:
        self.sync_metadata()
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, url, type, status, origin, chunks_count, note, updated_at
                FROM sources
                ORDER BY origin ASC, title ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_source(self, source_id: str) -> bool:
        self.sync_metadata()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, origin, path FROM sources WHERE id = ?",
                (source_id,),
            ).fetchone()
            if not row:
                return False

        if row["origin"] == "manual" and row["path"]:
            manual_path = Path(row["path"])
            try:
                if manual_path.exists() and manual_path.is_file():
                    manual_path.unlink()
            except OSError:
                pass
        else:
            sources = [item for item in self.configured_sources() if item["id"] != source_id]
            self.save_configured_sources(sources)

        raw_path = self.settings.raw_dir / f"{source_id}.txt"
        raw_path.unlink(missing_ok=True)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return True

    def update_status(
        self,
        source_id: str,
        status: str,
        chunks_count: int = 0,
        note: str = "",
        path: str | None = None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET status = ?, chunks_count = ?, note = ?, path = COALESCE(?, path), updated_at = ?
                WHERE id = ?
                """,
                (status, chunks_count, note, path, utc_now(), source_id),
            )
