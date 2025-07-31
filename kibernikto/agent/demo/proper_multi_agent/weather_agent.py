from openai import AsyncClient

from kibernikto.agent.demo.tools import weather_tool
from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.agent.kibernikto_context import kibernikto_context
from kibernikto.interactors import OpenAiExecutorConfig

# llm key, url comes from env
weather_config = OpenAiExecutorConfig(
    name="weather-agent",
    model="google/gemini-2.5-flash-lite",
    who_am_i="You are {0}, you help getting weather information.",
)


class WeatherAgent(KiberniktoAgent):
    def __init__(self, unique_id: str, config: OpenAiExecutorConfig = weather_config, client: AsyncClient = None):
        label = config.name
        description = "Call Weather agent to get weather information."
        config.tools = [weather_tool]
        super().__init__(unique_id=unique_id, config=config, client=client, description=description, label=label)

    async def query(self, message, effort_level: int, call_session_id: str = None, **kwargs):
        if call_session_id:
            kibernikto_context.add_call_session_data(session_key=call_session_id, label=self.label,
                                                     data={"query": message, "unique_id": self.unique_id})
        return await super().query(message, effort_level, call_session_id, **kwargs)


__READY_EXECUTOR = None


def get_global_instance() -> 'WeatherAgent':
    """
    :return: static global agent instance
    """
    global __READY_EXECUTOR
    if not __READY_EXECUTOR:
        __READY_EXECUTOR = WeatherAgent(unique_id=f"{weather_config.name}-global")
    return __READY_EXECUTOR
