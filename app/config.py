from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    chat_model: str
    embedding_model: str
    app_host: str
    app_port: int
    rag_top_k: int
    rag_score_threshold: float
    rag_max_chunks_per_source: int
    database_path: Path
    chroma_path: Path
    data_dir: Path
    manual_dir: Path
    raw_dir: Path
    docs_dir: Path

    @property
    def has_api_key(self) -> bool:
        return bool(self.openai_api_key.strip())


def get_settings() -> Settings:
    is_vercel = os.getenv("VERCEL") == "1"
    data_dir = Path("/tmp/sound-design-tutor") if is_vercel else ROOT_DIR / "data"
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        chat_model=os.getenv("CHAT_MODEL", "gpt-4.1-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        rag_top_k=int(os.getenv("RAG_TOP_K", "6")),
        rag_score_threshold=float(os.getenv("RAG_SCORE_THRESHOLD", "0.35")),
        rag_max_chunks_per_source=int(os.getenv("RAG_MAX_CHUNKS_PER_SOURCE", "24")),
        database_path=Path(os.getenv("DATABASE_PATH", data_dir / "app.db")),
        chroma_path=Path(os.getenv("CHROMA_PATH", data_dir / "chroma")),
        data_dir=data_dir,
        manual_dir=data_dir / "manual",
        raw_dir=data_dir / "raw",
        docs_dir=ROOT_DIR / "docs_md",
    )


def ensure_directories(settings: Settings) -> None:
    for path in (
        settings.data_dir,
        settings.manual_dir,
        settings.raw_dir,
        settings.chroma_path,
        settings.docs_dir,
        settings.database_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)
