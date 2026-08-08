# Kibernikto — история изменений

> Архив: что и когда делалось. Актуальные задачи → `migration_plan.md`.

## Текущее состояние

- **Шаг 1** `KiberniktoExtended` — личность Kibernikto, ConversationInfo, ChatDataStorage (JSON), динамический system-prompt, списание кредитов ✅
- **Шаг 2** `WebExpert` — read_web, web_search, deep_search через Jina ✅
- **Шаг 3** `ImageExpert` — describe_image (vision), edit_image (img2img), generate_image из core ✅
- **Шаг 4** `ConversationExpert` — add_user_info, set_user_info, answer_on_full_history ✅
- **Шаг 5** `SchedulerExpert` — plan_event, plan_many, replan_event, delete_event, clear_all, set_user_timezone, JSON-хранилище ✅
- **Шаг 6** `ReportExpert` — generate_report (Jina deepsearch + VseGPT fallback), .txt через deps.attachments ✅
- **Шаг 8** Сборка `DynamicWorkflow` + `SubAgents` в `__init__.py`, `--multi-agent` флаг в `cmd/__start.py` ✅

Telegram-интеграция (`kibernikto/telegram/`): TelegramAgent, TelegramApp, handlers, middlewares — работает.

### Обновления после плана (2026-08-01, коммиты dd97696..0a8e3fa)

- **dd97696** — `ai_tmp/` untracked и в `.gitignore` (скретч-заметки остаются на диске, из репо убраны)
- **29218b7** — эксперты переехали из `ai/agent/extended/` в `ai/agent/harness/<agent>/` (web/image/conversation/scheduler/report), `harness/__init__.py` экспортирует всех; `extended/orchestrators.py` обновлён
- **29218b7** — добавлен `AGENT_KIBERNIKTO_KEEP_THINKING_IN_HISTORY` (по умолчанию false): `_sanitize` выкидывает `ThinkingPart` из истории; при true — оставляет текст, но снимает `signature`. Хвост из feeling_sorry #1 закрыт частично: текст thinking хранить можно, сигнатуру всё равно нет
- **dd0b50c** — chat context enrichment: `TelegramDeps.conversation_context` (факты из `getChat` с TTL 600s в `client_app_info`), аннотация групповых сообщений `[имя at время]` через `time_utils.enhance_message/get_user_time`, пустые поля убраны из `ConversationInfo.as_string`
- **0a8e3fa** — `.gitignore`: добавлен `.swmphst_filestore`

### Обновления после плана (2026-08-01, коммиты 9380b0d..c2f5dcb)

- **9380b0d** — защита от bot-to-bot loop: приват бот↔бот полностью пропускается (`process_message` → `None`), в группах бот-отправитель получает плоское сообщение без reply-цепочки (`reply_mode=False` в `_deliver_*`), задержка `BOT_MESSAGE_DELAY` сохранена. Аннотация групповых сообщений: для ботов — `@username`, для людей — `full_name` (было `full_name` для всех).
- **9380b0d** — markdown→HTML: `utils/text.py::markdown_to_html` (CommonMark-подмножество: **bold**, *italic*/_italic_ на границах слов, `` `code` ``, fenced-блоки с языком, `[text](url)`, `###` → `<b>`, `> ` → `<blockquote>`; остальное экранируется по `<>&`). Новый флаг `TG_MARKDOWN_TO_HTML` (default true) в `TelegramSettings`; при false — старое legacy `prepare_for_MARKDOWN`. `prepare_for_MARKDOWN` больше НЕ экранирует `_` слепо (двойное экранирование ломало `@swarm\_host\_bot`).
- **9380b0d** — в `text.py` починен `SyntaxWarning` (raw-строка в `remove_text_in_brackets_and_parentheses`).
- **c2f5dcb** — `.gitignore`: добавлен `.filestore`, убран `.swmphst_filestore`; `.run/swarmhost.run.xml` включает `env/kibernikto.env`; `KiberniktoExtended` берёт дефолтное имя из `AGENT_KIBERNIKTO_SETTINGS.NAME`; `orchestrators._EXPERT_AGENTS` урезан до web/image/conversation (scheduler/report временно выключены).

