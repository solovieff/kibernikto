from pydantic_ai import Agent, ModelSettings

from ai.agent.utils import infer_kibernikto_model
from kibernikto.ai.agent.config import AGENT_KIBERNIKTO_SETTINGS

model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)

model_settings: ModelSettings = ModelSettings(max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
                                              temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
                                              parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS)

agent = Agent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)
