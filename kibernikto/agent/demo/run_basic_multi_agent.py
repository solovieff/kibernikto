import asyncio

from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.agent.kibernikto_context import kibernikto_context
from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.agent.demo import chat_loop
from kibernikto.agent.demo.tools import weather_tool, session_data_tool
from kibernikto.utils.environment import configure_logger

# llm key, url goes from env here
weather_config = OpenAiExecutorConfig(
    id=0,
    tools=[weather_tool],  # <-- weather_agent has a tool
    name="weather-agent",
    model="google/gemini-2.5-flash-lite",
    who_am_i="You are {0}, you help getting weather information.",
)

weather_agent = KiberniktoAgent(config=weather_config,
                                label=weather_config.name,
                                unique_id=f"{weather_config.name}-1",
                                description="Call Weather agent to get weather information.")
kibernikto_context.register_agent(weather_agent)

# llm key, url goes from env here
session_agent_config = OpenAiExecutorConfig(
    id=0,
    tools=[session_data_tool],  # <-- weather_agent has a tool
    name="session-agent",
    model="google/gemini-2.5-flash-lite",
    who_am_i="You are {0}, you help demonstrating that you have access to session data in your tools.",
)

session_agent = KiberniktoAgent(config=session_agent_config,
                                label=session_agent_config.name,
                                description="Call session agent to show call session tracking capabilities",
                                unique_id=f"{session_agent_config.name}-1")
kibernikto_context.register_agent(session_agent)

# llm key, url goes from env here
root_config = OpenAiExecutorConfig(
    id=1,
    name="root-agent",
    model="anthropic/claude-sonnet-4",
    who_am_i="You are {0}, a agent to show kibernikto multiple agents use.")

root_agent = KiberniktoAgent(config=root_config,
                             label=root_config.name,
                             unique_id="root-agent-1",
                             description="Agent to show kibernikto multiple agents use.",
                             agents=[weather_agent, session_agent])
kibernikto_context.register_agent(root_agent)

# Example of invoking a method for demonstration
print("KiberniktoAgent initialized. Label:", root_agent.label)
configure_logger()
asyncio.run(chat_loop.main_loop(root_agent))