### Storage — рефакторинг (июль–август 2026) + S3/PostgreSQL backends (2026-08-08)

✅ Хранилища (`kibernikto/storage/`) — множественные бэкенды, формальные протоколы, graceful shutdown:
- `storage/base.py` — Protocols: `HistoryStorage`, `MediaStore`, `ChatDataStore` (runtime_checkable). `serialize_messages`/`deserialize_messages` — единый TypeAdapter. `_sanitize`/`_window` шарятся всеми бэкендами. `MemoryHistoryStorage` — одна из имплементаций.
- `storage/models.py` — `ConversationInfo` (общая модель для file/sql chat_data).
- `storage/config.py` — `StorageSettings` (env_prefix `APP_STORAGE_`): `DATA_BACKEND=file|pg|sqlite`, `MEDIA_BACKEND=file|s3`. Cross-field validation при импорте (pg без DSN → ValueError, s3 без ключей → ValueError). `validate_storage()` — connectivity check (pg SELECT 1, sqlite SELECT 1, s3 head_bucket) из `start()`.
- `storage/factory.py` — per-name lazy singletons, `shutdown_storage()`, полная типизация.
- `storage/singletons.py` — `_LazySingleton` proxy: `history_storage`, `chat_data`, `media_store`. isinstance работает через `__class__`.
- `storage/file/history.py` — `FileStoreHistoryStorage(name, root=)` — standalone, JSON-персистентность, `_loaded: set[int]`, общий adapter из base.
- `storage/file/chat_data.py` — `ChatDataStorage(root=)` — JSON, `root` в `__init__` (не class attribute).
- `storage/file/media.py` — `MediaFileStore` — async `save`/`read`, `tmp_path`, `cleanup_tmp`.
- `storage/sql/engine.py` — `ensure_db_initialized()` с `asyncio.Lock` (один раз за процесс, только из `_on_startup` или явно перед `agent.run()`), `get_session()` требует предварительной инициализации (иначе `RuntimeError`), `shutdown_db()`.
- `storage/sql/models.py` — `ChatMessageRow` (per-message: `id, chat_id, name, seq, kind, payload`), `ChatDataRow` — `server_default=func.now()`.
- `storage/sql/history.py` — `SqlHistoryStorage` — **per-message**: одно `ModelMessage` = одна строка в `chat_messages`. Нет in-memory кэша, нет whole-chat reads. `get_conversation` читает хвост (`HISTORY_SIZE * HISTORY_WINDOW_SLACK` строк) + `_window` в Python для request-boundary. `get_full_conversation` — без обрезки. `add_messages` — INSERT новых строк, `seq` = MAX(seq)+1 по `(chat_id, name)`. Не вызывает `ensure_db_initialized()`.
- `storage/sql/chat_data.py` — `SqlChatDataStorage` — не вызывает `ensure_db_initialized()` (engine должен быть инициализирован до первого использования).
- `storage/s3/media.py` — `S3MediaStore` — async `save`/`read`, retry config, `aclose()`. media_ref унифицирован: `{chat_id}/{file}`.
- `KiberniktoAgent.__init__` принимает `history_storage: Optional[HistoryStorage]`, `None` = stateless.
- `KiberniktoExtended` использует `get_history_storage(agent_name)` per-name, `chat_data` синглтон для кредитов.
- `telegram_app.py::_on_shutdown` → `shutdown_storage()` → dispose engine + close S3.
- **Удалены**: `storage/file/models.py`, `ai/agent/core/history.py`, PEP 562 `__getattr__` из file backends.

✅ История персистентна, чат-данные общие, stateless-режим есть, `instructions` не хранятся, циркулярных импортов нет, shutdown graceful, media_ref унифицирован, протоколы формальные.

### Media — мини-файлстор и хостинг (июль 2026)

