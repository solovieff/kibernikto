# Feeling sorry — что в media-рефакторинге (2026-07-31) можно было сделать лучше

> Заметки для других агентов, которые будут трогать media/storage-слой. Это не оправдания, а известные хвосты.

## Что было сделано

`MediaFileStore` (`storage/file/media.py`), `_sanitize`/`_window` теперь в `storage/base.py` (шарится всеми бэкендами; режет `ModelRequest.instructions` + `FilePart` + `ThinkingPart`), `HistoryStorage(Protocol)` + `MemoryHistoryStorage` в `storage/base.py`, `FileStoreHistoryStorage` — standalone (не наследует память), `ImageHosting` + `ImgbbImageHosting` (`utils/image_hosting.py`), публикация генераций на imgbb + URL в копии финального ответа для истории (`_persist_generated_images` + `_annotate_generation` в `kibernikto_agent.py`).

## Известные хвосты

### 1. Снятие `signature` с ThinkingPart — НЕ универсально
Убрали `ThinkingPart.signature` при сохранении. Для Anthropic (и некоторых других провайдеров) signature **обязательна** при отправке thinking обратно в последующих запросах — без неё продолжение диалога может падать или терять reasoning. Текущий дефолтный модельный стек (glm через openrouter) это переживает, но:
- если придёт Anthropic-модель — `signature` нужно сохранять хотя бы для последнего ответа;
- правильнее: снимать только если `provider_name` не требует signature, или держать сигнатуру последнего `ModelResponse`.

> Частично закрыт в коммите `29218b7`: добавлен `AGENT_KIBERNIKTO_KEEP_THINKING_IN_HISTORY` (default false). При true текст thinking хранится, но `signature` снимается **всегда** — хвост для Anthropic остаётся.

### 2. `_sanitize` — O(n) на каждый ход и потеря семантики
- Санитайзер гоняется по **всей** истории при каждом `add_messages`. С 2026-08-08 чистит и `instructions`, и `FilePart`, и `ThinkingPart`; пока 60 сообщений — ок; на тысячах начнёт кусаться (лечится инкрементальной чисткой только `new_messages` до extend).
- Старые `FilePart` из истории выкинуты **полностью** — любой будущий «replay истории» или тул, который хотел показать «что бот сгенерил», их не увидит. Сознательная потеря, но про неё надо помнить. `instructions` тоже сознательно не хранятся — pydantic-ai ререзолвит их каждый ход (`_get_instruction_parts` предпочитает `model_request_parameters.instruction_parts`), suspend-resume — единственный потребитель исторических `instructions` — ботом не достигается.

### 3. Честность диалога держится на imgbb
Модель «видит» свои генерации только через URL-аннотацию в истории (реестр `generated.json` выпилен 2026-08-01 — был мёртвым). Если imgbb лежит в момент генерации — URL не запомнится, и модель больше никогда не увидит эту картинку (локальная копия в `media/` для модели бесполезна — провайдер не ходит на локальный диск). Fallback на локальный сервер/туннель не сделан.

### 4. Генерации в истории — TextPart с URL в ответе модели
Эволюция: (1) инжекция последнего URL в каждый user-промпт — хронологически врала; (2) синтетический user-маркер с ImageUrl — фейковое user-сообщение; (3) финал: в копию финального ответа для истории дописывается `TextPart("[Bot generated an image]: <url>")` — модель видит ссылку в своём собственном ответе и (на стеке glm/openrouter — проверено юзером) фетчит её. Остаточные хвосты:
- фетч URL из текста — поведение провайдера, не гарантировано на других моделях (OpenAI/Anthropic по умолчанию не тянут URL из текста);
- выпадает из окна истории (6 сообщений) после пары реплик — нормально, как и любой контекст;
- тул `generate_image` референсы из `deps.user_message_parts` (текущее сообщение) всё ещё не увидит свои старые генерации — «измени вторую картинку» не разрулит.

