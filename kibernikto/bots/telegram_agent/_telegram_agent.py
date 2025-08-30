import logging
import traceback
from typing import Literal

from openai import PermissionDeniedError, AsyncOpenAI
from openai._types import NOT_GIVEN

from kibernikto.agent.kibernikto_agent import KiberniktoAgent
from kibernikto.interactors.openai_executor import DEFAULT_CONFIG
from kibernikto.telegram.telegram_bot import TelegramBot, KiberniktoChatInfo
from kibernikto.interactors import OpenAiExecutorConfig, OpenAIRoles


class KiberniktoTelegramAgent(KiberniktoAgent):
    """
    Basic implementation of Telegram bot.
    """

    def __init__(self, username: str, config: OpenAiExecutorConfig, key=NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None, hide_errors=True, add_chat_info: bool = True,
                 client: AsyncOpenAI = None, agents: KiberniktoAgent = (), **kwargs
                 ):
        """
        :param username: telegram username
        :param config: ai bot config
        """
        self.key = key
        self.chat_info = chat_info
        self.hide_errors = hide_errors
        self.add_chat_info = add_chat_info
        self.username = username

        super().__init__(config=config,
                         unique_id=key,
                         agents=agents,
                         label="base-kibernikto-agent",
                         description="Basic kibernikto agent to talk with.",
                         client=client)

    async def query(self, message, effort_level: int, call_session_id: str = None, **kwargs):
        return await super().query(message=message, call_session_id=call_session_id, effort_level=effort_level,
                                   **kwargs)

    async def request_llm(self, message: str, author=NOT_GIVEN, save_to_history=True,
                          response_type: Literal['text', 'json_object'] = 'text',
                          additional_content: dict = None, with_history: bool = True,
                          custom_model: str = None, call_session_id: str = None) -> str:
        if self.username in message:
            message_to_send = message.replace(f"@{self.username}", '')
        else:
            message_to_send = message

        parent_call_obj = {
            'message': message_to_send,
            'author': author,
            'save_to_history': save_to_history,
            'response_type': response_type,
            'additional_content': additional_content,
            'call_session_id': call_session_id
        }

        if not self.hide_errors:
            return await super().request_llm(**parent_call_obj)
        else:
            try:
                return await super().request_llm(**parent_call_obj)
            except PermissionDeniedError as pde:
                logging.warning(f"Что-то грубое и недопустимое! {str(pde)}")
                return "Что-то грубое и недопустимое в ваших словах!"
            except Exception as e:
                print(traceback.format_exc())
                return f"Я не справился! Горе мне! {str(e)}"

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

    def _reset(self, **kwargs):
        """
        Adding additional data to default system message

        :return:
        """
        super()._reset(**kwargs)
        wai = self.full_config.who_am_i.format(self.full_config.name)
        if self.chat_info and self.add_chat_info:
            conversation_information = self._get_telegram_chat_info()
            wai += f"{conversation_information}"
        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")

    def _get_telegram_chat_info(self):
        if self.chat_info is None:
            return ""
        chat_descr_string = "\n[Static client app info]\n"
        if self.chat_info.is_personal:
            chat_descr_string += f"Name: {self.chat_info.aiogram_user.full_name}."
            if self.chat_info.bio:
                chat_descr_string += f"Bio: {self.chat_info.bio}."
            if self.chat_info.birthday:
                chat_descr_string += f"Birthday: {self.chat_info.birthday}."
        else:
            chat_descr_string += f"Title: {self.chat_info.full_name}."
            if self.chat_info.description:
                chat_descr_string += f"Description: {self.chat_info.description}."
        chat_descr_string = f"{chat_descr_string}\n"

        # print(f"{self.__class__.__name__}: {chat_descr_string}")
        return chat_descr_string