Добавлено:
- `storage/file/media.py` — `MediaFileStore`: durable `media/{chat_id}/`, транзит `tmp/`
- `storage/base.py` — `_sanitize`/`_window` (шарится всеми бэкендами): история не хранит `ModelRequest.instructions` (перерезолвится), бинарники (`FilePart`) и подписи (`ThinkingPart.signature`) — на диске и в памяти; `storage/file/history.py` — реюз той же функции + миграция старых JSON
- `utils/image_hosting.py` — `ImageHosting` (ABC) + `ImgbbImageHosting`, выбор по `IMAGE_HOSTING_PROVIDER`; `utils/image.py` — compat shim
- Генерации бота: локальная копия в `media/` + публикация на imgbb + URL для истории; в копию финального ответа для истории дописывается TextPart с URL (`_annotate_generation`) — модель «видит» свою прошлую генерацию в собственном ответе (провайдер фетчит URL из текста), без хранения байтов
- imgbb TTL: `IMAGE_STORAGE_EXPIRATION` (секунды), по умолчанию 0 = без TTL
- Фото пользователя: durable-копия в `media/` (ключ — Telegram `file_unique_id`)
- Голос: транзит через `{FILESTORE}/tmp/` с очисткой после транскрипции

⚠️ `IMAGE_STORAGE_API_KEY` больше не захардкожен в коде — должен быть в env (`env/kibernikto.env`).

## Что осталось

### 1. Документы: PDF/txt в мини-файлстор и к агентам

`_process_document` в препроцессоре — заглушка (`PDF processing not yet implemented`). Нужно:
- Извлечение текста из PDF (pypdf / pdfminer) и чтение txt
- Сохранение в `media/` через `MediaFileStore`
- В историю — текст + `media_ref` в metadata (модель работает с текстом, агент дочитывает файл по рефу)
- Тул чтения файла по `media_ref` для агентов

**Файлы:** `kibernikto/telegram/pre_processors/_default.py`, `kibernikto/ai/agent/core/` (тул)

### 2. smart_reply — буферизация сообщений

В старом Kiberkalki была: подряд идущие сообщения пользователя склеиваются в один запрос. В новом боте не реализовано.

**Файлы:** `kibernikto/telegram/pre_processors/_default.py`

### 3. prepare_request в ReportExpert

В старом ReportExpert длинные запросы (>200 символов) сокращались через gpt-4o-mini до 1 предложения. В новом не реализовано.

**Файлы:** `kibernikto/ai/agent/harness/report_agent/report_expert.py`

### 4. KnowledgeExpert — новый RAG

ChromaDB выброшена. Нужно:
- Выбрать хранилище: JSON-based индекс (TF-IDF/BM25), SQLite FTS5, или лёгкий embedding (напр. fastembed + numpy)
- Инструменты: answer_on_file, answer_on_whole_db, delete_file, list_documents
- Интеграция с главным агентом

**Файлы:** новый `kibernikto/ai/agent/harness/knowledge_agent/`

### 5. Scheduler daemon

События сохраняются в JSON, но нет процесса, который их исполняет. Нужен отдельный демон (cron-подобный цикл), который читает события и отправляет уведомления в Telegram.

**Файлы:** новый `kibernikto/telegram/scheduler_daemon.py` или подобное

### 6. image-to-image по своим прошлым генерациям — ✅ закрыто

Работает через аннотацию URL в истории: `_annotate_generation` дописывает URL генерации как `TextPart` в копию ответа модели, модель передаёт его в `edit_image(image_url=...)`, тот пушит в `deps.user_message_parts` и `generate_image` форвардит как image reference.

Остаточный хвост: полагаемся на то, что модель сама скопирует URL из текста истории в аргумент тула. Если захочет надёжности — тул по `chat_id`, но реестр `generated.json` выпилен (2026-08-01), хранилище URL пришлось бы заводить заново.

**Файлы:** `kibernikto/ai/agent/core/image.py`, `kibernikto/ai/agent/harness/image_agent/image_expert.py`, `kibernikto/ai/agent/core/kibernikto_agent.py` (_annotate_generation)

### 7. Демоны (daemons) — опционально

