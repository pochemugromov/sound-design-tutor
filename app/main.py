from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT_DIR, ensure_directories, get_settings
from app.services.auth import (
    MIN_PASSWORD_LEN,
    create_access_token,
    decode_access_token,
    generate_invite_code,
    hash_password,
    is_valid_email,
    normalize_email,
    verify_password,
)
from app.services.chat_store import ChatStore
from app.services.db import Database
from app.services.llm import LLMNotConfigured, OpenAICompatibleClient
from app.services.multimodal import (
    append_image_note,
    build_message_content,
    delete_uploaded_image,
    extract_image_paths,
    strip_image_note,
    uploaded_image_reference,
    vercel_blob_upload,
)
from app.services.prompts import SYSTEM_PROMPT, TITLE_SYSTEM_PROMPT, build_title_prompt, build_user_prompt
from app.services.rag import RagService
from app.services.sources import SourceStore
from app.services.telemetry import Telemetry
from app.services.tools import list_tools, run_mock_tool
from app.services.user_store import UserStore

logger = logging.getLogger(__name__)


settings = get_settings()
ensure_directories(settings)
db = Database(settings.database_path, postgres_url=settings.database_url or None)
db.init()
chat_store = ChatStore(db)
user_store = UserStore(db)
telemetry = Telemetry(settings)
llm = OpenAICompatibleClient(settings, telemetry)
source_store = SourceStore(db, settings)
rag = RagService(settings, llm, source_store)
try:
    rag.restore_keyword_index_from_raw()
except Exception as exc:
    logger.warning("restore_keyword_index_from_raw failed at startup: %s", exc)

EMPTY_RAG_WARNING = (
    "Пока не нашел достаточно релевантных материалов в базе знаний, чтобы ответить с опорой на источники.\n\n"
    "Что сделать:\n"
    "1. Откройте вкладку «База знаний».\n"
    "2. Нажмите «Переиндексировать».\n"
    "3. Выберите режим «Переиндексировать все» и дождитесь завершения.\n\n"
    "После этого повторите вопрос. Если нужный материал еще не добавлен, добавьте его как источник."
)

app = FastAPI(title="AI Sound Design Assistant")
app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")

_UPLOADS_DIR = settings.data_dir / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOADS_DIR), name="uploads")


# ---------- Auth helpers ----------

def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # set True behind HTTPS in production
        max_age=settings.auth_session_hours * 3600,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


def _decode_cookie(token: str | None) -> dict | None:
    if not token:
        return None
    return decode_access_token(token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_optional_user(request: Request) -> dict | None:
    token = request.cookies.get(settings.auth_cookie_name)
    payload = _decode_cookie(token)
    if not payload:
        return None
    user = user_store.get_by_id(payload.get("sub", ""))
    return user


def get_current_user(request: Request) -> dict:
    user = get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Требуется вход в систему.")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Недостаточно прав.")
    return user


def _user_public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "display_name": user.get("display_name"),
        "created_at": user.get("created_at"),
    }


# ---------- Bootstrap initial admin invite ----------

def _bootstrap_initial_invite() -> None:
    """Create a one-time admin invite on first startup so there's a way to register the first admin."""
    if user_store.count_admins() > 0:
        return
    existing = user_store.list_invites()
    if any(inv.get("role") == "admin" and inv.get("used_count", 0) < (inv.get("max_uses") or 1) for inv in existing):
        return
    code = generate_invite_code()
    user_store.create_invite(
        code=code,
        role="admin",
        max_uses=1,
        note="Bootstrap admin invite (first start, single-use)",
    )
    logger.warning("=" * 60)
    logger.warning("BOOTSTRAP ADMIN INVITE CODE: %s", code)
    logger.warning("Use this code at /register to create the first admin account.")
    logger.warning("=" * 60)


_bootstrap_initial_invite()


# ---------- Auth request/response models ----------

class RegisterRequest(BaseModel):
    email: str
    password: str
    invite_code: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class InviteCreateRequest(BaseModel):
    role: str = Field(default="user")
    max_uses: int = Field(default=1, ge=0, le=1000)
    expires_at: str | None = None
    note: str | None = None


class RoleUpdateRequest(BaseModel):
    role: str


