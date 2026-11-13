"""Synthesize final agent responses for Telegram voice-mode chats."""

import asyncio
import logging
import re
from dataclasses import replace

from pydantic_ai import AgentRunResult, BinaryContent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import FilePart

from kibernikto.ai.speech import TTS_TIMEOUT_SECONDS, synthesize_speech
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
        try:
            # Eleven v4 accepts at most 10,000 characters per request; send long responses in parts.
            chunks = [text[i:i + 9000] for i in range(0, len(text), 9000)]
            async with asyncio.timeout(TTS_TIMEOUT_SECONDS):
                audio = [await synthesize_speech(chunk) for chunk in chunks]
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