`_summon_daemons` / `moral_infiltrate_response` из старого Kiberkalki. Модификация ответа после генерации. Можно отложить или пропустить.

### 8. Уборка

- ~~`storage/file/models.py`~~ — удалён, `ConversationInfo` в `storage/models.py` ✅
- ~~`ai/agent/core/history.py`~~ — удалён, импорты на `storage/base` + `storage/singletons` ✅
- ~~PEP 562 `__getattr__`~~ — удалён из file/chat_data.py и file/media.py ✅
- `storage/file/__init__.py` и `storage/__init__.py` — пустые, вычистить (или оставить как есть — безвредны)
- `TG_FILES_LOCATION` — уже вычищен из кода (проверено grep по репо); осталось убрать из старых env-файлов, если встречается
- `post()` в `utils/image.py` — legacy, удалить, если никому не нужен

### 9. Стриминг ответов — Telegram sendMessageDraft

Сейчас бот шлёт ответ целиком после генерации (`TelegramAgent.reply_to` → `reply()`). Нужно прикрутить Telegram `sendMessageDraft`: слать черновик сообщения сразу и обновлять его по мере генерации (edit-подход для стриминга токенов).

**Файлы:** `kibernikto/telegram/utils/conversation.py`, `kibernikto/ai/agent/telegram_agent.py`

### 10. Инфа о самом себе боту из TG — ✅ сделано (2026-08-08)

Реализовано как аналог chat-context enrichment: `telegram_app.py::_on_startup` после `get_me()` дергает `getMyShortDescription`/`getMyDescription`, строит строку через `telegram/identity.format_bot_identity(username, first_name, short_description, description, name)` → глобал `_bot_identity` (`set_bot_identity/get_bot_identity` в `telegram/identity.py`). Строка в формате `[Your Telegram bot parameters] username: @xxx | display_name: Y | short_description: ... | description: ...` — без `You are`, чтобы не конфликтовать с `WHO_AM_I`/personality. `TelegramAgent` регистрирует второй `self.instructions(self._bot_identity_prompt)` рядом с `_user_context_prompt` — инжектится каждый ран как system-prompt, переживает truncation истории. Без TG — пустая строка, падения нет.

`TelegramAgent` разложен из монолитного `ai/agent/telegram_agent.py` в пакет `ai/agent/telegram/` (как у про — не свалка утилит в одном файле): `telegram_agent.py` (класс + синглтон), `deps.py` (`TelegramDeps`), `identity.py` (bot identity), `chat_context.py` (`format_chat_context`/`refresh_chat_context`, TTL 600s), `group_message.py` (`annotate_group_message`). Старый файл удалён. `chat_context` нормализован к `key: value | key: value`: приват `chat_type: private | full_name: X | username: @y | bio: ...`, группа `chat_type: group | title: ... | ...` (CHANNEL не поддерживается). Дублирующий `user:`-префикс в `build_deps` для привата не нужен — `getChat` уже даёт `full_name`/`username`/`bio`.

**Файлы:** `kibernikto/ai/agent/telegram/telegram_agent.py`, `kibernikto/ai/agent/telegram/identity.py`, `kibernikto/ai/agent/telegram/chat_context.py`, `kibernikto/ai/agent/telegram/group_message.py`, `kibernikto/ai/agent/telegram/deps.py`, `kibernikto/telegram/agent/telegram_app.py` (`_on_startup`), `kibernikto/ai/agent/__init__.py`, `kibernikto/ai/agent/extended/kibernikto_extended.py`, `kibernikto/cmd/__start.py`, `kibernikto/telegram/handlers/conversation.py`

## Предлагаемый порядок

1. ~~Инфа о самом себе боту из TG (см. п.10)~~ — ✅
2. Документы: PDF/txt → media/ → агенты
3. smart_reply — буферизация сообщений
4. prepare_request в ReportExpert
5. KnowledgeExpert — новый RAG
6. Scheduler daemon
7. ~~image-to-image по своим прошлым генерациям~~ (закрыто, см. п.6)
8. Демоны (опционально, отложено)
9. Стриминг ответов — Telegram sendMessageDraft
