from openai import AsyncClient

from kibernikto.agent.demo.tools import session_data_tool
from kibernikto.agent.kibernikto_agent import KiberniktoAgent, IrrelevantKiberniktoAgent
from kibernikto.agent.kibernikto_context import kibernikto_context
from kibernikto.interactors import OpenAiExecutorConfig

# llm key, url comes from env
session_agent_config = OpenAiExecutorConfig(
    id=0,
    name="session-agent",
    model="google/gemini-2.5-flash-lite",
    who_am_i="You are {0}, you help demonstrating that you have access to session data in your tools.",
)


class SessionAgent(IrrelevantKiberniktoAgent):
    def __init__(self, unique_id: str, config: OpenAiExecutorConfig = session_agent_config, client: AsyncClient = None):
        label = config.name
        description = "Call session agent to show call session tracking capabilities",
        config.tools = [session_data_tool]
        config.tools_with_history = False
        super().__init__(unique_id=unique_id, config=config, client=client, description=description, label=label)

    async def query(self, message, effort_level: int, call_session_id: str = None, **kwargs):
        # doing any custom logic here: changing session data, running other llms etc
        if call_session_id:
            kibernikto_context.add_call_session_data(session_key=call_session_id, label=self.label,
                                                     data={"query": message, "unique_id": self.unique_id})
        return await super().query(message, effort_level, call_session_id, **kwargs)


__READY_EXECUTOR = None


def get_global_instance() -> 'SessionAgent':
    """
    :return: static global agent instance
    """
    global __READY_EXECUTOR
    if not __READY_EXECUTOR:
        __READY_EXECUTOR = SessionAgent(unique_id=f"{session_agent_config.name}-global")
    return __READY_EXECUTOR