### 5. Синхронный IO в async-коде — ✅ закрыто (2026-08-08)
Все storage-операции async: `MediaFileStore` (save/read через `asyncio.to_thread`), `ChatDataStorage` (load/save), `FileStoreHistoryStorage` (_load/_save), `SqlHistoryStorage`/`SqlChatDataStorage` (нативный async через SQLAlchemy), `S3MediaStore` (нативный async через aioboto3). Протоколы `HistoryStorage`, `MediaStore`, `ChatDataStore` — все async.

### 6. Именование файлов непоследовательно
- Фото пользователя: `file_unique_id` (дедуп по Telegram) ✅
- Генерации: `uuid` на каждый вызов — одинаковые картинки будут копиться в `media/`.
Стоит и для генераций дедуплицировать (хэш байтов) и добавить политику очистки (TTL по дате, лимит на чат).

### 7. `generated.json` — без блокировок — ✅ закрыто
Реестр выпилен (2026-08-01) — файла больше нет, гонка неактуальна.

### 8. Совместимый шим врут
`utils/image.py::publish_image_file` теперь игнорирует параметр `expiration` — провайдер сам читает env. Внешний код, звавший её с `expiration=...`, тихо получит другое поведение. Найти и удалить legacy (`post`, `publish_image_file`) при случае.

### 9. `_process_photo` — три копии байтов
Telegram → память → диск (`media/`) + imgbb. Плюс берётся **самый большой** размер фото (`photo[-1]`). Для тяжёлых фото и медленных каналов стоит ресайзить копию для агента, а не хранить оригинал целиком.

### 10. Тестов нет — отложено
`tests/` пустой (только `__init__.py`). Напрашиваются юнит-тесты для `storage/` (serialize round-trip, factory per-name, file backend CRUD, protocol compliance) и `_sanitize`/`_annotate_generation`. Отложено — venv сломан (griffelib vs griffe), pytest не установлен.

## Что уже поправлено по ходу
- Убран захардкоженный `IMAGE_STORAGE_API_KEY` из кода → ключ вернули в локальный `env/kibernikto.env` (gitignored). Если окружение собирается с нуля — без ключа imgbb молча падает (`publish` вернёт `None`).

## Обновление 2026-08-01 — коммит `5db8512`

- **Доставка бинарей из сабагентов**: `_materialize_attachments` больше НЕ чистит `deps.attachments`. Раньше сабагент (report_expert/image_expert) забирал бинарь из общих deps в свой response и чистил буфер, а родителю возвращался только `str(output)` — файл/картинка терялись. Теперь буфер живёт до верхнего запуска. Хвост: если кто-то когда-то переиспользует те же deps для второго доставляемого запуска — возможна двойная отправка (сейчас таких путей нет).
- **Модель не знает URL приложенного фото**: провайдер (OpenRouter→Google) называет аттачмент `input_file_0.png`, модель передаёт это имя в `image_url`, провайдер отвечает 400. Теперь: `_is_valid_image_url` режет мусор, `_extract_input_images` берёт реальные URL из deps, `edit_image`/`describe_image` аппендят только валидные URL.
- **Jina deepsearch**: работает через стрим (`stream: true`, сбор `type=text` чанков). Не-стрим роняет соединение на ~60s — серверный идл-таймаут, не наш баг.

## Обновление 2026-08-08 (позже) — per-message SQL history + validation + answer_on_full_history fix

