"""TelegramCapability — bot identity, chat context, reactions and image tool for any Agent[TelegramDeps]."""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, CombinedCapability
from pydantic_ai.toolsets import FunctionToolset

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.image import generate_image

from .agent_reaction import AgentReaction
from .deps import TelegramDeps
from .identity import get_bot_identity


def _bot_identity_prompt(ctx: RunContext[TelegramDeps]) -> str:
    """Bot getMe + descriptions, fetched once at startup."""
    identity = get_bot_identity()
    return identity.as_prompt() if identity else ""


def _chat_context_prompt(ctx: RunContext[TelegramDeps]) -> str:
    """Per-run chat facts built by the transport."""
    return (ctx.deps.conversation_context or "") if isinstance(ctx.deps, TelegramDeps) else ""


class _TelegramContext(AbstractCapability[TelegramDeps]):
    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    def get_instructions(self):  # noqa: ANN201 — AgentInstructions
        return [_bot_identity_prompt, _chat_context_prompt]

    def get_toolset(self) -> FunctionToolset[TelegramDeps] | None:
        return FunctionToolset([generate_image]) if AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME else None


class TelegramCapability(CombinedCapability[TelegramDeps]):
    """Everything the model needs to live in Telegram; transport I/O stays in ``TelegramBridge``."""

    def __init__(self) -> None:
        super().__init__([_TelegramContext(), AgentReaction()])
