import dataclasses
import logging
import uuid
from typing import Optional

from pydantic_ai import Agent, ModelSettings, AgentRunResult
from pydantic_ai.messages import BinaryImage, FilePart, ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.storage.base import HistoryStorage
from kibernikto.ai.agent.core.history import history_storage
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS, resolve_instructions
from kibernikto.storage.file.media import media_store
from kibernikto.utils.image_hosting import image_hosting

logger = logging.getLogger(__name__)

model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)


model_settings: ModelSettings = ModelSettings(max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
                                              temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
                                              parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS)


class KiberniktoAgent(Agent):
    def __init__(self, *, history_storage: Optional[HistoryStorage] = history_storage, **kwargs):
        super().__init__(**kwargs)
        self._history_storage = history_storage
        # Personality loads from {filestore}/{name}-instructions.txt, else env WHO_AM_I.
        self.instructions(resolve_instructions(self.name))

    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        if self._history_storage is not None and chat_id is not None and 'message_history' not in kwargs:
            kwargs['message_history'] = self._history_storage.get_conversation(chat_id)

        run_result: AgentRunResult = await super().run(*args, **kwargs)

        self._materialize_attachments(run_result, kwargs.get('deps'))

        messages = run_result.new_messages()
        if chat_id is not None:
            published = await self._persist_generated_images(run_result, chat_id)
            # The model sees its generation in its own response: append the
            # public URL as a TextPart to the history copy. The live response
            # stays untouched so the user doesn't see the note; providers that
            # fetch URLs from text will let the model re-see the image.
            if published:
                messages = self._annotate_generation(messages, published)

        if self._history_storage is not None and chat_id is not None:
            self._history_storage.add_messages(chat_id=chat_id, messages=messages)

        return run_result

    @staticmethod
    def _annotate_generation(messages: list[ModelMessage], urls: list[str]) -> list[ModelMessage]:
        """Append a ``TextPart`` with the published URLs to the final response.

        ``ImageUrl`` can only live in request parts in pydantic-ai's schema, so
        the URL is recorded as plain text inside the model's own response —
        semantically correct, and the model can fetch it on later turns.
        """
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

    @staticmethod
    async def _persist_generated_images(run_result: AgentRunResult, chat_id: int) -> list[str]:
        """Keep generated binaries out of history: durable copy + public URL.

        The ``FilePart`` stays in ``run_result.response`` for delivery; here we
        archive the bytes locally and publish a public URL so the model can
        re-see the image on later turns (see :meth:`_generation_marker`).
        Returns the published URLs.
        """
        urls: list[str] = []
        for image in run_result.response.images:
            ext = (image.media_type or "image/png").split("/")[-1].split(";")[0] or "png"
            try:
                media_store.save(chat_id, image.data, ext)
            except Exception as exc:
                logger.warning("Failed to save generated image for chat %s: %s", chat_id, exc)
            try:
                url = await image_hosting.publish(image.data, f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}")
                if url:
                    urls.append(url)
            except Exception as exc:
                logger.warning("Failed to publish generated image for chat %s: %s", chat_id, exc)
        return urls

    @staticmethod
    def _materialize_attachments(run_result: AgentRunResult, deps) -> None:
        """Fold tool-produced binaries into the final response as ``FilePart``s.

        Tools can't return content to the user directly (a tool return only
        flows back to the model), so they stash binaries on ``deps.attachments``.
        We append them to the final ``ModelResponse`` as genuine ``FilePart``s —
        the same public shape a model uses to return files — so they surface via
        ``response.images`` / ``response.files`` and are delivered by the reply
        layer. The buffer is intentionally left intact: sub-agent runs share
        the parent's deps, and only the top-level run's response is delivered,
        so the parent must be able to pick up binaries queued by delegated
        tools. History storage strips ``FilePart``s anyway
        (``FileStoreHistoryStorage._sanitize``), so nothing leaks into the
        model's context.
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


agent = KiberniktoAgent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    deps_type=KiberniktoDeps,
)

