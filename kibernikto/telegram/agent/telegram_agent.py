from aiogram.types import Message
from pydantic_ai import Agent


class TelegramAgent(Agent):
    """Telegram agent for interacting with Telegram API."""

    async def execute(self, full_msg: Message) -> str:
        """Run the Telegram agent to process the given message."""
        return f"Processed message: {full_msg}"