async def generate_session_title(message: str, has_images: bool) -> str | None:
    if not settings.has_api_key:
        return None
    try:
        messages = [
            {"role": "system", "content": TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": build_title_prompt(message, has_images)},
        ]
        raw = await llm.chat(
            messages,
            max_tokens=settings.title_generation_max_tokens,
            continue_on_length=False,
        )
    except Exception as exc:
        logger.warning("Session title generation failed: %s: %s", type(exc).__name__, exc)
        return None
    title = (raw or "").strip()
    for ch in ('"', "'", "«", "»", "“", "”", "`"):
        title = title.strip(ch)
    title = title.strip().rstrip(".").strip()
    if not title:
        return None
    return title[:80]


def uploaded_image_url(path: str) -> str | None:
    if not path:
        return None
    normalized = path.strip().replace("\\", "/")
    # Already a fully-qualified Blob (or any HTTP) URL — return as-is.
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    for prefix in ("data/uploads/", "uploads/"):
        if normalized.startswith(prefix):
            return "/" + normalized[normalized.index("uploads/") :]
    name = normalized.rsplit("/", 1)[-1]
    return f"/uploads/images/{name}" if name else None


@app.on_event("shutdown")
async def flush_langfuse_events():
    telemetry.flush()


@app.middleware("http")
async def langfuse_request_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    started_at = perf_counter()
    trace_name = f"{request.method} {request.url.path}"
    metadata = {
        "method": request.method,
        "path": request.url.path,
        "environment": settings.langfuse_environment,
    }
    with telemetry.observation(
        trace_name,
        input={"method": request.method, "path": request.url.path},
        metadata=metadata,
        tags=["api-request"],
        trace_name=trace_name,
    ) as request_span:
        try:
            response = await call_next(request)
        except Exception as exc:
            telemetry.update(
                request_span,
                level="ERROR",
                status_message=str(exc)[:500],
                metadata={**metadata, "duration_ms": round((perf_counter() - started_at) * 1000, 2)},
            )
            if settings.langfuse_flush_on_request_end:
                telemetry.flush()
            raise

        telemetry.update(
            request_span,
            output={"status_code": response.status_code},
            metadata={
                **metadata,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        if settings.langfuse_flush_on_request_end:
            telemetry.flush()
        return response


def deduplicate_contexts(contexts: list[dict]) -> list[dict]:
    seen: set = set()
    result = []
    for item in contexts:
        source_id = item["source_id"]
        page_number = item.get("page_number")
        seen_key = (source_id, page_number or citation_url(item))
        if seen_key in seen:
            continue
        seen.add(seen_key)
        result.append(item)
    return result


def source_citations(contexts: list[dict]) -> list[dict]:
    citations = []
    seen = set()
    for item in contexts:
        source_id = item["source_id"]
        page_number = item.get("page_number")
        url = citation_url(item)
        seen_key = (source_id, page_number or url)
        if seen_key in seen:
            continue
        seen.add(seen_key)
        citations.append(
            {
                "title": item["title"],
                "url": url,
                "source_id": source_id,
                "page_number": page_number,
            }
        )
    return citations


def citation_url(item: dict) -> str:
    url = item["url"]
    source_id = item["source_id"]
    page_number = item.get("page_number")
    page_suffix = f"#page={page_number}" if page_number else ""
    if source_id.startswith("manual-") and url.lower().endswith(".pdf"):
        return f"/api/manuals/{source_id}{page_suffix}"
    if page_number and url.lower().endswith(".pdf"):
        return f"{url}{page_suffix}"
    return url


def build_contextual_rag_query(message: str, history: list[dict]) -> str:
    recent_user_messages = [
        strip_image_note(item["content"])
        for item in history[-6:]
        if item["role"] == "user" and strip_image_note(item["content"])
    ]
    query_parts = [*recent_user_messages[-3:], message]
    return "\n".join(dict.fromkeys(part.strip() for part in query_parts if part.strip()))


async def build_normalized_rag_query(message: str, history: list[dict]) -> tuple[str, str | None]:
    base_query = build_contextual_rag_query(message, history)
    if not settings.has_api_key:
        return base_query, None
    try:
        normalized_query = await llm.rewrite_search_query(base_query)
    except Exception:
        return base_query, None
    return base_query, normalized_query


def build_llm_history(history: list[dict]) -> list[dict]:
    llm_messages = []
    for item in history:
        if item["role"] not in {"user", "assistant"}:
            continue
        text = strip_image_note(item["content"])
        if item["role"] == "user":
            content = build_message_content(text, extract_image_paths(item["content"]), settings)
        else:
            content = text
        llm_messages.append({"role": item["role"], "content": content})
    return llm_messages


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    image_paths: list[str] = []


class SessionRequest(BaseModel):
    title: str = "Новый диалог"


class SourceRequest(BaseModel):
    title: str
    url: str
    type: str = "web"


class SourceUpdateRequest(BaseModel):
    title: str
    type: str
    url: str | None = None


class ReindexRequest(BaseModel):
    mode: str = "all"


@app.get("/")
async def index():
    return FileResponse(ROOT_DIR / "app" / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "has_api_key": settings.has_api_key,
        "api_key_env": settings.api_key_env_name,
        "llm_base_url": settings.openai_base_url,
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "langfuse_configured": settings.langfuse_configured,
        "langfuse_enabled": telemetry.enabled,
        "langfuse_environment": settings.langfuse_environment,
    }


# ---------- Auth endpoints ----------

@app.post("/api/auth/register")
async def auth_register(payload: RegisterRequest, response: Response):
    email = normalize_email(payload.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Некорректный email.")
    if len(payload.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Пароль должен быть не короче {MIN_PASSWORD_LEN} символов.")
    if user_store.get_by_email(email):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")
    invite = user_store.find_valid_invite(payload.invite_code.strip())
    if not invite:
        raise HTTPException(status_code=400, detail="Неверный или просроченный код приглашения.")
    user = user_store.create_user(
        email=email,
        password_hash=hash_password(payload.password),
        role=invite["role"],
        display_name=(payload.display_name or "").strip() or None,
    )
    user_store.consume_invite(invite["id"])
    token = create_access_token(
        user["id"], user["role"],
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_hours=settings.auth_session_hours,
    )
    _set_auth_cookie(response, token)
    return _user_public(user)


@app.post("/api/auth/login")
async def auth_login(payload: LoginRequest, response: Response):
    email = normalize_email(payload.email)
    user = user_store.get_by_email(email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный email или пароль.")
    token = create_access_token(
        user["id"], user["role"],
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_hours=settings.auth_session_hours,
    )
    _set_auth_cookie(response, token)
    return _user_public(user)


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    _clear_auth_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = get_optional_user(request)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": _user_public(user)}


# ---------- Admin: users & invites ----------

@app.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    return [_user_public(u) for u in user_store.list_users()]


@app.post("/api/admin/users/{user_id}/role")
async def admin_set_role(user_id: str, payload: RoleUpdateRequest, admin: dict = Depends(require_admin)):
    if user_id == admin["id"] and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Нельзя понизить себе роль.")
    if not user_store.set_role(user_id, payload.role):
        raise HTTPException(status_code=400, detail="Не удалось обновить роль.")
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Нельзя удалить собственный аккаунт.")
    deleted = user_store.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    return {"ok": True}


@app.get("/api/admin/invites")
async def admin_list_invites(admin: dict = Depends(require_admin)):
    return user_store.list_invites()


@app.post("/api/admin/invites")
async def admin_create_invite(payload: InviteCreateRequest, admin: dict = Depends(require_admin)):
    role = payload.role if payload.role in {"user", "admin"} else "user"
    code = generate_invite_code()
    return user_store.create_invite(
        code=code,
        role=role,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
        note=(payload.note or "").strip() or None,
        created_by=admin["id"],
    )


@app.delete("/api/admin/invites/{invite_id}")
async def admin_delete_invite(invite_id: str, admin: dict = Depends(require_admin)):
    if not user_store.delete_invite(invite_id):
        raise HTTPException(status_code=404, detail="Код приглашения не найден.")
    return {"ok": True}


# ---------- Session ownership guard ----------

def _ensure_session_access(session_id: str, user: dict) -> dict:
    """Verify that the user owns this session (or is admin)."""
    with db.connect() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Диалог не найден.")
    owner_id = row["user_id"]
    if owner_id and owner_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Нет доступа к диалогу.")
    return {"owner_id": owner_id}


@app.post("/api/llm-test")
async def llm_test(admin: dict = Depends(require_admin)):
    try:
        return await llm.smoke_test()
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM API недоступен: {exc}") from exc


@app.get("/api/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    # Admin sees only own sessions too (cleaner UX); could be changed to see all later.
    return chat_store.list_sessions(user_id=user["id"])


@app.post("/api/sessions")
async def create_session(payload: SessionRequest, user: dict = Depends(get_current_user)):
    return chat_store.create_session(payload.title, user_id=user["id"])


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str, user: dict = Depends(get_current_user)):
    _ensure_session_access(session_id, user)
    messages = chat_store.get_messages(session_id)
    for msg in messages:
        if msg["role"] == "user":
            paths = extract_image_paths(msg["content"])
            msg["content"] = strip_image_note(msg["content"])
            msg["image_urls"] = [url for url in (uploaded_image_url(p) for p in paths) if url]
        else:
            msg["image_urls"] = []
    return messages


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    _ensure_session_access(session_id, user)
    image_paths = chat_store.collect_image_paths(session_id)
    deleted = chat_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Диалог не найден.")
    removed_files = 0
    for path in image_paths:
        if delete_uploaded_image(path, settings):
            removed_files += 1
    if image_paths:
        logger.info("Session %s deleted: removed %d/%d image files", session_id, removed_files, len(image_paths))
    return {"ok": True, "removed_files": removed_files}


@app.post("/api/chat")
async def chat(payload: ChatRequest, user: dict = Depends(get_current_user)):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")

    if payload.session_id:
        _ensure_session_access(payload.session_id, user)
    session_id = chat_store.ensure_session(payload.session_id, user_id=user["id"])
    prior_messages = chat_store.get_messages(session_id)
    is_first_message = not prior_messages
    user_content = append_image_note(message, payload.image_paths)
    chat_store.add_message(session_id, "user", user_content)
    history = [
        *prior_messages,
        {"role": "user", "content": user_content},
    ][-settings.chat_history_window:]
    rag_query, normalized_rag_query = await build_normalized_rag_query(message, history)

    with telemetry.observation(
        "rag.search",
        as_type="retriever",
        input={"query": rag_query, "normalized_query": normalized_rag_query},
        metadata={
            "top_k": settings.rag_top_k,
            "has_api_key": settings.has_api_key,
            "history_messages": len(history),
            "attached_images": len(payload.image_paths),
            "query_normalized": normalized_rag_query is not None,
        },
        session_id=session_id,
        tags=["chat", "rag"],
        trace_name="chat",
    ) as rag_span:
        contexts = await rag.search(rag_query, query_variants=[normalized_rag_query] if normalized_rag_query else None)
        telemetry.update(
            rag_span,
            output={
                "results": len(contexts),
                "search_modes": sorted({item.get("search_mode", "unknown") for item in contexts}),
                "source_ids": [item.get("source_id", "") for item in contexts[:8]],
            },
        )

    if not settings.has_api_key:
        if contexts:
            citations = source_citations(contexts)
            found_places = "\n\n".join(
                (
                    f"{index}. {item['title']} · фрагмент {int(item['chunk_index']) + 1}\n"
                    f"Найденные слова: {', '.join(item.get('matched_terms') or []) or 'не указаны'}\n"
                    f"{item.get('snippet') or item['text'][:520]}"
                )
                for index, item in enumerate(contexts[:5], start=1)
            )
            sources = "\n".join(
                f"{index}. {item['title']}\n{item['url']}"
                for index, item in enumerate(citations, start=1)
            )
            answer = (
                "LLM API ключ пока не задан, поэтому я не генерирую полноценный ответ. "
                "Но база может работать в режиме keyword-поиска без расхода токенов.\n\n"
                f"Найденные места:\n{found_places}\n\n"
                f"Источники:\n{sources}"
            )
            chat_store.add_message(session_id, "assistant", answer, citations)
            return {"session_id": session_id, "answer": answer, "citations": citations}
        answer = (
            "Сервер и история диалога работают, но LLM API ключ пока не задан. "
            "Нажмите «Переиндексировать» во вкладке «База знаний», чтобы подготовить keyword-базу без расхода токенов. "
            f"После добавления `{settings.api_key_env_name}` заработают полноценные ответы LLM и vector RAG."
        )
        chat_store.add_message(session_id, "assistant", answer, [])
        return {"session_id": session_id, "answer": answer, "citations": []}

    contexts = deduplicate_contexts(contexts)

    if not contexts and not payload.image_paths:
        chat_store.add_message(session_id, "assistant", EMPTY_RAG_WARNING, [])
        return {"session_id": session_id, "answer": EMPTY_RAG_WARNING, "citations": [], "kind": "knowledge-warning"}

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(build_llm_history(history[:-1]))
    messages.append(
        {
            "role": "user",
            "content": build_message_content(
                build_user_prompt(message, contexts, rag_query),
                payload.image_paths,
                settings,
            ),
        }
    )

    try:
        with telemetry.observation(
            "chat.answer",
            input={
                "message": message,
                "contexts_count": len(contexts),
                "attached_images": len(payload.image_paths),
            },
            metadata={
                "history_messages": len(history),
                "citations": len(source_citations(contexts)),
                "rag_query_chars": len(rag_query),
            },
            session_id=session_id,
            tags=["chat", "answer"],
            trace_name="chat",
        ) as answer_span:
            answer = await llm.chat(messages)
            telemetry.update(answer_span, output={"answer_chars": len(answer)})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка LLM API: {exc}") from exc

    citations = source_citations(contexts)
    chat_store.add_message(session_id, "assistant", answer, citations)

    # NOTE: AI title generation disabled to save Gemini API quota (rate-limit
    # mitigation on free tier). Title is set automatically by chat_store.add_message
    # from the first 80 chars of the user message (cleaned of image notes).
    return {
        "session_id": session_id,
        "answer": answer,
        "citations": citations,
        "title": None,
    }


@app.get("/api/materials")
async def materials(admin: dict = Depends(require_admin)):
    return source_store.list_sources()


@app.post("/api/materials")
async def add_material(payload: SourceRequest, admin: dict = Depends(require_admin)):
    title = payload.title.strip()
    url = payload.url.strip()
    source_type = payload.type.strip() or "web"
    if not title:
        raise HTTPException(status_code=400, detail="Название источника не может быть пустым.")
    try:
        return source_store.add_web_source(title, url, source_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/materials/{source_id}")
async def delete_material(source_id: str, admin: dict = Depends(require_admin)):
    deleted = source_store.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Источник не найден.")
    return {"ok": True}


@app.patch("/api/materials/{source_id}")
async def update_material(source_id: str, payload: SourceUpdateRequest, admin: dict = Depends(require_admin)):
    try:
        return source_store.update_source(source_id, payload.title, payload.type, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/manuals/{source_id}")
async def open_manual(source_id: str, user: dict = Depends(get_current_user)):
    from fastapi.responses import RedirectResponse

    source_store.sync_metadata()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT title, path, blob_url FROM sources WHERE id = ? AND origin = 'manual'",
            (source_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Методичка не найдена.")

    # Prefer Vercel Blob (persistent across deploys and accessible from prod).
    # The browser automatically appends any #page=N fragment from the original
    # URL to the redirect target.
    blob_url = row["blob_url"] if "blob_url" in row.keys() else None
    if blob_url:
        return RedirectResponse(url=blob_url, status_code=302)

    if not row["path"]:
        raise HTTPException(status_code=404, detail="Методичка не найдена.")
    path = Path(row["path"])
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF-файл методички не найден.")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


@app.post("/api/reindex")
async def reindex(payload: ReindexRequest | None = None, admin: dict = Depends(require_admin)):
    mode = (payload.mode if payload else "all").strip().lower()
    if mode not in {"all", "new"}:
        raise HTTPException(status_code=400, detail="Режим переиндексации должен быть all или new.")
    try:
        return await rag.reindex(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка переиндексации: {exc}") from exc


@app.post("/api/uploads/images")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можно загружать только изображения.")
    body = await file.read()
    safe_name = Path(file.filename or "image").name

    # Production path: upload to Vercel Blob if configured.
    if settings.blob_read_write_token:
        try:
            result = vercel_blob_upload(safe_name, body, content_type, settings.blob_read_write_token)
        except Exception as exc:
            logger.error("Vercel Blob upload failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"Ошибка Vercel Blob: {exc}") from exc
        url = result.get("url") or result.get("downloadUrl")
        if not url:
            logger.error("Vercel Blob returned unexpected payload: %s", result)
            raise HTTPException(status_code=502, detail="Vercel Blob не вернул url.")
        return {"ok": True, "path": url, "name": safe_name}

    # Local dev fallback: write to disk.
    upload_dir = settings.data_dir / "uploads" / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / safe_name
    index = 1
    while target.exists():
        target = upload_dir / f"{target.stem}-{index}{target.suffix}"
        index += 1
    target.write_bytes(body)
    return {"ok": True, "path": uploaded_image_reference(target, settings), "name": target.name}


@app.get("/api/tools")
async def tools(user: dict = Depends(get_current_user)):
    return list_tools()


@app.post("/api/tools/{tool_id}/run")
async def run_tool(tool_id: str, user: dict = Depends(get_current_user)):
    return run_mock_tool(tool_id)
