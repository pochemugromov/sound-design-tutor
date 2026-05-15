# AI Sound Design Assistant

Локальный MVP учебного AI-агента-наставника для ВКР по применению ИИ-агентов в обучении саунд-дизайну и работе в Ableton Live.

## Что входит в MVP

- веб-интерфейс на русском языке;
- чат с сохранением истории диалогов в SQLite;
- новый диалог создается как черновик и попадает в историю только после первого сообщения;
- RAG-пайплайн через ChromaDB;
- Gemini API через OpenAI-compatible endpoint и `.env`;
- вкладка `Materials` со списком источников и кнопкой `ReIndex`;
- вкладка `Курсы` с учебными траекториями агента-методиста, модулями и локальным прогрессом;
- добавление и удаление web-источников через вкладку `Materials`;
- ручное пополнение базы через `data/manual` и удаление manual-источников из интерфейса;
- удаление диалогов из левого меню;
- загрузка изображений с передачей в мультимодальную LLM для анализа интерфейса, проекта, ошибок и цепочек эффектов;
- вкладка `Tools` с архитектурными заготовками под агента-критика, методиста, генератор заданий и анализ аудио/проекта.

## Курсы и агент-методист

Вкладка `Курсы` показывает базовые учебные траектории:

- `Старт в Ableton Live`;
- `Основы обработки звука`;
- `Работа с AI-наставником`.

Прогресс модулей хранится локально в браузере через `localStorage`. Это демонстрационный слой для ВКР: он показывает, как агент-методист может структурировать обучение, отслеживать этапы и направлять студента от теории к практике и самопроверке.

## Локальный запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Откройте `.env` и добавьте свой ключ:

```env
GEMINI_API_KEY=your_key_here
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
CHAT_MODEL=gemini-3-flash-preview
EMBEDDING_MODEL=gemini-embedding-001
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_CAPTURE_IO=true
```

Настоящий ключ хранится только в локальном `.env`. Этот файл уже добавлен в `.gitignore`, поэтому он не должен попадать в репозиторий. Для Vercel или другого хостинга ключ нужно добавлять в Environment Variables, а не загружать `.env` в проект.

Langfuse собирает трассы backend-запросов `/api/*`, RAG-поиска, LLM-вызовов и embeddings. Для приватности секреты и API-ключи автоматически редактируются перед отправкой в Langfuse. Если не нужно сохранять тексты запросов и ответов в Langfuse Cloud, установите `LANGFUSE_CAPTURE_IO=false`.

Запуск сервера:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте:

```text
http://127.0.0.1:8000
```

## Деплой на Vercel

В проект добавлены `api/index.py` и `vercel.json`, чтобы Vercel явно запускал FastAPI-приложение как Python Function и отправлял все пути в backend. Если появляется `404: NOT_FOUND` или браузер скачивает `.py` файл, Vercel задеплоил репозиторий без корректного Python Function entrypoint.

Настройки Vercel:

- Framework Preset: `Other`.
- Build Command: оставить пустым.
- Output Directory: оставить пустым.
- Install Command: `pip install -r requirements.txt`.
- Environment Variables: добавить `GEMINI_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`, `LANGFUSE_TRACING_ENABLED=true`, `LANGFUSE_TRACING_ENVIRONMENT=production` и при необходимости `LLM_BASE_URL`, `CHAT_MODEL`, `EMBEDDING_MODEL`.

На Vercel runtime-файлы SQLite, ChromaDB и загруженные материалы пишутся во временную директорию `/tmp`. Это подходит для демо MVP, но не для постоянного хранения: после cold start данные могут быть пересозданы. Для production-версии нужна внешняя БД и отдельное хранилище файлов.

## Индексация базы знаний

1. Откройте вкладку `Materials`.
2. Нажмите `ReIndex`.

Индексатор скачивает доступные web/PDF-источники из `data/sources.json`, сохраняет извлеченный текст в `data/raw` и строит ChromaDB-индекс в `data/chroma`.

Чтобы ограничить расход embeddings, по умолчанию индексируется не больше `RAG_MAX_CHUNKS_PER_SOURCE=24` фрагментов на источник. Значение можно увеличить в `.env`.

Если `GEMINI_API_KEY` не задан, `ReIndex` все равно скачает источники, извлечет текст, нарежет chunks и включит keyword-поиск без расхода токенов. После добавления ключа повторный `ReIndex` создаст полноценный векторный индекс.

Если источник недоступен или содержит только короткую metadata-страницу, он получает статус `unavailable` или `metadata_only` и не используется как прочитанный материал в ответах агента.

## Ручное добавление материалов

Через вкладку `Materials` можно добавить открытый HTML-источник или прямую PDF-ссылку. Лучше всего читаются:

- обычные статьи и документация с серверным HTML;
- официальные help/manual страницы;
- прямые PDF-файлы с текстовым слоем.

Плохо извлекаются или будут помечены как `metadata_only`/`unavailable`:

- страницы, где весь текст отрисовывается JavaScript;
- закрытые DOI, paywall и страницы с авторизацией;
- PDF-сканы без текстового слоя.

Для локальных материалов положите легально доступные `.md`, `.txt` или `.pdf` файлы в:

```text
data/manual
```

Затем нажмите `ReIndex` во вкладке `Materials`. Если файл удалить из `data/manual`, список материалов обновится после следующего открытия вкладки или нажатия `ReIndex`.

## Важные ограничения

- Файлы практик `novitskiy_praktika_1.md` и `novitskiy_praktika_2.md` не используются в RAG и не показываются во вкладке `Materials`.
- Агент не должен выдавать готовые творческие решения, пресеты или законченные цепочки эффектов вместо студента.
- При недостатке контекста агент обязан сообщить, что данных в базе знаний недостаточно.
- Настоящий `.env`, SQLite-база, ChromaDB и скачанные raw-материалы не коммитятся.

## Проверка LLM

После добавления ключа можно выполнить короткий тест API:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/llm-test
```

Этот endpoint отправляет минимальный запрос к модели и не запускает индексацию.
