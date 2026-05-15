from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_dev_jwt_secret() -> str:
    secret_file = ROOT_DIR / "data" / ".jwt-secret"
    if secret_file.exists():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    import secrets
    new_secret = secrets.token_urlsafe(48)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(new_secret, encoding="utf-8")
    return new_secret


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    api_key_env_name: str
    openai_base_url: str
    chat_model: str
    embedding_model: str
    app_host: str
    app_port: int
    rag_top_k: int
    rag_score_threshold: float
    rag_max_chunks_per_source: int
    rag_max_keyword_chunks_per_source: int
    chat_history_window: int
    title_generation_max_tokens: int
    jwt_secret: str
    jwt_algorithm: str
    auth_cookie_name: str
    auth_session_hours: int
    bootstrap_admin_email: str
    database_url: str
    blob_read_write_token: str
    langfuse_secret_key: str
    langfuse_public_key: str
    langfuse_base_url: str
    langfuse_tracing_enabled: bool
    langfuse_capture_io: bool
    langfuse_flush_on_request_end: bool
    langfuse_environment: str
    langfuse_max_field_chars: int
    database_path: Path
    chroma_path: Path
    data_dir: Path
    manual_dir: Path
    raw_dir: Path
    docs_dir: Path

    @property
    def has_api_key(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def langfuse_configured(self) -> bool:
        return bool(
            self.langfuse_secret_key.strip()
            and self.langfuse_public_key.strip()
            and self.langfuse_base_url.strip()
        )

    @property
    def langfuse_enabled(self) -> bool:
        return self.langfuse_tracing_enabled and self.langfuse_configured


def get_settings() -> Settings:
    is_vercel = os.getenv("VERCEL") == "1"
    vercel_env = os.getenv("VERCEL_ENV", "")
    default_langfuse_environment = "production" if vercel_env == "production" else "development"
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", default_langfuse_environment)

    data_dir = Path("/tmp/sound-design-tutor") if is_vercel else ROOT_DIR / "data"
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    legacy_openai_api_key = os.getenv("OPENAI_API_KEY", "")
    selected_api_key = gemini_api_key or legacy_openai_api_key
    api_key_env_name = "GEMINI_API_KEY" if gemini_api_key or not legacy_openai_api_key else "OPENAI_API_KEY"
    use_gemini_defaults = api_key_env_name == "GEMINI_API_KEY"

    default_base_url = (
        "https://generativelanguage.googleapis.com/v1beta/openai"
        if use_gemini_defaults
        else "https://api.openai.com/v1"
    )
    default_chat_model = "gemini-3-flash-preview" if use_gemini_defaults else "gpt-4.1-mini"
    default_embedding_model = "gemini-embedding-001" if use_gemini_defaults else "text-embedding-3-small"

    return Settings(
        openai_api_key=selected_api_key,
        api_key_env_name=api_key_env_name,
        openai_base_url=os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", default_base_url)).rstrip("/"),
        chat_model=os.getenv("CHAT_MODEL", default_chat_model),
        embedding_model=os.getenv("EMBEDDING_MODEL", default_embedding_model),
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        rag_top_k=int(os.getenv("RAG_TOP_K", "6")),
        rag_score_threshold=float(os.getenv("RAG_SCORE_THRESHOLD", "0.35")),
        rag_max_chunks_per_source=int(os.getenv("RAG_MAX_CHUNKS_PER_SOURCE", "24")),
        rag_max_keyword_chunks_per_source=int(os.getenv("RAG_MAX_KEYWORD_CHUNKS_PER_SOURCE", "0")),
        chat_history_window=int(os.getenv("CHAT_HISTORY_WINDOW", "10")),
        title_generation_max_tokens=int(os.getenv("TITLE_GENERATION_MAX_TOKENS", "500")),
        jwt_secret=os.getenv("JWT_SECRET", "").strip() or _ensure_dev_jwt_secret(),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        auth_cookie_name=os.getenv("AUTH_COOKIE_NAME", "sdt_auth"),
        auth_session_hours=int(os.getenv("AUTH_SESSION_HOURS", "168")),
        bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        blob_read_write_token=os.getenv("BLOB_READ_WRITE_TOKEN", "").strip(),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/"),
        langfuse_tracing_enabled=_env_bool("LANGFUSE_TRACING_ENABLED", True),
        langfuse_capture_io=_env_bool("LANGFUSE_CAPTURE_IO", True),
        langfuse_flush_on_request_end=_env_bool("LANGFUSE_FLUSH_ON_REQUEST_END", is_vercel),
        langfuse_environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", default_langfuse_environment),
        langfuse_max_field_chars=int(os.getenv("LANGFUSE_MAX_FIELD_CHARS", "12000")),
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
