"""CreditTier — credit-balanced model selection and post-run charging as a pydantic-ai capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic_ai import AgentRunResult, ModelSelectionContext, RunContext
from pydantic_ai.capabilities import AbstractCapability, ModelSelector
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.errors import InsufficientCreditsError
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.singletons import chat_data

logger = logging.getLogger(__name__)

type Tier = Literal["poor", "medium", "rich"]


def credit_tier(credits: int) -> Tier:
    """Return the tier for a credit balance; thresholds mirror ``ConversationInfo.model_name``."""
    s = AGENT_KIBERNIKTO_SETTINGS
    if credits < s.POOR_CREDITS:
        return "poor"
    if credits >= s.RICH_CREDITS:
        return "rich"
    return "medium"


@dataclass
class CreditTier(AbstractCapability[KiberniktoDeps]):
    """Pick the model by the conversation's credit tier once per run, then charge ``effort`` after success.

    Explicit ``run(model=...)`` / ``agent.override(model=...)`` still win over the selection;
    non-billable runs use the agent's constructor model. Failed runs are never charged.
    """

    effort: int = 1
    models: dict[str, Model] = field(default_factory=dict)  # Model-name cache; pre-fill to inject models.
    conversation_id: str | None = None

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None  # Holds live Model instances — not spec-constructible.

    async def for_run(self, ctx: RunContext[KiberniktoDeps]) -> CreditTier:
        return replace(self, conversation_id=ctx.conversation_id or None)

    def get_model(self) -> ModelSelector[KiberniktoDeps]:
        return self._select

    async def before_run(self, ctx: RunContext[KiberniktoDeps]) -> None:
        if AGENT_KIBERNIKTO_SETTINGS.ALLOW_ZERO_CREDITS:
            return
        cid = _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id)
        if cid is None:
            return
        info = (ctx.deps.chat_info if isinstance(ctx.deps, KiberniktoDeps) else None) or await chat_data.load(cid)
        if info.credits <= 0:
            raise InsufficientCreditsError()

    async def after_run(self, ctx: RunContext[KiberniktoDeps], *, result: AgentRunResult[Any]) -> AgentRunResult[Any]:
        cid = _billable_conversation(ctx.deps, self.conversation_id or ctx.conversation_id)
        if cid is None:
            return result
        info = await chat_data.load(cid)  # Fresh read: a top-up landed mid-run must not be overwritten.
        previous = credit_tier(info.credits)
        info.charge(effort=self.effort)
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
        info = (ctx.deps.chat_info if isinstance(ctx.deps, KiberniktoDeps) else None) or await chat_data.load(cid)
        return self._model(info.model_name)

    def _model(self, name: str) -> Model:
        if name not in self.models:
            self.models[name] = infer_kibernikto_model(name)
        return self.models[name]


def _billable_conversation(deps: object, conversation_id: str | None) -> str | None:
    """Conversation to bill and tier by; None without a conversation_id or when ``deps.billable`` is False."""
    if not conversation_id:
        return None
    if isinstance(deps, KiberniktoDeps) and not deps.billable:
        return None
    return conversation_id
