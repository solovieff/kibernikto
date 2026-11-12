"""VkusVill shopping agent without Telegram: python examples/vkusvill_agent.py"""

import asyncio

from kibernikto.ai.agent.vkusvill import build_vkusvill_agent
from kibernikto.storage.base import MemoryHistoryStorage


async def main() -> None:
    agent = build_vkusvill_agent(history_storage=MemoryHistoryStorage())
    while True:
        prompt = input('Ты: ').strip()
        if prompt in {'выход', 'exit', 'quit'}:
            return
        result = await agent.run(prompt, conversation_id='vkusvill-demo')
        print(f'ВкусВилл: {result.output}')


if __name__ == '__main__':
    asyncio.run(main())
