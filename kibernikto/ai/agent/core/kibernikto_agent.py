import logging
import uuid
from typing import Any, Optional

from pydantic_ai import Agent, ModelSettings, AgentRunResult
from pydantic_ai.messages import BinaryImage, FilePart, ImageUrl
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.history import MemoryHistoryStorage, history_storage
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.storage.file.media import media_store
from kibernikto.utils.image_hosting import image_hosting

logger = logging.getLogger(__name__)

model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)


model_settings: ModelSettings = ModelSettings(max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
                                              temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
                                              parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS)


class KiberniktoAgent(Agent):
    def __init__(self, *, history_storage: Optional[MemoryHistoryStorage] = history_storage, **kwargs):
        super().__init__(**kwargs)
        self._history_storage = history_storage

    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        if self._history_storage is not None and chat_id is not None and 'message_history' not in kwargs:
            kwargs['message_history'] = self._history_storage.get_conversation(chat_id)
            # Honest dialogue: let the model re-see its last generation on later turns.
            if args:
                args = (self._with_generated_context(chat_id, args[0]), *args[1:])

        run_result: AgentRunResult = await super().run(*args, **kwargs)

        self._materialize_attachments(run_result, kwargs.get('deps'))

        if chat_id is not None:
            await self._persist_generated_images(run_result, chat_id)

        if self._history_storage is not None and chat_id is not None:
            self._history_storage.add_messages(chat_id=chat_id, messages=run_result.new_messages())

        return run_result

    @staticmethod
    def _with_generated_context(chat_id: int, user_content: Any) -> Any:
        """Append the most recent generated image URL to the user content.

        Generated images are delivered to the user but stripped from the
        persisted history (they'd bloat it as base64), so on the next turn we
        re-inject the latest one as an ``ImageUrl`` — the provider fetches it
        itself, keeping the dialogue honest without storing bytes.
        """
        urls = media_store.last_generated(chat_id)
        if not urls:
            return user_content
        images: list[ImageUrl] = [ImageUrl(url=urls[-1])]
        if isinstance(user_content, str):
            return [user_content, *images]
        if isinstance(user_content, list):
            return [*user_content, *images]
        return user_content

    @staticmethod
    async def _persist_generated_images(run_result: AgentRunResult, chat_id: int) -> None:
        """Keep generated binaries out of history: durable copy + public URL.

        The ``FilePart`` stays in ``run_result.response`` for delivery; here we
        archive the bytes locally and publish a public URL so the model can
        re-see the image on later turns (see :meth:`_with_generated_context`).
        """
        for image in run_result.response.images:
            ext = (image.media_type or "image/png").split("/")[-1].split(";")[0] or "png"
            try:
                media_store.save(chat_id, image.data, ext)
            except Exception as exc:
                logger.warning("Failed to save generated image for chat %s: %s", chat_id, exc)
            try:
                url = await image_hosting.publish(image.data, f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}")
                if url:
                    media_store.remember_generated(chat_id, url)
            except Exception as exc:
                logger.warning("Failed to publish generated image for chat %s: %s", chat_id, exc)

    @staticmethod
    def _materialize_attachments(run_result: AgentRunResult, deps) -> None:
        """Fold tool-produced binaries into the final response as ``FilePart``s.

        Tools can't return content to the user directly (a tool return only
        flows back to the model), so they stash binaries on ``deps.attachments``.
        We append them to the final ``ModelResponse`` as genuine ``FilePart``s —
        the same public shape a model uses to return files — so they surface via
        ``response.images`` / ``response.files`` and serialize into history as if
        the model had produced them. The buffer is cleared to avoid double-send.
        """
        if not isinstance(deps, KiberniktoDeps) or not deps.attachments:
            return

        response = run_result.response
        for binary in deps.attachments:
            # Narrow BinaryContent → BinaryImage when applicable. pydantic's
            # `AfterValidator` on FilePart.content only fires during
            # `TypeAdapter` / `model_validate`, not on a direct `__init__` call,
            # so we have to do it ourselves; otherwise `response.images` —
            # which filters via `isinstance(_, BinaryImage)` — stays empty and
            # the Telegram reply layer never sees the image.
            content = BinaryImage.narrow_type(binary) if not isinstance(binary, BinaryImage) else binary
            response.parts.append(FilePart(content=content))
        deps.attachments.clear()


agent = KiberniktoAgent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
    deps_type=KiberniktoDeps,
)

