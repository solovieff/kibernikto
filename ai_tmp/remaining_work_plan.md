# Kibernikto — оставшаяся работа после миграции

> План создан 2026-07-29. Все шаги миграции из `migration_plan.md` выполнены.

## Текущее состояние

- **Шаг 1** `KiberniktoExtended` — личность Kibernikto, ConversationInfo, ChatDataStorage (JSON), динамический system-prompt, списание кредитов ✅
- **Шаг 2** `WebExpert` — read_web, web_search, deep_search через Jina ✅
- **Шаг 3** `ImageExpert` — describe_image (vision), edit_image (img2img), generate_image из core ✅
- **Шаг 4** `ConversationExpert` — add_user_info, set_user_info, answer_on_full_history ✅
- **Шаг 5** `SchedulerExpert` — plan_event, plan_many, replan_event, delete_event, clear_all, set_user_timezone, JSON-хранилище ✅
- **Шаг 6** `ReportExpert` — generate_report (Jina deepsearch + VseGPT fallback), .txt через deps.attachments ✅
- **Шаг 7** `KnowledgeExpert` — **сознательно пропущен** (ChromaDB забыта, нужен новый RAG) ❌
- **Шаг 8** Сборка `DynamicWorkflow` + `SubAgents` в `__init__.py`, `--multi-agent` флаг в `cmd/__start.py` ✅

Telegram-интеграция (`kibernikto/telegram/`): TelegramAgent, TelegramApp, handlers, middlewares — работает.

### Storage — рефакторинг (июль 2026)

Выделен пакет `kibernikto/storage/`:
- `storage/base.py` — `MemoryHistoryStorage`, чистый in-memory, не зависит от конфига
- `storage/file/history.py` — `FileStoreHistoryStorage(name)`, JSON-персистентность, история у каждого агента своя (неймспейс в подпапке `history/{name}/`)
- `storage/file/chat_data.py` — `ChatDataStorage`, модульный синглтон `chat_data`, пользовательские данные (credits, private_info) общие для всех агентов (`chat_data/{chat_id}.json`)
- `storage/file/models.py` — `ConversationInfo` (вынесен для разрыва циркулярного импорта)
- `storage/file/__init__.py` — пустой (будет вычищен)
- `storage/__init__.py` — пустой (будет вычищен)
- `ai/agent/core/history.py` — backward-compat shim (`MemoryHistoryStorage` + синглтон `history_storage`)
- `KiberniktoAgent.__init__` принимает `history_storage: Optional[MemoryHistoryStorage]`, `None` = stateless
- `KiberniktoExtended` использует `FileStoreHistoryStorage(name=...)` для истории, `chat_data` синглтон для кредитов
- `ConversationExpert` использует `chat_data` синглтон для user info
- `APP_FILESTORE_LOCATION` в `config.py`, путь по умолчанию `~/.kibernikto`

✅ История персистентна, чат-данные общие, stateless-режим есть, циркулярных импортов нет.

## Что осталось

### 1. smart_reply — буферизация сообщений

В старом Kiberkalki была: подряд идущие сообщения пользователя склеиваются в один запрос. В новом боте не реализовано.

**Файлы:** `kibernikto/telegram/pre_processors/_default.py`

### 3. prepare_request в ReportExpert

В старом ReportExpert длинные запросы (>200 символов) сокращались через gpt-4o-mini до 1 предложения. В новом не реализовано.

**Файлы:** `kibernikto/ai/agent/extended/report_expert.py`

### 4. KnowledgeExpert — новый RAG

ChromaDB выброшена. Нужно:
- Выбрать хранилище: JSON-based индекс (TF-IDF/BM25), SQLite FTS5, или лёгкий embedding (напр. fastembed + numpy)
- Инструменты: answer_on_file, answer_on_whole_db, delete_file, list_documents
- Интеграция с главным агентом

**Файлы:** новый `kibernikto/ai/agent/extended/knowledge_expert.py`

### 5. Scheduler daemon

События сохраняются в JSON, но нет процесса, который их исполняет. Нужен отдельный демон (cron-подобный цикл), который читает события и отправляет уведомления в Telegram.

**Файлы:** новый `kibernikto/telegram/scheduler_daemon.py` или подобное

### 6. Демоны (daemons) — опционально

`_summon_daemons` / `moral_infiltrate_response` из старого Kiberkalki. Модификация ответа после генерации. Можно отложить или пропустить.

## Предлагаемый порядок

1. smart_reply — буферизация сообщений
2. Уведомление о смене модели
3. prepare_request в ReportExpert
4. KnowledgeExpert — новый RAG
5. Scheduler daemon
6. Демоны (опционально, отложено)
