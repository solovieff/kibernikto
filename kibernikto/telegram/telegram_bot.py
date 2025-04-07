from aiogram.types import Chat, User
from aiogram.enums import ChatType
from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from pydantic import BaseModel
from kibernikto.interactors import OpenAIExecutor, OpenAiExecutorConfig


class KiberniktoChatInfo:
    def __init__(self, aiogram_chat: Chat, aiogram_user: User = None):
        self.full_name = aiogram_chat.full_name
        self.bio = aiogram_chat.bio
        self.description = aiogram_chat.description
        self.business_intro = aiogram_chat.business_intro
        self.birthday = None
        self.is_personal = aiogram_chat.type == ChatType.PRIVATE
        self.id = aiogram_chat.id
        if self.is_personal and not aiogram_user:
            raise ValueError("Failed to create kibernikto chat with private chat: no user info provided")

        if not self.is_personal:
            self.bio = aiogram_chat.description
        self.aiogram_user = aiogram_user


class TelegramBot(OpenAIExecutor):
    def __init__(self, config: OpenAiExecutorConfig, master_id, username, key=NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None, client: AsyncOpenAI = None):
        self.key = key
        self.master_id = master_id
        self.username = username
        self.chat_info = chat_info
        super().__init__(config=config, unique_id=key, client=client)

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        mt_lower = message_text.lower()
        if self.full_config.name.lower() in mt_lower:
            return True

        if self.username.lower() in mt_lower:
            return True
        return parent_should or self.username.lower() in mt_lower

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id
