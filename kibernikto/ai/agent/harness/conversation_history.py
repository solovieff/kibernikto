"""Conversation history capability: auto-loads stored history and processes it with ProcessHistory."""

from __future__ import annotations

import dataclasses
import logging
import uuid
from typing import Sequence

from pydantic_ai import RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import AbstractCapability, CombinedCapability, ProcessHistory
from pydantic_ai.capabilities.abstract import WrapRunHandler
from pydantic_ai.messages import BinaryImage, FilePart, ModelMessage, ModelResponse, TextPart, UserContent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.media_check import check_history_images, fetch_bytes, head_alive
from kibernikto.storage.base import HistoryStorage, _sanitize, _window
from kibernikto.storage.factory import get_history_storage, get_media_store
from kibernikto.storage.singletons import history_storage, media_store
from kibernikto.utils.image_hosting import image_hosting

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _ActiveConversationTracker(AbstractCapability[KiberniktoDeps]):
    """Register the live ``RunContext`` per ``conversation_id`` so concurrent calls steer into it."""

    active_runs: dict[str, RunContext[KiberniktoDeps]] = dataclasses.field(default_factory=dict)

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def wrap_run(self, ctx: RunContext[KiberniktoDeps], *, handler: WrapRunHandler) -> AgentRunResult:
        cid = ctx.conversation_id or None
        if cid is not None and self.active_runs.get(cid) is None:
            self.active_runs[cid] = ctx
            try:
                return await handler()
            finally:
                if self.active_runs.get(cid) is ctx:
                    self.active_runs.pop(cid, None)
        return await handler()


async def _store_exists(store_name: str, media_ref: str) -> bool:
    return await get_media_store(store_name).exists(media_ref)


async def _store_save(store_name: str, media_ref: str, data: bytes) -> None:
    conversation_id, name = media_ref.split("/", 1)
    ext = name.rsplit(".", 1)[-1] if "." in name else "bin"
    await get_media_store(store_name).save(conversation_id, data, ext=ext, name=name)


class _StorageIO(AbstractCapability[KiberniktoDeps]):
    def __init__(self, storage: HistoryStorage):
        self.storage = storage

    async def before_run(self, ctx: RunContext[KiberniktoDeps]) -> None:
        cid = ctx.conversation_id or None
        if cid is None or not self.storage:
            return
        # Load persisted conversation messages
        messages = await self.storage.get_conversation(cid)
        if messages:
            fixed, changed = await check_history_images(
                messages, conversation_id=cid, exists=_store_exists, save=_store_save,
                head=head_alive, fetch=fetch_bytes,
            )
            if changed:
                messages = fixed
                await self.storage.replace_messages(cid, fixed)
            # Prepend into run context so the agent starts with loaded history
            ctx.messages[:0] = messages

    async def after_run(self, ctx: RunContext[KiberniktoDeps], *, result: AgentRunResult) -> AgentRunResult:
        self._materialize_attachments(result, ctx.deps)
        cid = ctx.conversation_id or None
        if cid is not None and self.storage:
            messages = result.new_messages()
            published = await self._persist_generated_images(result, cid)
            if published:
                messages = self._annotate_generation(messages, published)
            # Sanitize before saving to database (drop instructions, drop binary parts, drop reasoning)
            cleaned = _sanitize(messages, keep_thinking=AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY)
            await self.storage.add_messages(conversation_id=cid, messages=cleaned)
        return result

    @staticmethod
    def _materialize_attachments(run_result: AgentRunResult, deps: object) -> None:
        if not isinstance(deps, KiberniktoDeps) or not deps.attachments:
            return
        response = run_result.response
        existing_data = {p.content.data for p in response.parts if isinstance(p, FilePart) and hasattr(p.content, 'data')}
        for binary in deps.attachments:
            if binary.data in existing_data:
                continue
            content = BinaryImage.narrow_type(binary) if not isinstance(binary, BinaryImage) else binary
            response.parts.append(FilePart(content=content))
            existing_data.add(binary.data)

    @staticmethod
    async def _persist_generated_images(run_result: AgentRunResult, conversation_id: str) -> list[str]:
        urls: list[str] = []
        for image in run_result.response.images:
            ext = (image.media_type or "image/png").split("/")[-1].split(";")[0] or "png"
            try:
                await media_store.save(conversation_id, image.data, ext)
            except Exception as exc:
                logger.warning("Failed to save generated image for conversation %s: %s", conversation_id, exc)
            try:
                url = await image_hosting.publish(image.data, f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}")
                if url:
                    urls.append(url)
            except Exception as exc:
                logger.warning("Failed to publish generated image for conversation %s: %s", conversation_id, exc)
        return urls

    @staticmethod
    def _annotate_generation(messages: list[ModelMessage], urls: list[str]) -> list[ModelMessage]:
        text = "[Bot generated " + ("an image" if len(urls) == 1 else f"{len(urls)} images") + "]: " + ", ".join(urls)
        last_response = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], ModelResponse)),
            None,
        )
        if last_response is None:
            return messages
        result = list(messages)
        response = result[last_response]
        result[last_response] = dataclasses.replace(response, parts=[*response.parts, TextPart(content=text)])
        return result


class ConversationHistory(CombinedCapability[KiberniktoDeps]):
    """Capability managing conversation persistence, steering, and context-window processing."""

    _materialize_attachments = staticmethod(_StorageIO._materialize_attachments)

    def __init__(
            self,
            storage: HistoryStorage | None = history_storage,
            *,
            history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
            keep_thinking: bool = AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
            active_runs: dict[str, RunContext[KiberniktoDeps]] | None = None,
    ) -> None:
        self.storage = storage
        self.history_size = history_size
        self.keep_thinking = keep_thinking
        self.active_runs = active_runs if active_runs is not None else {}

        def process_messages(ctx: RunContext[KiberniktoDeps], messages: list[ModelMessage]) -> list[ModelMessage]:
            # Keep instructions on the current (latest) request so the model sees system prompts,
            # but window history turns according to history_size.
            if not messages:
                return messages
            if self.history_size and len(messages) > self.history_size:
                return _window(messages, self.history_size)
            return messages

        capabilities: list[AbstractCapability[KiberniktoDeps]] = [
            _ActiveConversationTracker(self.active_runs),
            _StorageIO(storage),
            ProcessHistory(process_messages),
        ]
        super().__init__(capabilities)

    def steer_active_run(
            self,
            conversation_id: str,
            user_prompt: str | Sequence[UserContent],
            new_deps: object,
    ) -> bool:
        """Inject ``user_prompt`` into active run for ``conversation_id``; returns True if steered."""
        active_ctx = self.active_runs.get(conversation_id)
        if active_ctx is None:
            return False
        items: Sequence[UserContent] = [user_prompt] if isinstance(user_prompt, str) else list(user_prompt)
        try:
            enqueued = active_ctx.enqueue(*items, priority="asap")
        except Exception:
            return False
        if enqueued is None:
            return False
        if isinstance(active_deps := active_ctx.deps, KiberniktoDeps):
            if isinstance(new_deps, KiberniktoDeps) and new_deps.user_message_parts:
                active_deps.user_message_parts.extend(new_deps.user_message_parts)
            else:
                active_deps.user_message_parts.extend(items)
            if hasattr(active_deps, "message") and (new_msg := getattr(new_deps, "message", None)) is not None:
                prev_msg = getattr(active_deps, "message", None)
                if prev_msg is not None and prev_msg is not new_msg:
                    active_deps.extra.setdefault("steered_messages", []).append(prev_msg)
                setattr(active_deps, "message", new_msg)
        return True

