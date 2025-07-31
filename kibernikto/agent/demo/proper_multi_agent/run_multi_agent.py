# llm key, url goes from env here
import asyncio

from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.agent.kibernikto_context import kibernikto_context
from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.agent.demo import chat_loop
from kibernikto.agent.demo.proper_multi_agent import weather_agent, session_agent
from kibernikto.utils.environment import configure_logger

root_config = OpenAiExecutorConfig(
    name="root-agent",
    model="anthropic/claude-sonnet-4",
    who_am_i="You are {0}, a agent to show kibernikto multiple agents use.")

weather_agent = weather_agent.get_global_instance()
session_agent = session_agent.get_global_instance()

root_agent = KiberniktoAgent(config=root_config,
                             label=root_config.name,
                             unique_id="root-agent-1",
                             description="Agent to show kibernikto multiple agents use.",
                             agents=[weather_agent, session_agent])

kibernikto_context.register_agent(weather_agent)
kibernikto_context.register_agent(session_agent)
kibernikto_context.register_agent(root_agent)

# Example of invoking a method for demonstration
print("KiberniktoAgent initialized. Label:", root_agent.label)
configure_logger()
asyncio.run(chat_loop.main_loop(root_agent))
