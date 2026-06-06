from pydantic_ai import Agent, ModelSettings, AgentRunResult
from pydantic_ai.models import Model

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

        if chat_id is not None:
            history_storage.add_messages(chat_id=chat_id, messages=run_result.new_messages())

        return run_result


agent = KiberniktoAgent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)
