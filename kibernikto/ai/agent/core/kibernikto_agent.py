from pydantic_ai import Agent, ModelSettings, AgentRunResult
from pydantic_ai.messages import BinaryImage, FilePart
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.history import history_storage
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)


model_settings: ModelSettings = ModelSettings(max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
                                              temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
                                              parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS)


class KiberniktoAgent(Agent):
    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        if chat_id is not None and 'message_history' not in kwargs:
            kwargs['message_history'] = history_storage.get_conversation(chat_id)

        run_result: AgentRunResult = await super().run(*args, **kwargs)

        self._materialize_attachments(run_result, kwargs.get('deps'))

        if chat_id is not None:
            history_storage.add_messages(chat_id=chat_id, messages=run_result.new_messages())

        return run_result

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

