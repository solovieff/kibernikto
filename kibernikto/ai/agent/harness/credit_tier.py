"""CreditTier — credit-balanced model selection and post-run charging as a pydantic-ai capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai import AgentRunResult, ModelSelectionContext, RunContext
from pydantic_ai.capabilities import AbstractCapability, ModelSelector
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.errors import InsufficientCreditsError
from kibernikto.ai.agent.telegram.deps import TelegramDeps
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


def _billable_chat(deps: object) -> int | None:
    """Chat to bill and tier by; None for non-Telegram deps or non-billable (peer envelope) runs."""
    if not isinstance(deps, TelegramDeps) or not deps.billable:
        return None
    return deps.chat_id


@dataclass
class CreditTier(AbstractCapability[TelegramDeps]):
    """Pick the model by the chat's credit tier once per run, then charge ``effort`` after success.

    Explicit ``run(model=...)`` / ``agent.override(model=...)`` still win over the selection;
    non-billable runs use the agent's constructor model. Failed runs are never charged.
    """

    effort: int = 1
    models: dict[str, Model] = field(default_factory=dict)  # Model-name cache; pre-fill to inject models.

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None  # Holds live Model instances — not spec-constructible.

    def get_model(self) -> ModelSelector[TelegramDeps]:
        return self._select

    async def before_run(self, ctx: RunContext[TelegramDeps]) -> None:
        if AGENT_KIBERNIKTO_SETTINGS.ALLOW_ZERO_CREDITS:
            return
        chat_id = _billable_chat(ctx.deps)
        if chat_id is None:
            return
        info = ctx.deps.chat_info or await chat_data.load(chat_id)
        if info.credits <= 0:
            raise InsufficientCreditsError()

    async def _select(self, ctx: ModelSelectionContext[TelegramDeps]) -> Model:
        if ctx.run_step > 1 and ctx.model is not None:
            return ctx.model  # Tier is pinned for the whole run: no storage hit per tool step.
        chat_id = _billable_chat(ctx.deps)
        if chat_id is None:
            if ctx.model is None:
                raise UserError("CreditTier needs a constructor model for non-billable runs")
            return ctx.model
        info = ctx.deps.chat_info or await chat_data.load(chat_id)  # Reuse the build_deps snapshot.
        return self._model(info.model_name)

    def _model(self, name: str) -> Model:
        if name not in self.models:
            self.models[name] = infer_kibernikto_model(name)
        return self.models[name]

    async def after_run(self, ctx: RunContext[TelegramDeps], *, result: AgentRunResult[Any]) -> AgentRunResult[Any]:
        chat_id = _billable_chat(ctx.deps)
        if chat_id is None:
            return result
        info = await chat_data.load(chat_id)  # Fresh read: a top-up landed mid-run must not be overwritten.
        previous = credit_tier(info.credits)
        info.charge(effort=self.effort)
        await chat_data.save(chat_id, info)
        if (current := credit_tier(info.credits)) != previous:
            logger.info("Model tier changed for chat %s: %s -> %s", chat_id, previous, current)
        return result
