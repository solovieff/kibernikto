import dataclasses
import logging
import uuid
from collections.abc import Sequence

from pydantic_ai import Agent, ModelSettings, AgentRunResult, RunContext, UserError
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.messages import BinaryImage, FilePart, ModelMessage, ModelResponse, TextPart, UserContent
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.media_check import check_history_images, fetch_bytes, head_alive
from kibernikto.ai.agent.core.persona import (
    PERSONA_INSTRUCTION, PersonaFirst, PersonaSource, StaticPersona, compile_persona, persona_source_text,
)
from kibernikto.ai.agent.utils import infer_kibernikto_model, with_attribution
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.factory import get_media_store
from kibernikto.storage.singletons import history_storage, media_store
from kibernikto.utils.image_hosting import image_hosting
from kibernikto.utils.time_utils import DEFAULT_TIMEZONE, get_user_date

logger = logging.getLogger(__name__)


model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)


model_settings: ModelSettings = ModelSettings(max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
                                              temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
                                              parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS)


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


class KiberniktoAgent(Agent):
    # Network probes for history image links; overridable per instance (tests stay offline).
    image_head = staticmethod(head_alive)
    image_fetch = staticmethod(fetch_bytes)

    def __init__(
            self,
            *,
            history_storage: HistoryStorage | None = history_storage,
            persona_source: PersonaSource | None = None,
            persona: bool = True,
            reaction: str | None = None,
            **kwargs,
    ):
        """``persona=False`` for delegated experts: they serve the parent agent, not the user.

        ``reaction`` is the emoji a transport shows on the user's message when this agent starts a run.
        """
        self._active_runs: dict[str, RunContext[KiberniktoDeps]] = {}
        caps = [*(kwargs.get("capabilities") or ()), _ActiveConversationTracker(self._active_runs)]
        if persona:
            caps.append(PersonaFirst())
        kwargs["capabilities"] = caps
        if not callable(settings := kwargs.get("model_settings")):  # Callables are dynamic: left to their owner.
            kwargs["model_settings"] = with_attribution(settings, kwargs.get("name"))
        super().__init__(**kwargs)
        self._history_storage = history_storage
        self._reaction = reaction
        if persona:
            # Persona: {filestore}/{name}-instructions.txt or WHO_AM_I, a Handlebars template compiled once.
            text = compile_persona(persona_source_text(self.name), persona_source or self.default_persona_source())
            self.instructions(name=PERSONA_INSTRUCTION)(text)
        self.instructions(self._current_date_prompt)

    @property
    def history_storage(self) -> HistoryStorage | None:
        """Per-conversation history backend this agent reads and writes; ``None`` when history is off."""
        return self._history_storage

    @property
    def reaction(self) -> str | None:
        """Emoji set on the user's message when this agent starts a run; ``None`` = no reaction."""
        return self._reaction

    @staticmethod
    def default_persona_source() -> PersonaSource:
        """Values for ``{{name}}``/``{{traits}}`` when none is injected; transports override."""
        return StaticPersona()

    async def run(
            self,
            user_prompt: str | Sequence[UserContent] | None = None,
            *,
            conversation_id: str | int | None = None,
            **kwargs,
    ) -> AgentRunResult | None:
        """Run the agent; ``conversation_id`` opts into stored history, capability scoping and mid-run steering.

        When a run for ``conversation_id`` is already in flight on this agent, ``user_prompt`` is enqueued
        into that active run (``priority='asap'``) and ``None`` is returned so the active run answers once
        with the combined context. Anonymous runs (``conversation_id=None``) pass ``conversation_id=''`` to
        pydantic-ai so capabilities see an empty id and skip per-conversation storage/billing.
        """
        cid = str(conversation_id) if conversation_id is not None and conversation_id != "" else None
        if cid is not None and (active_ctx := self._active_runs.get(cid)) is not None and user_prompt is not None:
            if self._steer_active_run(active_ctx, user_prompt, kwargs.get("deps")):
                return None

        if self._history_storage is not None and cid is not None and "message_history" not in kwargs:
            kwargs["message_history"] = await self._history_storage.get_conversation(cid)
            await self._repair_history_images(kwargs, cid)

        run_result: AgentRunResult = await super().run(
            user_prompt,
            conversation_id=cid if cid is not None else "",
            **kwargs,
        )

        self._materialize_attachments(run_result, kwargs.get("deps"))

        messages = run_result.new_messages()
        if cid is not None:
            published = await self._persist_generated_images(run_result, cid)
            if published:
                messages = self._annotate_generation(messages, published)

        if self._history_storage is not None and cid is not None:
            await self._history_storage.add_messages(conversation_id=cid, messages=messages)

        return run_result

    @staticmethod
    def _steer_active_run(
            active_ctx: RunContext[KiberniktoDeps],
            user_prompt: str | Sequence[UserContent],
            new_deps: object,
    ) -> bool:
        """Inject ``user_prompt`` into ``active_ctx``; return False if the run already finished."""
        items: Sequence[UserContent] = [user_prompt] if isinstance(user_prompt, str) else list(user_prompt)
        try:
            enqueued = active_ctx.enqueue(*items, priority="asap")
        except UserError:
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

    @staticmethod
    def _current_date_prompt(ctx: RunContext[KiberniktoDeps]) -> str:
        """Today's date each run in ``deps.timezone``; plain or missing deps get the default zone."""
        timezone = ctx.deps.timezone if isinstance(ctx.deps, KiberniktoDeps) else None
        return f"Current date: {get_user_date(timezone or DEFAULT_TIMEZONE)}."

    async def _repair_history_images(self, kwargs: dict, conversation_id: str) -> None:
        """Replace dead history image links with text and persist the fixed history once."""
        fixed, changed = await check_history_images(
            kwargs["message_history"], conversation_id=conversation_id, exists=_store_exists, save=_store_save,
            head=self.image_head, fetch=self.image_fetch,
        )
        if not changed:
            return
        kwargs["message_history"] = fixed
        await self._history_storage.replace_messages(conversation_id, fixed)

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
    async def _persist_generated_images(run_result: AgentRunResult, conversation_id: str) -> list[str]:
        """Keep generated binaries out of history: durable copy + public URL.

        The ``FilePart`` stays in ``run_result.response`` for delivery; here we
        archive the bytes locally and publish a public URL so the model can
        re-see the image on later turns (see :meth:`_annotate_generation`).
        Returns the published URLs.
        """
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


async def _store_exists(store_name: str, media_ref: str) -> bool:
    """Check a media ref in the named media store (``default`` or ``telegram``)."""
    return await get_media_store(store_name).exists(media_ref)


async def _store_save(store_name: str, media_ref: str, data: bytes) -> None:
    """Save downloaded bytes under the exact ref recorded in history."""
    conversation_id, name = media_ref.split("/", 1)
    ext = name.rsplit(".", 1)[-1] if "." in name else "bin"
    await get_media_store(store_name).save(conversation_id, data, ext=ext, name=name)

