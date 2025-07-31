import asyncio

from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.agent.demo import chat_loop
from kibernikto.agent.demo.tools import weather_tool

if __name__ == "__main__":
    # This basic agent demonstrates the use of a single tool (weather_tool) 
    # to interact with a language model for handling weather-related queries.
    # llm key, url goes from env here
    config = OpenAiExecutorConfig(
        id=0,
        name="demo-agent",
        model="anthropic/claude-sonnet-4",
        who_am_i="You are {0}, a test agent.",
        tools=[weather_tool]
    )
    if not config.key:
        raise ValueError("OpenAI API key is required.")

    # Create an instance of KiberniktoAgent
    agent = KiberniktoAgent(config=config,
                            label=config.name,
                            unique_id=f"{config.name}-1")

    # Example of invoking a method for demonstration
    print("KiberniktoAgent initialized. Label:", agent.label)

    asyncio.run(chat_loop.main_loop(agent))