- **Per-message SQL history** — `chat_messages(id, chat_id, name, seq, kind, payload)` вместо `chat_history` (JSON-блоб на чат). Одно `ModelMessage` = одна строка. `SqlHistoryStorage` переписан: нет in-memory кэша, нет whole-chat reads. `get_conversation` читает хвост (`HISTORY_SIZE * HISTORY_WINDOW_SLACK`) + `_window` в Python для request-boundary. `get_full_conversation` — без обрезки. `add_messages` — INSERT новых строк, `seq` = MAX(seq)+1 по `(chat_id, name)`.
- **`HistoryStorage.get_full_conversation`** — новый метод протокола (все три бэкенда). `answer_on_full_history` в conversation_expert теперь зовёт его вместо обрезанного `get_conversation`.
- **`answer_on_full_history` форматирование** — починено: раньше делал `getattr(m, 'content', '')` на `ModelMessage` (атрибута нет, были пустые строки). Теперь правильно обходит `parts` (TextPart/UserPromptPart), тулколлы пропускаются.
- **`StorageSettings` validation** — cross-field при импорте: pg без DSN → ValueError, s3 без ключей → ValueError. `validate_storage()` — connectivity check (pg SELECT 1, sqlite SELECT 1, s3 head_bucket) из `start()` до polling.
- **`HISTORY_WINDOW_SLACK`** — `APP_STORAGE_HISTORY_WINDOW_SLACK`, default 3. Множитель для SQL history tail fetch.
- **Удалён legacy `chat_history`** — `create_all` больше не создаёт, `DROP TABLE IF EXISTS` убран (по запросу юзера).

## Обновление 2026-08-08 — S3 + PostgreSQL + SQLAlchemy storage backends

- **`StorageSettings`** — `kibernikto/storage/config.py`, `env_prefix='APP_STORAGE_'`: `DATA_BACKEND=file|pg|sqlite`, `MEDIA_BACKEND=file|s3`.
- **SQL-слой** — `storage/sql/`: `SqlHistoryStorage` + `SqlChatDataStorage` через SQLAlchemy 2.0 async (PG через `asyncpg`, SQLite через `aiosqlite`). `ensure_db_initialized()` с `asyncio.Lock` — `create_all` один раз за процесс. Storage-классы НЕ вызывают `ensure_db_initialized()` — engine должен быть инициализирован до первого использования (в `_on_startup` для Telegram, явно перед `agent.run()` для standalone). `get_session()` кидает `RuntimeError` если engine не готов.
- **S3-медиа** — `storage/s3/media.py`: `S3MediaStore` через `aioboto3`, async `save`/`read`/`tmp_path`, retry config (max_attempts=3), `aclose()` для shutdown.
- **Фабрика** — `storage/factory.py`: `get_history_storage(name)` per-name dict, `get_chat_data_storage()`, `get_media_store()`, `shutdown_storage()`.
- **Синглтоны** — `storage/singletons.py`: `_LazySingleton` proxy (замена PEP 562), isinstance работает через `__class__`.
- **Модели** — `storage/models.py`: `ConversationInfo` (бывший `file/models.py`, шим удалён).
- **Протоколы** — `storage/base.py`: `HistoryStorage`, `MediaStore` (async-only), `ChatDataStore`. `serialize_messages`/`deserialize_messages` — единый TypeAdapter.
- **media_ref унифицирован**: `{chat_id}/{file}` для file и s3.
- **Депсы**: `sqlalchemy[asyncio]`, `asyncpg`, `aiosqlite`, `aioboto3` в `pyproject.toml`.
- **Shutdown**: `telegram_app.py::_on_shutdown` → `shutdown_storage()` → dispose engine + close S3.
- **Удалены**: `storage/file/models.py`, `ai/agent/core/history.py`, PEP 562 `__getattr__` из file backends.

## Обновление 2026-08-01 (позже) — markdown→HTML отправка

- `conversation.py` теперь шлёт через `markdown_to_html` + `ParseMode.HTML` (флаг `TG_MARKDOWN_TO_HTML`, default true). Legacy `Markdown` остался за флагом. Слепое экранирование `_` в `prepare_for_MARKDOWN` убрано — оно удваивало слеши у `@swarm\_host\_bot`.
- Новый конвертер живёт в `utils/text.py`; покрывает **bold/italic/code/fenced/links/headings/blockquotes**, всё остальное экранируется по `<>&` — юзернеймы с подчёркиванием безопасны.
- Если флаг выключен — поведение прежнее (legacy Markdown + fallback plain).

> Стриминг (`sendMessageDraft`, п.9 remaining_work_plan) всё ещё не делали.
