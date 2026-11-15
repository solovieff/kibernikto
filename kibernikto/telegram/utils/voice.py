"""Telegram voice delivery errors and actionable recipient guidance."""

from aiogram.exceptions import TelegramBadRequest

VOICE_PRIVACY_NOTICE = (
    'Telegram does not let me send you voice messages. '
    'Check: Settings → Privacy → Voice Messages. Replying with text for now.'
)


def voice_messages_restricted(error: Exception) -> bool:
    """Recognize Telegram's recipient voice-message privacy restriction."""
    if not isinstance(error, TelegramBadRequest):
        return False
    description = error.message.lower()
    return 'user restricted receiving of voice note messages' in description or 'voice_messages_forbidden' in description
