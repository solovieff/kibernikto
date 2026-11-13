"""Synthesize final agent responses for Telegram voice-mode chats."""

import asyncio
import logging
import re
from dataclasses import replace

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from pydantic_ai import AgentRunResult, BinaryContent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import FilePart

from kibernikto.ai.speech import TTS_TIMEOUT_SECONDS, prepare_for_speech, split_for_speech, synthesize_speech
from kibernikto.ai.agent.telegram.deps import TelegramDeps

logger = logging.getLogger(__name__)


def _voice_instructions(ctx: RunContext[TelegramDeps]) -> str:
    deps = ctx.deps
    if not isinstance(deps, TelegramDeps) or not deps.billable or not ctx.conversation_id:
        return ''
    if not deps.message or not deps.message.from_user or deps.message.from_user.is_bot:
        return ''
    if not deps.chat_info or deps.chat_info.response_mode != 'audio':
        return ''
    return (
        'Your answer will be spoken aloud. Optionally begin the answer with voice delivery tags '
        'in English in square brackets, matching your personality and the message, e.g. '
        '[sarcastic], [sighs], [whispering]. Place tags only at the beginning. '
        'Write naturally for speech and avoid unnecessary Markdown. '
        'Keep necessary links and factual details in your answer.'
    )


async def _show_recording(message: Message) -> None:
    """Best-effort "recording voice" indicator while TTS runs."""
    try:
        await message.bot.send_chat_action(message.chat.id, 'record_voice')
    except (TelegramAPIError, AttributeError):
        logger.debug('Chat action not sent', exc_info=True)


class SpeechReply(AbstractCapability[TelegramDeps]):
    """Attach speech to human replies while retaining their original text and history."""

    def get_instructions(self):  # noqa: ANN201 — AgentInstructions
        return _voice_instructions

    async def after_run(self, ctx: RunContext[TelegramDeps], *, result: AgentRunResult) -> AgentRunResult:
        deps = ctx.deps
        if not isinstance(deps, TelegramDeps) or not deps.billable or not ctx.conversation_id:
            return result
        if not deps.message or not deps.message.from_user or deps.message.from_user.is_bot:
            return result
        if not deps.chat_info or deps.chat_info.response_mode != 'audio' or not isinstance(result.output, str):
            return result
        text = result.output.strip()
        if not text:
            return result
        # Tags belong to the speech input, never to a text fallback or caption.
        result.output = re.sub(r'^(?:\s*\[[a-zA-Z ,\-]{1,50}\](?!\()\s*)+', '', text)
        spoken = prepare_for_speech(text)
        if not spoken:
            return result
        await _show_recording(deps.message)
        try:
            # One deadline for all chunks; they synthesize concurrently, gather keeps their order.
            async with asyncio.timeout(TTS_TIMEOUT_SECONDS):
                audio = await asyncio.gather(*(synthesize_speech(chunk) for chunk in split_for_speech(spoken)))
        except Exception:
            logger.exception('Voice synthesis failed; sending text instead')
            return result
        parts = [FilePart(content=BinaryContent(
            data=data, media_type='audio/mpeg', vendor_metadata={'telegram_voice': True, 'filename': 'voice.mp3'},
        )) for data in audio]
        response = result.response
        messages = result.all_messages()
        index = next(i for i in range(len(messages) - 1, -1, -1) if messages[i] is response)
        messages[index] = replace(response, parts=[*response.parts, *parts])
        return result
