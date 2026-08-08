# Kibernikto — migration plan

> 2026-08-08. Актуальные задачи, коротко.

## Сделано

- **Storage**: file/pg/sqlite + S3, протоколы, graceful shutdown, per-message SQL history, `ensure_db_initialized()` только из `_on_startup` (не lazy)
- **Media**: `MediaFileStore`, imgbb-хостинг, URL в истории для image-to-image
- **Bot identity**: имя/описание бота из TG → system-prompt
- **Chat context**: `getChat` с TTL, аннотация групп
- **Markdown→HTML**: через `TG_MARKDOWN_TO_HTML`
- **Bot-to-bot защита**: приват игнор, группы без reply-цепочек
- **Эксперты**: web, image, conversation (scheduler/report временно выключены)

## Осталось (по приоритету)

### 1. Документы: PDF/txt
`_process_document` — заглушка. Извлечение текста, сохранение в `media/`, тул чтения по `media_ref`.
**Файлы:** `telegram/pre_processors/_default.py`, `ai/agent/core/`

### 2. smart_reply — буферизация сообщений
Склеивать подряд идущие сообщения в один запрос (было в Kiberkalki).
**Файлы:** `telegram/pre_processors/_default.py`

### 3. prepare_request в ReportExpert
Длинные запросы (>200 символов) сокращать через модель до 1 предложения.
**Файлы:** `ai/agent/harness/report_agent/report_expert.py`

### 4. KnowledgeExpert — новый RAG
Вместо ChromaDB: SQLite FTS5 или fastembed. Инструменты: answer_on_file, answer_on_whole_db, delete_file, list_documents.
**Файлы:** новый `ai/agent/harness/knowledge_agent/`

### 5. Scheduler daemon
Процесс, читающий события и шлющий уведомления в TG.
**Файлы:** новый `telegram/scheduler_daemon.py`

### 6. Стриминг ответов — sendMessageDraft
Слать черновик и обновлять по мере генерации.
**Файлы:** `telegram/utils/conversation.py`, `ai/agent/telegram/`

### 7. Уборка
- Пустые `__init__.py` в `storage/` и `storage/file/` (безвредны, можно оставить)
- `post()` в `utils/image.py` — legacy shim
- Старые env-переменные из env-файлов

### 8. Демоны (опционально, отложено)
`_summon_daemons` / `moral_infiltrate_response` из старого Kiberkalki.
