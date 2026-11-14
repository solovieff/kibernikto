"""AgentReaction — every agent in the run tree marks the user's message with its own ``reaction`` emoji."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, ReactionTypeEmoji
from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.capabilities import AbstractCapability, ValidatedToolArgs
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import ModelRequestContext

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.config import APP_SETTINGS

from .deps import TelegramDeps

logger = logging.getLogger(__name__)

# deps.extra keys (deps are shared across the delegation tree): emoji on the message, the root agent, steered messages.
_CURRENT = "reaction"
_ROOT = "reaction_root"
_STEERED = "steered_messages"
_PENDING = "reaction_tasks"  # Strong refs to in-flight reaction tasks (the loop keeps only weak ones).
_SENT_AT = "reaction_sent_at"  # Monotonic time of the last reaction sent (run-wide throttle).


@dataclass
class AgentReaction(AbstractCapability[KiberniktoDeps]):
    """Mark ``deps.message`` with the agent's ``metadata["reaction"]``; the last emoji stays.

    Delegates react at run start. The root agent reacts on its own tool calls and on earlier
    messages absorbed by mid-run steering, so plain single-message chatter stays clean while
    steered follow-ups acknowledge the superseded message; ``skip_tools`` (delegation) is left
    to the delegate's own emoji. Any tool call reacts: the root with its own emoji, a delegate with a random
    one from ``tool_reactions`` (never the current one, so every change is visible). Whatever the source,
    every reaction goes through ``_set`` and its single throttle: at most one per ``reaction_interval`` seconds
    per run across the whole agent tree, so bursts and parallel calls cannot flood Telegram.
    Bind it on the parent and in ``SubAgents(shared_capabilities=...)`` so delegates
    react too. Cosmetic: Telegram failures are logged and never fail the run; they are sent fire-and-forget,
    so the agent never waits for Telegram. The capability alone owns every reaction rule (emoji choice, throttle,
    peer/group filtering); agents only expose ``metadata["reaction"]``. ``enabled`` (default ``APP_REACTIONS_ENABLED``)
    is the master switch: off, every hook is a no-op.
    """

    enabled: bool = field(default_factory=lambda: APP_SETTINGS.REACTIONS_ENABLED)
    timeout: float = 3.0
    skip_tools: frozenset[str] = frozenset({"delegate_task"})
    steered_reaction: str | None = "✍"
    tool_reactions: tuple[str, ...] = ("🤔", "👀", "🤓", "🔥", "🤨", "😎", "🫡", "⚡")  # Empty: no tool reactions.
    reaction_interval: float = 2.5  # Min seconds between reactions in one run, whatever their source; 0 disables.

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None  # Runtime-only Telegram side effect.

    async def before_run(self, ctx: RunContext[KiberniktoDeps]) -> None:
        if not self.enabled or not isinstance(deps := ctx.deps, TelegramDeps):
            return  # Deps-less runs (tests, scripts) have no message to mark.
        if deps.extra.setdefault(_ROOT, ctx.agent) is not ctx.agent:
            await self.react(ctx, deps)  # First starter is the root; everyone after is a delegate.

    async def before_model_request(
            self, ctx: RunContext[KiberniktoDeps], request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        deps = ctx.deps
        if self.enabled and isinstance(deps, TelegramDeps) and deps.extra.get(_ROOT) is ctx.agent:
            steered: list[Message] = deps.extra.get(_STEERED) or []
            emoji = self.steered_reaction
            if steered and emoji and deps.billable:
                while steered:
                    self._fire(deps, steered.pop(0), emoji)
        return request_context

    async def before_tool_execute(
            self, ctx: RunContext[KiberniktoDeps], *, call: ToolCallPart, tool_def: ToolDefinition,
            args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        deps = ctx.deps
        if not self.enabled or not isinstance(deps, TelegramDeps) or tool_def.name in self.skip_tools:
            return args
        if deps.extra.get(_ROOT) is ctx.agent:
            await self.react(ctx, deps)
        else:  # A delegate is busy with its tools: show it (no timers).
            await self.react(ctx, deps, self._pick_tool_emoji(deps))
        return args

    def _pick_tool_emoji(self, deps: TelegramDeps) -> str | None:
        current = (deps.extra.get(_CURRENT) or (None, None))[1]
        pool = [emoji for emoji in self.tool_reactions if emoji != current]
        return random.choice(pool) if pool else None

    async def react(self, ctx: RunContext[KiberniktoDeps], deps: TelegramDeps, emoji: str | None = None) -> None:
        """Mark the user's message with ``emoji`` (default: the agent's own); skipped for peer envelopes."""
        if deps.message is None or not deps.billable:
            return  # Peer envelopes (billable=False) answer a bot: nothing on the wire request.
        await self._set(ctx, deps, emoji)

    async def _set(self, ctx: RunContext[KiberniktoDeps], deps: TelegramDeps, emoji: str | None = None) -> None:
        emoji = emoji or (ctx.metadata or {}).get("reaction")
        if not emoji or deps.message is None:
            return
        key = (deps.message.message_id, emoji)
        now = time.monotonic()
        if deps.extra.get(_CURRENT) == key or now - deps.extra.get(_SENT_AT, -math.inf) < self.reaction_interval:
            return  # Duplicate or throttled; claimed before any await, so parallel calls see it too.
        deps.extra[_CURRENT] = key
        deps.extra[_SENT_AT] = now
        self._fire(deps, deps.message, emoji)

    def _fire(self, deps: TelegramDeps, message: Message, emoji: str) -> None:
        pending: set[asyncio.Task[None]] = deps.extra.setdefault(_PENDING, set())
        task = asyncio.create_task(self._react_message(message, emoji))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def _react_message(self, message: Message, emoji: str) -> None:
        try:
            async with asyncio.timeout(self.timeout):
                await message.bot.set_message_reaction(
                    chat_id=message.chat.id, message_id=message.message_id,
                    reaction=[ReactionTypeEmoji(emoji=emoji)],
                )
        except (TelegramAPIError, TimeoutError) as error:  # Union types are not catchable; `as` needs parens.
            logger.warning("Reaction %s failed for chat %s: %s", emoji, message.chat.id, error)
