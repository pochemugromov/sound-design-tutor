from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import ROOT_DIR, ensure_directories, get_settings
from app.services.chat_store import ChatStore
from app.services.db import Database
from app.services.llm import LLMNotConfigured, OpenAICompatibleClient
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt
from app.services.rag import RagService
from app.services.sources import SourceStore
from app.services.tools import list_tools, run_mock_tool


settings = get_settings()
ensure_directories(settings)
db = Database(settings.database_path)
db.init()
chat_store = ChatStore(db)
llm = OpenAICompatibleClient(settings)
source_store = SourceStore(db, settings)
rag = RagService(settings, llm, source_store)

app = FastAPI(title="AI Sound Design Assistant")
app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")


def source_citations(contexts: list[dict]) -> list[dict]:
    citations = []
    seen_urls = set()
    for item in contexts:
        url = item["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        citations.append(
            {
                "title": item["title"],
                "url": url,
                "source_id": item["source_id"],
            }
        )
    return citations


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


@app.get("/")
async def index():
    return FileResponse(ROOT_DIR / "app" / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "has_api_key": settings.has_api_key,
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
    }


@app.post("/api/llm-test")
async def llm_test():
    try:
        return await llm.smoke_test()
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM API недоступен: {exc}") from exc


@app.get("/api/sessions")
async def list_sessions():
    return chat_store.list_sessions()


@app.post("/api/sessions")
async def create_session(payload: SessionRequest):
    return chat_store.create_session(payload.title)


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    return chat_store.get_messages(session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = chat_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Диалог не найден.")
    return {"ok": True}


@app.post("/api/chat")
async def chat(payload: ChatRequest):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")

    session_id = chat_store.ensure_session(payload.session_id)
    attachment_note = ""
    if payload.image_paths:
        attachment_note = "\n\n[Прикрепленные изображения: " + ", ".join(payload.image_paths) + "]"
    chat_store.add_message(session_id, "user", message + attachment_note)

    contexts = await rag.search(message)

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
            "После добавления `OPENAI_API_KEY` заработают полноценные ответы LLM и vector RAG."
        )
        chat_store.add_message(session_id, "assistant", answer, [])
        return {"session_id": session_id, "answer": answer, "citations": []}

    if not contexts:
        answer = (
            "В базе знаний не найдено достаточно релевантных материалов для надежного ответа. "
            "Добавьте источники или выполните `ReIndex`, чтобы я мог отвечать с опорой на проверяемые материалы."
        )
        chat_store.add_message(session_id, "assistant", answer, [])
        return {"session_id": session_id, "answer": answer, "citations": []}

    history = chat_store.get_messages(session_id)[-8:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history:
        if item["role"] in {"user", "assistant"}:
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": build_user_prompt(message, contexts)})

    try:
        answer = await llm.chat(messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка LLM API: {exc}") from exc

    citations = source_citations(contexts)
    chat_store.add_message(session_id, "assistant", answer, citations)
    return {"session_id": session_id, "answer": answer, "citations": citations}


@app.get("/api/materials")
async def materials():
    return source_store.list_sources()


@app.post("/api/materials")
async def add_material(payload: SourceRequest):
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
async def delete_material(source_id: str):
    deleted = source_store.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Источник не найден.")
    return {"ok": True}


@app.patch("/api/materials/{source_id}")
async def update_material(source_id: str, payload: SourceUpdateRequest):
    try:
        return source_store.update_source(source_id, payload.title, payload.type, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/reindex")
async def reindex():
    return await rag.reindex()


@app.post("/api/uploads/images")
async def upload_image(file: UploadFile = File(...)):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можно загружать только изображения.")
    upload_dir = settings.data_dir / "uploads" / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "image").name
    target = upload_dir / safe_name
    index = 1
    while target.exists():
        target = upload_dir / f"{target.stem}-{index}{target.suffix}"
        index += 1
    target.write_bytes(await file.read())
    return {"ok": True, "path": str(target.relative_to(ROOT_DIR)), "name": target.name}


@app.get("/api/tools")
async def tools():
    return list_tools()


@app.post("/api/tools/{tool_id}/run")
async def run_tool(tool_id: str):
    return run_mock_tool(tool_id)
