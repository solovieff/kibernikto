"""Local (non-MCP) tools the shop agent owns."""

from pydantic_ai import Agent, RunContext

from kibernikto.ai.agent.telegram.deps import TelegramDeps

from .memory import forget_shop_memory


def attach_shop_tools(agent: Agent[TelegramDeps]) -> Agent[TelegramDeps]:
    """Give the agent a way to drop the cart once the order is done."""

    @agent.tool
    async def forget_shop_cart(ctx: RunContext[TelegramDeps]) -> str:
        """Забыть последнюю корзину и найденные товары этого чата.

        Вызывай, когда человек говорит, что заказ оформлен или оплачен, либо просит забыть корзину.
        """
        await forget_shop_memory(ctx.deps)
        return 'Корзина и найденные товары забыты.'

    return agent
