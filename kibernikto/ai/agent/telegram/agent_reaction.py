"""AgentReaction — every agent in the run tree marks the user's message with its own ``reaction`` emoji."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ReactionTypeEmoji
from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.capabilities import AbstractCapability, ValidatedToolArgs
from pydantic_ai.messages import ToolCallPart

from kibernikto.ai.agent.core.deps import KiberniktoDeps

from .deps import TelegramDeps

logger = logging.getLogger(__name__)

# deps.extra keys (deps are shared across the delegation tree): emoji on the message, the root agent.
_CURRENT = "reaction"
_ROOT = "reaction_root"


@dataclass
class AgentReaction(AbstractCapability[KiberniktoDeps]):
    """Mark ``deps.message`` with ``ctx.agent.reaction``; the last emoji stays.

    Delegates react at run start. The root agent reacts only on its own tool calls, so plain
    chatter stays clean; ``skip_tools`` (delegation) is left to the delegate's own emoji.
    Bind it on the parent and in ``SubAgents(shared_capabilities=...)`` so delegates react too.
    Cosmetic: Telegram failures are logged and never fail the run.
    """

    timeout: float = 3.0
    skip_tools: frozenset[str] = frozenset({"delegate_task"})

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None  # Runtime-only Telegram side effect.

    async def before_run(self, ctx: RunContext[KiberniktoDeps]) -> None:
        if not isinstance(deps := ctx.deps, TelegramDeps):
            return  # Deps-less runs (tests, scripts) have no message to mark.
        if deps.extra.setdefault(_ROOT, ctx.agent) is not ctx.agent:
            await self._set(ctx.agent, deps)  # First starter is the root; everyone after is a delegate.

    async def before_tool_execute(
            self, ctx: RunContext[KiberniktoDeps], *, call: ToolCallPart, tool_def: ToolDefinition,
            args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        deps = ctx.deps
        if isinstance(deps, TelegramDeps) and deps.extra.get(_ROOT) is ctx.agent and tool_def.name not in self.skip_tools:
            await self._set(ctx.agent, deps)
        return args

    async def _set(self, agent: object, deps: TelegramDeps) -> None:
        emoji = getattr(agent, "reaction", None)
        if not emoji or deps.message is None or not deps.billable:
            return  # Peer envelopes (billable=False) answer a bot: no reactions on the wire request.
        if deps.extra.get(_CURRENT) == emoji:
            return
        deps.extra[_CURRENT] = emoji
        await self._react(deps, emoji)

    async def _react(self, deps: TelegramDeps, emoji: str) -> None:
        message = deps.message
        try:
            async with asyncio.timeout(self.timeout):
                await message.bot.set_message_reaction(
                    chat_id=message.chat.id, message_id=message.message_id,
                    reaction=[ReactionTypeEmoji(emoji=emoji)],
                )
        except (TelegramAPIError, TimeoutError) as error:  # Union types are not catchable; `as` needs parens.
            logger.warning("Reaction %s failed for chat %s: %s", emoji, message.chat.id, error)
