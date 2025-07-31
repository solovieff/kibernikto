import logging
import uuid

from openai import AsyncOpenAI
from openai.types.chat.chat_completion import Choice

from kibernikto.interactors import OpenAIExecutor, OpenAiExecutorConfig, OpenAIRoles
from kibernikto.utils.ai_tools import run_tool_calls
from ._prompt import AGENTS_PROMPT


class KiberniktoAgent(OpenAIExecutor):
    def __init__(self, config: OpenAiExecutorConfig,
                 unique_id: str,
                 label: str,
                 description: str = "",
                 agents: list = (),
                 client: AsyncOpenAI = None,
                 automatic_delegate=True):
        """

        :param config: core kibernikto executor config for this agent
        :param unique_id: executor unique id
        :param description: to be added to parent executor system prompt
        :param agents: the list of agents to delegate tasks to
        :param label: the type of the agent (i.e. weather_agent)
        :param client: ready openai client to share
        :param automatic_delegate: if True, will add default delegate_task tool to config tools
        :param opinion_irrelevant: if True, will return it's tools calls without any processing
        """
        self.agents = agents
        self.description = description
        self.label = label
        self.automatic_delegate = automatic_delegate
        if agents and self.automatic_delegate:
            from .tools import delegate_box
            config.tools.append(delegate_box)
        super().__init__(config=config, unique_id=unique_id, client=client)

    async def query(self, message, effort_level: int, call_session_id: str = None, **kwargs):
        logging.debug(f"running {self.label} agent with message: {message} [{call_session_id}]")
        if not call_session_id:
            call_session_id = self._generate_session_id()
        return await self.request_llm(message=message, call_session_id=call_session_id, **kwargs)

    def get_cur_system_message(self):
        """
        gets called inside each request_llm to update system prompt if needed
        :return: system prompt dict to be used in OpenAI request as {role: 'system', content: 'our content'}.
        """
        wai = self.full_config.who_am_i.format(self.full_config.name)

        # adding agents descriptions
        if self.agents:
            agents_prompt = get_agents_prompt(self.agents)
            wai += f"\n\n{agents_prompt}"
        return dict(role=OpenAIRoles.system.value, content=f"{wai}")

    def get_task_delegate(self, agent_label: str):
        for agent in self.agents:
            if agent.label == agent_label:
                return agent
        raise RuntimeError(f"Agent with label {agent_label} not found")

    def _generate_session_id(self):
        return f"{self.full_config.name}_{self.unique_id}_{uuid.uuid4().hex[:8]}"


class IrrelevantKiberniktoAgent(KiberniktoAgent):
    """
    Does not postprocess tool calls results and returns them as is.
    """

    async def process_tool_calls(self, choice: Choice, original_request_text: str, save_to_history=True, iteration=0,
                                 call_session_id: str = None):
        tool_call_messages = await run_tool_calls(choice=choice, available_tools=self.tools,
                                                  unique_id=self.unique_id, call_session_id=call_session_id)
        content = tool_call_messages[1]['content']

        return content


def get_agents_prompt(agents: list[KiberniktoAgent]):
    prompt = AGENTS_PROMPT
    for agent in agents:
        prompt += f"\n\nagent_label: {agent.label}, {agent.description}"
    return prompt
