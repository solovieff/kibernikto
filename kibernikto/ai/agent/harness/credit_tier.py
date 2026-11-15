"""CreditTier — credit-balanced model selection and post-run charging as a pydantic-ai capability."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace

from pydantic_ai import AgentRunResult, ModelSelectionContext, RunContext
from pydantic_ai.capabilities import AbstractCapability, ModelSelector
from pydantic_ai.capabilities.abstract import ValidatedToolArgs
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.errors import InsufficientCreditsError
from kibernikto.ai.agent.harness.tariff import Tariff, credit_tier
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.models import ConversationInfo
from kibernikto.storage.singletons import chat_data

logger = logging.getLogger(__name__)

DELEGATE_TOOL_NAME = "delegate_task"  # Tool name of the harness ``SubAgents`` capability.


def format_credit_status(
        credits: int,
        *,
        conversation_id: str | None = None,
        is_admin: bool = False,
        is_personal: bool = True,
) -> str:
    """Format the current credit balance, tier thresholds, and paid-expert access for the model."""
    s = AGENT_KIBERNIKTO_SETTINGS
    tariff = Tariff(credits, is_personal=is_personal)
    tier = tariff.tier
    zero_policy = "switches to poor tier" if s.ALLOW_ZERO_CREDITS else "blocks runs until topped up"
    status = (
        f"credits: {credits} | tier: {tier} | "
        f"tiers: poor (<{s.POOR_CREDITS}), medium ({s.POOR_CREDITS}..{s.RICH_CREDITS - 1}), rich (>={s.RICH_CREDITS}) | "
        f"at_zero: {zero_policy}"
    )
    if experts := tariff.experts_line():
        status += f" | {experts}"
    if is_admin:
        self_id = conversation_id or "<your_tg_id>"
        status += (
            " | admin_commands (caller is admin): "
            f"grant/deduct credits for yourself (this chat): /pay <±credits> {self_id} (e.g. /pay 500 {self_id}), "
            "grant/deduct credits for another user or chat: /pay <±credits> <tg_id>, "
            "check another chat's balance: /balance <tg_id>"
        )
    return status


@dataclass
class CreditTier(AbstractCapability[KiberniktoDeps]):
    """Pick the model by the conversation's credit tier once per run, then charge it after success.

    A run is priced by its tokens: one credit per ``TOKENS_PER_CREDIT`` tokens of the whole run, every
    sub-agent included, with cache reads weighted by ``CACHE_TOKEN_WEIGHT``. The fixed ``effort`` is only the
    floor: run effort plus ``SUBAGENT_EFFORT`` per successful ``delegate_task`` (``0`` = free run), and chats in
    voice (``audio``) mode pay the run effort twice.

    Explicit ``run(model=...)`` / ``agent.override(model=...)`` still win over the selection;
    non-billable runs use the agent's constructor model. Failed runs are never charged.
    """

    effort: int | None = None  # None = ``AGENT_KIBERNIKTO_RUN_EFFORT``.
    models: dict[str, Model] = field(default_factory=dict)  # Model-name cache; pre-fill to inject models.
    conversation_id: str | None = None
    _run_info: ConversationInfo | None = field(default=None, init=False, repr=False)
    _delegations: int = field(default=0, init=False, repr=False)  # Per-run copy only (see ``for_run``).

    @property
    def run_effort(self) -> int:
        """Credits for one successful run: explicit ``effort`` or the env default, never negative."""
        effort = AGENT_KIBERNIKTO_SETTINGS.RUN_EFFORT if self.effort is None else self.effort
        return max(0, effort)

    def _run_cost(self, info: ConversationInfo) -> int:
        """Run effort, doubled while the chat replies with voice."""
        return self.run_effort * (2 if info.response_mode == 'audio' else 1)

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None  # Holds live Model instances — not spec-constructible.

    async def for_run(self, ctx: RunContext[KiberniktoDeps]) -> CreditTier:
        return replace(self, conversation_id=ctx.conversation_id or None)

    def get_model(self) -> ModelSelector[KiberniktoDeps]:
        return self._select

    def get_toolset(self) -> FunctionToolset[KiberniktoDeps]:
        return FunctionToolset([self.check_credits])

    async def check_credits(self, ctx: RunContext[KiberniktoDeps]) -> str:
        """Tariff info for this chat: credit balance, tier, which paid experts are available and the access rules.

        Call it when the user asks about credits, limits or access, or wants something an expert would do
        but none is in your roster. Explain the result to the user instead of refusing or improvising.
        """
        cid = _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id)
        if cid is None:
            return "credits: untracked (non-billable run)"
        info = await self._load_info(ctx.deps, cid)
        is_admin = isinstance(ctx.deps, KiberniktoDeps) and ctx.deps.is_admin
        return format_credit_status(
            info.credits, conversation_id=cid, is_admin=is_admin, is_personal=getattr(ctx.deps, 'is_personal', True),
        )

    async def before_run(self, ctx: RunContext[KiberniktoDeps]) -> None:
        if AGENT_KIBERNIKTO_SETTINGS.ALLOW_ZERO_CREDITS:
            return
        cid = _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id)
        if cid is None:
            return
        info = await self._load_info(ctx.deps, cid)
        if info.credits <= 0:
            raise InsufficientCreditsError()

    async def after_tool_execute(self, ctx: RunContext[KiberniktoDeps], *, call: ToolCallPart,
                                 tool_def: ToolDefinition, args: ValidatedToolArgs, result: object) -> object:
        # Successful delegations only: failed or retried calls never reach this hook.
        if tool_def.name == DELEGATE_TOOL_NAME and _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id):
            self._delegations += 1
        return result

    async def after_run(self, ctx: RunContext[KiberniktoDeps], *, result: AgentRunResult[object]) -> AgentRunResult[object]:
        cid = _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id)
        if cid is None:
            return result
        info = await chat_data.load(cid)  # Fresh read: a top-up landed mid-run must not be overwritten.
        floor = self._run_cost(info) + self._delegations * max(0, AGENT_KIBERNIKTO_SETTINGS.SUBAGENT_EFFORT)
        total = max(floor, _usage_credits(result.usage))  # Whole run, sub-agents included: the floor is a minimum.
        if total == 0:
            return result  # Free run: nothing to charge (``charge`` itself bills at least 1).
        previous = credit_tier(info.credits)
        info.charge(effort=total)
        await chat_data.save(cid, info)
        if (current := credit_tier(info.credits)) != previous:
            logger.info("Model tier changed for conversation %s: %s -> %s", cid, previous, current)
        return result

    async def _select(self, ctx: ModelSelectionContext[KiberniktoDeps]) -> Model:
        if ctx.run_step > 1 and ctx.model is not None:
            return ctx.model  # Tier is pinned for the whole run: no storage hit per tool step.
        cid = _billable_conversation(ctx.deps, self.conversation_id)
        if cid is None:
            if ctx.model is None:
                raise UserError("CreditTier needs a constructor model for non-billable runs")
            return ctx.model
        info = await self._load_info(ctx.deps, cid)
        return self._model(info.model_name)

    async def _load_info(self, deps: object, cid: str) -> ConversationInfo:
        if isinstance(deps, KiberniktoDeps) and deps.chat_info is not None:
            return deps.chat_info
        if self._run_info is None:
            self._run_info = await chat_data.load(cid)
        return self._run_info

    def _model(self, name: str) -> Model:
        if name not in self.models:
            self.models[name] = infer_kibernikto_model(name)
        return self.models[name]


def _usage_credits(usage: RunUsage) -> int:
    """Credits for the tokens the run burned: a published site is billed like the work it did."""
    s = AGENT_KIBERNIKTO_SETTINGS
    if s.TOKENS_PER_CREDIT <= 0:
        return 0
    cached = usage.cache_read_tokens * max(0.0, s.CACHE_TOKEN_WEIGHT)  # Cache reads are the cheap ones.
    tokens = usage.input_tokens + usage.cache_write_tokens + usage.output_tokens + cached
    return math.ceil(tokens / s.TOKENS_PER_CREDIT)


def _billable_conversation(deps: object, conversation_id: str | None) -> str | None:
    """Conversation to bill and tier by; None without a conversation_id or when ``deps.billable`` is False."""
    if not conversation_id:
        return None
    if isinstance(deps, KiberniktoDeps) and not deps.billable:
        return None
    return conversation_id
