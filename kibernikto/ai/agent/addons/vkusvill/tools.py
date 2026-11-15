"""Local (non-MCP) tools the shop agent owns."""

from pydantic_ai import Agent, RunContext

from kibernikto.ai.agent.telegram.deps import TelegramDeps

from .memory import forget_shop_memory


def attach_shop_tools(agent: Agent[TelegramDeps]) -> Agent[TelegramDeps]:
    """Give the agent a way to drop the cart once the order is done."""

    @agent.tool
    async def forget_shop_cart(ctx: RunContext[TelegramDeps]) -> str:
        """Forget the last cart and the products found in this chat.

        Call when the person says the order is placed or paid, or asks to forget the cart.
        """
        await forget_shop_memory(ctx.deps)
        return 'The cart and found products are forgotten.'

    return agent
