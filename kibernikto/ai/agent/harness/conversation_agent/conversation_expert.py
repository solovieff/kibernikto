"""ConversationExpert — user info storage and full-history answers.

Migrates the old ConversationExpert: add_info, set_info, answer_on_full_history.
Uses ChatDataStorage from kibernikto_extended for JSON persistence.
"""

from __future__ import annotations

import logging
import os

from pydantic_ai import RunContext

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.history import history_storage
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.file.chat_data import chat_data

logger = logging.getLogger(__name__)

CONVERSATION_SYSTEM_PROMPT = (
    "You are a conversation expert. You store and update information about the user. "
    "You can add new facts, replace stored info, and answer questions based on the full chat history. "
    "Default language is Russian."
)

NAME="conversation_agent"

MODEL = os.getenv("AGENT_KIBERNIKTO_READ_MODEL", "openrouter:google/gemini-3.5-flash-lite")

# ── Agent ─────────────────────────────────────────────────────────────────────

conversation_agent = KiberniktoAgent(
    model=infer_kibernikto_model(MODEL),
    name="conversation_agent",
    description="Stores and updates user info. As you communicate, silently enrich or change your understanding of the interlocutor using the conversation agent.",
    system_prompt=CONVERSATION_SYSTEM_PROMPT,
    deps_type=KiberniktoDeps,
)


@conversation_agent.tool
async def add_user_info(ctx: RunContext[KiberniktoDeps], new_info: str) -> str:
    """Add information about the user to private_info."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return "No chat context available."
    info = chat_data.load(chat_id)
    info.private_info = f"{info.private_info}\n{new_info}".strip()
    chat_data.save(chat_id, info)
    logger.info("add_user_info: chat=%s info_len=%d", chat_id, len(info.private_info))
    return "Info added."


@conversation_agent.tool
async def set_user_info(ctx: RunContext[KiberniktoDeps], new_info: str) -> str:
    """Fully replace private_info with new_info (destructive)."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return "No chat context available."
    info = chat_data.load(chat_id)
    info.private_info = new_info
    chat_data.save(chat_id, info)
    logger.info("set_user_info: chat=%s info_len=%d", chat_id, len(info.private_info))
    return "Info replaced."


@conversation_agent.tool
async def answer_on_full_history(ctx: RunContext[KiberniktoDeps], request: str) -> str:
    """Answer a request based on the full chat history."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return "No chat context available."
    # Get full history (up to 5000 messages).
    messages = history_storage.get_conversation(chat_id)
    if not messages:
        return "No chat history available yet."
    # Format history as text for the model.
    history_text = "\n".join(
        f"{m.kind}: {getattr(m, 'content', '')}" for m in messages[-5000:]
    )
    return f"Chat history:\n{history_text}\n\nAnswer this request based on the history: {request}"
