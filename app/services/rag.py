from __future__ import annotations

import asyncio
from collections import Counter
from difflib import get_close_matches
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from bs4 import BeautifulSoup
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
    "какой",
    "какая",
    "какие",
    "какое",
    "где",
    "почему",
    "зачем",
    "можно",
    "нужно",
    "надо",
    "сделать",
    "делать",
    "найти",
    "работает",
    "работать",
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
    "бочка": ["kick", "drum"],
    "бочки": ["kick", "drum"],
    "бас": ["bass"],
    "баса": ["bass"],
    "сайдчейн": ["sidechain", "compressor", "compression"],
    "сайдчейна": ["sidechain", "compressor", "compression"],
    "сайдчейнить": ["sidechain", "compressor", "compression"],
    "трек": ["track"],
    "трека": ["track"],
    "треки": ["tracks"],
    "ретюрн": ["return", "send"],
    "ретерн": ["return", "send"],
    "return": ["return", "send"],
    "посыл": ["send", "return"],
    "посылы": ["sends", "return"],
    "сенд": ["send", "return"],
    "сенды": ["sends", "return"],
    "channel": ["track", "channel", "routing"],
    "канал": ["track", "channel", "routing"],
    "каналы": ["track", "channel", "routing"],
}

RU_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яё]", text, flags=re.IGNORECASE))


def transliterate_ru(text: str) -> str:
    return text.lower().translate(RU_TO_LATIN)


def english_vocabulary(rows) -> set[str]:
    vocabulary = set()
    for row in rows:
        vocabulary.update(re.findall(r"[a-z][a-z0-9]{2,}", row["search_text"]))
    return vocabulary


def add_transliteration_matches(terms: Counter, query_terms: list[str], vocabulary: set[str]) -> None:
    if not vocabulary:
        return
    for term in query_terms:
        if term in STOPWORDS or not has_cyrillic(term) or len(term) < 5:
            continue
        latin = transliterate_ru(term)
        if not latin:
            continue
        first_letter_matches = [word for word in vocabulary if word[0] == latin[0] and abs(len(word) - len(latin)) <= 4]
        for match in get_close_matches(latin, first_letter_matches, n=3, cutoff=0.55):
            terms[match] += 2


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


def chunk_pages(page_texts: list[tuple[int, str]]) -> list[dict]:
    chunks = []
    for page_number, page_text in page_texts:
        for chunk in chunk_text(page_text):
            chunks.append({"text": chunk, "page_number": page_number})
    return chunks


def chunk_body(chunk) -> str:
    return chunk["text"] if isinstance(chunk, dict) else chunk


