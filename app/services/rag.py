from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile

from bs4 import BeautifulSoup
import chromadb
import httpx
from pypdf import PdfReader

from app.config import Settings
from app.services.db import utc_now
from app.services.llm import OpenAICompatibleClient
from app.services.sources import SourceStore


COLLECTION_NAME = "sound_design_knowledge"

STOPWORDS = {
    "что",
    "это",
    "такое",
    "как",
    "где",
    "для",
    "или",
    "при",
    "про",
    "мне",
    "его",
    "она",
    "они",
    "the",
    "and",
    "for",
    "with",
    "what",
    "where",
    "how",
    "why",
    "live",
    "ableton",
}


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]{3,}", normalize_for_search(text), flags=re.IGNORECASE)


QUERY_SYNONYMS = {
    "звук": ["sound", "audio", "signal"],
    "звука": ["sound", "audio", "signal"],
    "глух": ["dull", "muffled", "filter", "lowpass"],
    "глухим": ["dull", "muffled", "filter", "lowpass"],
    "фильтр": ["filter", "lowpass", "highpass"],
    "фильтра": ["filter", "lowpass", "highpass"],
    "эквалайзер": ["equalizer", "eq"],
    "реверберация": ["reverb"],
    "реверб": ["reverb"],
    "задержка": ["delay"],
    "компрессор": ["compressor", "compression"],
    "компрессия": ["compressor", "compression"],
    "клип": ["clip"],
    "дорожка": ["track"],
    "дорожки": ["track"],
    "сэмпл": ["sample"],
    "сэмплы": ["samples"],
    "миди": ["midi"],
    "синтезатор": ["synthesizer", "synth"],
    "синтез": ["synthesis", "synth"],
    "ableton": ["ableton", "live"],
    "mixer": ["mixing", "mixer", "routing"],
    "микшер": ["mixer", "mixing"],
    "микшере": ["mixer", "mixing"],
    "channel": ["track", "channel", "routing"],
    "канал": ["track", "channel", "routing"],
    "каналы": ["track", "channel", "routing"],
}


def expanded_query_terms(query: str) -> Counter:
    terms = Counter(term for term in tokenize(query) if term not in STOPWORDS)
    for term in list(terms):
        for synonym in QUERY_SYNONYMS.get(term, []):
            terms[synonym] += 1
    return terms


def matched_terms_in_text(text: str, terms: Counter) -> list[str]:
    text_tokens = set(tokenize(text))
    return [term for term in terms if term in text_tokens]


def best_keyword_snippet(text: str, terms: Counter, size: int = 520) -> str:
    normalized = normalize_for_search(text)
    positions = [normalized.find(term) for term in terms if normalized.find(term) >= 0]
    if not positions:
        return text[:size].strip()
    center = min(positions)
    start = max(0, center - size // 3)
    end = min(len(text), start + size)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def chunk_text(text: str, size: int = 1400, overlap: int = 220) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if len(chunk) > 120]