def chunk_page_number(chunk) -> int | None:
    if not isinstance(chunk, dict):
        return None
    page_number = chunk.get("page_number")
    return int(page_number) if page_number else None


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
        # In Postgres mode (DATABASE_URL set), vectors live in source_chunks.embedding via pgvector.
        # In SQLite mode, fall back to ChromaDB on local disk.
        self.vector_backend = "pgvector" if self.settings.database_url else "chromadb"

    def _client(self):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        return chromadb.PersistentClient(
            path=str(self.settings.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _collection(self):
        if self.vector_backend == "pgvector":
            return "pgvector"  # truthy sentinel; pgvector paths read from DB directly
        client = self._client()
        return client.get_or_create_collection(
            COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _to_vector_literal(embedding) -> str:
        return "[" + ",".join(repr(float(x)) for x in embedding) + "]"

    async def reindex(self, mode: str = "all") -> dict:
        if mode not in {"all", "new"}:
            raise ValueError("Неизвестный режим переиндексации.")

        self.source_store.sync_metadata()
        current_sources = self.source_store.list_sources()
        target_source_ids = None
        if mode == "new":
            target_source_ids = {
                source["id"]
                for source in current_sources
                if source["status"] == "pending"
            }

        if mode == "all":
            self._clear_prepared_chunks()

        collection = None
        if self.settings.has_api_key:
            if mode == "all":
                self._reset_vector_collection()
            collection = self._collection()

        prepared = 0
        embedded = 0
        unavailable = 0
        metadata_only = 0
        skipped = 0

        for source in self.source_store.configured_sources():
            if target_source_ids is not None and source["id"] not in target_source_ids:
                skipped += 1
                continue
            try:
                result = await self._process_web_source(source, collection)
            except Exception as exc:
                self.source_store.update_status(source["id"], "unavailable", 0, f"Ошибка индексации: {exc}")
                unavailable += 1
                continue
            prepared += result["prepared"]
            embedded += result["embedded"]
            unavailable += result["unavailable"]
            metadata_only += result["metadata_only"]
            await asyncio.sleep(0.1)

        for source in self.source_store.manual_sources():
            if target_source_ids is not None and source["id"] not in target_source_ids:
                skipped += 1
                continue
            try:
                result = await self._process_manual_source(source, collection)
            except Exception as exc:
                self.source_store.update_status(source["id"], "unavailable", 0, f"Ошибка индексации: {exc}")
                unavailable += 1
                continue
            prepared += result["prepared"]
            embedded += result["embedded"]
            unavailable += result["unavailable"]
            metadata_only += result["metadata_only"]

        if mode == "new" and not (prepared or embedded or unavailable or metadata_only):
            message = "Новых источников для индексации нет."
        elif mode == "new":
            message = "Подготовка новых источников завершена."
        else:
            message = "Полная подготовка базы завершена."
        if self.settings.has_api_key and embedded:
            message += " Векторная индексация выполнена."
        elif self.settings.has_api_key:
            message += " Векторная база не изменялась."
        else:
            message += " API ключ не задан, поэтому работает keyword fallback без расхода токенов."
        return {
            "ok": True,
            "message": message,
            "mode": mode,
            "prepared": prepared,
            "indexed": embedded,
            "unavailable": unavailable,
            "metadata_only": metadata_only,
            "skipped": skipped,
        }

    def restore_keyword_index_from_raw(self) -> dict:
        self.source_store.sync_metadata()
        with self.source_store.db.connect() as conn:
            chunks_count = conn.execute("SELECT COUNT(*) AS count FROM source_chunks").fetchone()["count"]
        if chunks_count:
            return {"ok": True, "restored": 0, "skipped": True}

        restored = 0
        sources = [*self.source_store.configured_sources(), *self.source_store.manual_sources()]
        for source in sources:
            raw_path = self.settings.raw_dir / f"{source['id']}.txt"
            if not raw_path.exists():
                continue
            text = raw_path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._keyword_chunks(text)
            if not chunks:
                continue
            self._store_chunks(source, chunks)
            self.source_store.update_status(
                source["id"],
                "prepared",
                len(chunks),
                "Источник восстановлен из локального кэша без повторной загрузки.",
            )
            restored += 1
        return {"ok": True, "restored": restored, "skipped": False}

    async def search(self, query: str, top_k: int | None = None, query_variants: list[str] | None = None) -> list[dict]:
        variants = list(dict.fromkeys(item.strip() for item in [query, *(query_variants or [])] if item and item.strip()))
        if self.settings.has_api_key:
            vector_contexts = []
            for variant in variants:
                vector_contexts.extend(await self._vector_search(variant, top_k))
            vector_results = self._dedupe_contexts(vector_contexts)
            if vector_results:
                return vector_results[: top_k or self.settings.rag_top_k]
        return self.keyword_search("\n".join(variants), top_k)

    def _dedupe_contexts(self, contexts) -> list[dict]:
        deduped = []
        seen = set()
        for item in contexts:
            key = (item.get("source_id"), item.get("chunk_index"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def keyword_search(self, query: str, top_k: int | None = None) -> list[dict]:
        terms = expanded_query_terms(query)
        if not terms:
            return []
        with self.source_store.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_id, title, url, chunk_index, page_number, text, search_text
                FROM source_chunks
                """
            ).fetchall()

        query_terms = [term for term in tokenize(query) if term not in STOPWORDS]
        add_transliteration_matches(terms, query_terms, english_vocabulary(rows))
        query_phrase = normalize_for_search(query)
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
                    "page_number": row["page_number"],
                    "distance": None,
                    "search_mode": "keyword",
                    "score": score,
                    "matched_terms": matched,
                }
            )
        return contexts

    async def _vector_search(self, query: str, top_k: int | None = None) -> list[dict]:
        try:
            query_embedding = (await self.llm.embed([query]))[0]
        except Exception:
            return []
        if self.vector_backend == "pgvector":
            return self._vector_search_pgvector(query_embedding, top_k)
        return self._vector_search_chromadb(query_embedding, top_k)

    def _vector_search_chromadb(self, query_embedding, top_k: int | None) -> list[dict]:
        collection = self._collection()
        try:
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
                    "page_number": metadata.get("page_number") or None,
                    "distance": distance,
                    "search_mode": "vector",
                }
            )
        return contexts

    def _vector_search_pgvector(self, query_embedding, top_k: int | None) -> list[dict]:
        limit = top_k or self.settings.rag_top_k
        vec_literal = self._to_vector_literal(query_embedding)
        try:
            with self.source_store.db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT c.id, c.text, c.title, c.url, c.source_id, c.chunk_index, c.page_number,
                           (c.embedding <=> ?::vector) AS distance
                    FROM source_chunks c
                    WHERE c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> ?::vector
                    LIMIT ?
                    """,
                    (vec_literal, vec_literal, limit),
                ).fetchall()
        except Exception:
            return []
        contexts = []
        for row in rows:
            distance = row["distance"]
            if distance is not None and distance > self.settings.rag_score_threshold:
                continue
            contexts.append(
                {
                    "text": row["text"],
                    "title": row["title"],
                    "url": row["url"],
                    "source_id": row["source_id"],
                    "chunk_index": row["chunk_index"],
                    "page_number": row["page_number"] or None,
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

    def _clear_source_chunks(self, source_id: str) -> None:
        with self.source_store.db.connect() as conn:
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))

    def _reset_vector_collection(self) -> None:
        if self.vector_backend == "pgvector":
            try:
                with self.source_store.db.connect() as conn:
                    conn.execute("UPDATE source_chunks SET embedding = NULL")
            except Exception:
                pass
            return
        self.settings.chroma_path.mkdir(parents=True, exist_ok=True)
        client = self._client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    def _delete_source_vectors(self, collection, source_id: str) -> None:
        if self.vector_backend == "pgvector":
            try:
                with self.source_store.db.connect() as conn:
                    conn.execute("UPDATE source_chunks SET embedding = NULL WHERE source_id = ?", (source_id,))
            except Exception:
                pass
            return
        try:
            collection.delete(where={"source_id": source_id})
        except Exception:
            pass

    def _store_chunks(self, source: dict, chunks: list[str]) -> None:
        now = utc_now()
        rows = []
        for index, chunk in enumerate(chunks):
            text = chunk_body(chunk)
            rows.append(
                (
                    f"{source['id']}:{index}",
                    source["id"],
                    source["title"],
                    source["url"],
                    index,
                    chunk_page_number(chunk),
                    text,
                    normalize_for_search(text),
                    now,
                )
            )
        if not rows:
            return
        with self.source_store.db.connect() as conn:
            cur = conn.cursor()
            cur.executemany(
                """
                INSERT INTO source_chunks (id, source_id, title, url, chunk_index, page_number, text, search_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    async def _index_chunks(self, collection, source: dict, chunks: list[str]) -> None:
        ids = [f"{source['id']}:{index}" for index in range(len(chunks))]
        texts = [chunk_body(chunk) for chunk in chunks]
        embeddings = []
        batch_size = 32
        for start in range(0, len(texts), batch_size):
            embeddings.extend(await self.llm.embed(texts[start : start + batch_size]))

        if self.vector_backend == "pgvector":
            # Embeddings are stored directly in source_chunks.embedding (matched by id).
            update_rows = [
                (self._to_vector_literal(embedding), chunk_id)
                for chunk_id, embedding in zip(ids, embeddings)
            ]
            with self.source_store.db.connect() as conn:
                cur = conn.cursor()
                cur.executemany(
                    "UPDATE source_chunks SET embedding = ?::vector WHERE id = ?",
                    update_rows,
                )
            return

        metadatas = []
        for index, chunk in enumerate(chunks):
            metadata = {
                "source_id": source["id"],
                "title": source["title"],
                "url": source["url"],
                "type": source.get("type", ""),
                "chunk_index": index,
            }
            page_number = chunk_page_number(chunk)
            if page_number:
                metadata["page_number"] = page_number
            metadatas.append(metadata)
        collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)

    async def _process_web_source(self, source: dict, collection) -> dict[str, int]:
        result = await self._load_remote_source(source)
        if not result["text"]:
            self.source_store.update_status(source["id"], result["status"], 0, result["note"])
            return {
                "prepared": 0,
                "embedded": 0,
                "unavailable": 0 if result["status"] == "metadata_only" else 1,
                "metadata_only": 1 if result["status"] == "metadata_only" else 0,
            }

        keyword_chunks = self._keyword_chunks(result["text"])
        if not keyword_chunks:
            self.source_store.update_status(source["id"], "metadata_only", 0, "Текст найден, но он слишком короткий для чанков.")
            return {"prepared": 0, "embedded": 0, "unavailable": 0, "metadata_only": 1}

        self._clear_source_chunks(source["id"])
        if collection is not None:
            self._delete_source_vectors(collection, source["id"])
        self._store_chunks(source, keyword_chunks)

        embedded = 0
        if collection is not None:
            await self._index_chunks(collection, source, self._embedding_chunks(keyword_chunks))
            embedded = 1
            status = "indexed"
            note = "Источник загружен, подготовлен и добавлен в векторный индекс."
        else:
            status = "prepared"
            note = "Источник загружен и подготовлен для keyword-поиска. Векторный индекс будет создан после добавления API ключа."
        self.source_store.update_status(source["id"], status, len(keyword_chunks), note)
        return {"prepared": 1, "embedded": embedded, "unavailable": 0, "metadata_only": 0}

    async def _process_manual_source(self, source: dict, collection) -> dict[str, int]:
        keyword_chunks = self._read_manual_source_chunks(source)
        if not keyword_chunks:
            self.source_store.update_status(source["id"], "unavailable", 0, "Файл пустой или не читается.")
            return {"prepared": 0, "embedded": 0, "unavailable": 1, "metadata_only": 0}

        raw_path = self.settings.raw_dir / f"{source['id']}.txt"
        raw_path.write_text("\n\n".join(chunk_body(chunk) for chunk in keyword_chunks), encoding="utf-8")
        self._clear_source_chunks(source["id"])
        if collection is not None:
            self._delete_source_vectors(collection, source["id"])
        self._store_chunks(source, keyword_chunks)

        embedded = 0
        if collection is not None:
            await self._index_chunks(collection, source, self._embedding_chunks(keyword_chunks))
            embedded = 1
            status = "indexed"
            note = "Локальный материал подготовлен и добавлен в векторный индекс."
        else:
            status = "prepared"
            note = "Локальный материал подготовлен для keyword-поиска."
        self.source_store.update_status(source["id"], status, len(keyword_chunks), note)
        return {"prepared": 1, "embedded": embedded, "unavailable": 0, "metadata_only": 0}

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

    def _read_manual_source_chunks(self, source: dict) -> list:
        path = Path(source["path"])
        if path.suffix.lower() in {".md", ".txt"}:
            return self._keyword_chunks(path.read_text(encoding="utf-8", errors="ignore"))
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            chunks = chunk_pages(
                [
                    (index, page.extract_text() or "")
                    for index, page in enumerate(reader.pages, start=1)
                ]
            )
            if self.settings.rag_max_keyword_chunks_per_source > 0:
                return chunks[: self.settings.rag_max_keyword_chunks_per_source]
            return chunks
        return []