class RagService:
    def __init__(
        self,
        settings: Settings,
        llm: OpenAICompatibleClient,
        source_store: SourceStore,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.source_store = source_store

    def _client(self):
        return chromadb.PersistentClient(path=str(self.settings.chroma_path))

    def _collection(self):
        client = self._client()
        return client.get_or_create_collection(
            COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def reindex(self) -> dict:
        self.source_store.sync_metadata()
        self._clear_prepared_chunks()

        collection = None
        if self.settings.has_api_key:
            if self.settings.chroma_path.exists():
                shutil.rmtree(self.settings.chroma_path)
            self.settings.chroma_path.mkdir(parents=True, exist_ok=True)
            collection = self._collection()

        prepared = 0
        embedded = 0
        unavailable = 0
        metadata_only = 0

        for source in self.source_store.configured_sources():
            result = await self._load_remote_source(source)
            if not result["text"]:
                if result["status"] == "metadata_only":
                    metadata_only += 1
                else:
                    unavailable += 1
                self.source_store.update_status(source["id"], result["status"], 0, result["note"])
                continue

            keyword_chunks = self._keyword_chunks(result["text"])
            if not keyword_chunks:
                unavailable += 1
                self.source_store.update_status(source["id"], "metadata_only", 0, "Текст найден, но он слишком короткий для чанков.")
                continue
            self._store_chunks(source, keyword_chunks)
            prepared += 1

            if collection is not None:
                await self._index_chunks(collection, source, self._embedding_chunks(keyword_chunks))
                embedded += 1
                status = "indexed"
                note = "Источник загружен, подготовлен и добавлен в векторный индекс."
            else:
                status = "prepared"
                note = "Источник загружен и подготовлен для keyword-поиска. Векторный индекс будет создан после добавления API ключа."
            self.source_store.update_status(source["id"], status, len(keyword_chunks), note)
            await asyncio.sleep(0.1)

        for source in self.source_store.manual_sources():
            text = self._read_manual_source(source)
            keyword_chunks = self._keyword_chunks(text)
            if not keyword_chunks:
                unavailable += 1
                self.source_store.update_status(source["id"], "unavailable", 0, "Файл пустой или не читается.")
                continue
            self._store_chunks(source, keyword_chunks)
            prepared += 1
            if collection is not None:
                await self._index_chunks(collection, source, self._embedding_chunks(keyword_chunks))
                embedded += 1
                status = "indexed"
                note = "Локальный материал подготовлен и добавлен в векторный индекс."
            else:
                status = "prepared"
                note = "Локальный материал подготовлен для keyword-поиска."
            self.source_store.update_status(source["id"], status, len(keyword_chunks), note)

        message = "Подготовка базы завершена."
        if self.settings.has_api_key:
            message += " Векторная индексация выполнена."
        else:
            message += " API ключ не задан, поэтому работает keyword fallback без расхода токенов."
        return {
            "ok": True,
            "message": message,
            "prepared": prepared,
            "indexed": embedded,
            "unavailable": unavailable,
            "metadata_only": metadata_only,
        }

    async def search(self, query: str, top_k: int | None = None) -> list[dict]:
        if self.settings.has_api_key:
            vector_results = await self._vector_search(query, top_k)
            if vector_results:
                return vector_results
        return self.keyword_search(query, top_k)

    def keyword_search(self, query: str, top_k: int | None = None) -> list[dict]:
        terms = expanded_query_terms(query)
        if not terms:
            return []
        with self.source_store.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_id, title, url, chunk_index, text, search_text
                FROM source_chunks
                """
            ).fetchall()

        query_phrase = normalize_for_search(query)
        query_terms = [term for term in tokenize(query) if term not in STOPWORDS]
        requires_primary_match = any(re.search(r"[a-z]", term) for term in query_terms)
        scored = []
        for row in rows:
            search_text = row["search_text"]
            token_counts = Counter(tokenize(search_text))
            if requires_primary_match and not any(token_counts[term] for term in query_terms):
                continue
            matched = [term for term in terms if token_counts[term]]
            if not matched:
                continue
            score = sum(min(token_counts[term], 3) * weight for term, weight in terms.items())
            score += len(set(matched)) * 3
            if query_phrase and query_phrase in search_text:
                score += 12
            if len(query_terms) > 1:
                positions = [search_text.find(term) for term in query_terms if search_text.find(term) >= 0]
                if len(positions) >= 2 and max(positions) - min(positions) < 240:
                    score += 8
            if "ableton" in row["title"].lower():
                score += 2
            primary_matches = [term for term in query_terms if token_counts[term]]
            score += len(primary_matches) * 5
            if score:
                scored.append((score, dict(row), matched, primary_matches))
        scored.sort(key=lambda item: item[0], reverse=True)
        contexts = []
        for score, row, matched, primary_matches in scored[: top_k or self.settings.rag_top_k]:
            snippet_terms = Counter({term: terms[term] for term in primary_matches}) if primary_matches else terms
            contexts.append(
                {
                    "text": row["text"],
                    "snippet": best_keyword_snippet(row["text"], snippet_terms),
                    "title": row["title"],
                    "url": row["url"],
                    "source_id": row["source_id"],
                    "chunk_index": row["chunk_index"],
                    "distance": None,
                    "search_mode": "keyword",
                    "score": score,
                    "matched_terms": matched,
                }
            )
        return contexts

    async def _vector_search(self, query: str, top_k: int | None = None) -> list[dict]:
        collection = self._collection()
        try:
            query_embedding = (await self.llm.embed([query]))[0]
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k or self.settings.rag_top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        contexts = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            if distance is not None and distance > self.settings.rag_score_threshold:
                continue
            contexts.append(
                {
                    "text": document,
                    "title": metadata.get("title", ""),
                    "url": metadata.get("url", ""),
                    "source_id": metadata.get("source_id", ""),
                    "chunk_index": metadata.get("chunk_index", 0),
                    "distance": distance,
                    "search_mode": "vector",
                }
            )
        return contexts

    def _keyword_chunks(self, text: str) -> list[str]:
        chunks = chunk_text(text)
        if self.settings.rag_max_keyword_chunks_per_source > 0:
            return chunks[: self.settings.rag_max_keyword_chunks_per_source]
        return chunks

    def _embedding_chunks(self, chunks: list[str]) -> list[str]:
        if self.settings.rag_max_chunks_per_source > 0:
            return chunks[: self.settings.rag_max_chunks_per_source]
        return chunks

    def _clear_prepared_chunks(self) -> None:
        with self.source_store.db.connect() as conn:
            conn.execute("DELETE FROM source_chunks")

    def _store_chunks(self, source: dict, chunks: list[str]) -> None:
        now = utc_now()
        with self.source_store.db.connect() as conn:
            for index, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO source_chunks (id, source_id, title, url, chunk_index, text, search_text, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{source['id']}:{index}",
                        source["id"],
                        source["title"],
                        source["url"],
                        index,
                        chunk,
                        normalize_for_search(chunk),
                        now,
                    ),
                )

    async def _index_chunks(self, collection, source: dict, chunks: list[str]) -> None:
        ids = [f"{source['id']}:{index}" for index in range(len(chunks))]
        embeddings = []
        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            embeddings.extend(await self.llm.embed(chunks[start : start + batch_size]))
        metadatas = [
            {
                "source_id": source["id"],
                "title": source["title"],
                "url": source["url"],
                "type": source.get("type", ""),
                "chunk_index": index,
            }
            for index in range(len(chunks))
        ]
        collection.upsert(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)

    async def _load_remote_source(self, source: dict) -> dict:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(source["url"], headers={"User-Agent": "AI Sound Design Assistant MVP"})
            if response.status_code >= 400:
                return {"status": "unavailable", "text": "", "note": f"HTTP {response.status_code}"}
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" in content_type or source["url"].lower().endswith(".pdf"):
                text = self._extract_pdf_bytes(response.content)
            else:
                text = self._extract_html(response.text)
            if len(clean_text(text)) < 200:
                return {"status": "metadata_only", "text": "", "note": "Доступен только короткий HTML/metadata без содержательного текста."}
            raw_path = self.settings.raw_dir / f"{source['id']}.txt"
            raw_path.write_text(text, encoding="utf-8")
            return {"status": "prepared", "text": text, "note": "OK"}
        except Exception as exc:
            return {"status": "unavailable", "text": "", "note": str(exc)[:240]}

    def _extract_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        main = soup.find("main") or soup.body or soup
        return clean_text(main.get_text(" "))

    def _extract_pdf_bytes(self, content: bytes) -> str:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            reader = PdfReader(str(tmp_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _read_manual_source(self, source: dict) -> str:
        path = Path(source["path"])
        if path.suffix.lower() in {".md", ".txt"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return ""
