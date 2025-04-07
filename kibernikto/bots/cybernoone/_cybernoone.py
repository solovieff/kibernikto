import logging
import traceback
from typing import Literal

from openai import PermissionDeniedError, AsyncOpenAI
from openai._types import NOT_GIVEN

from kibernikto.interactors.openai_executor import DEFAULT_CONFIG
from kibernikto.telegram.telegram_bot import TelegramBot, KiberniktoChatInfo
from kibernikto.interactors import OpenAiExecutorConfig, OpenAIRoles

from kibernikto.plugins import KiberniktoPluginException


class Kibernikto(TelegramBot):
    """
    Basic implementation of Telegram bot.
    """

    def __init__(self, master_id: str, username: str, config: OpenAiExecutorConfig, key=NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None, hide_errors=True, add_chat_info: bool = True,
                 client: AsyncOpenAI = None):
        """
        :param master_id: telegram admin id
        :param username: telegram username
        :param config: ai bot config
        """
        self.key = key
        self.hide_errors = hide_errors
        self.add_chat_info = add_chat_info
        super().__init__(config=config, username=username, master_id=master_id, key=key, chat_info=chat_info,
                         client=client)

    async def heed_and_reply(self, message: str, author=NOT_GIVEN, save_to_history=True,
                             response_type: Literal['text', 'json_object'] = 'text', additional_content=None):
        if self.username in message:
            message_to_send = message.replace(f"@{self.username}", '')
        else:
            message_to_send = message

        parent_call_obj = {
            'message': message_to_send,
            'author': author,
            'save_to_history': save_to_history,
            'response_type': response_type,
            'additional_content': additional_content
        }

        if not self.hide_errors:
            return await super().heed_and_reply(**parent_call_obj)
        else:
            try:
                return await super().heed_and_reply(**parent_call_obj)
            except KiberniktoPluginException as e:
                return f" {e.plugin_name} не сработал!\n\n {str(e)}"
            except PermissionDeniedError as pde:
                logging.warning(f"Что-то грубое и недопустимое! {str(pde)}")
                return "Что-то грубое и недопустимое в ваших словах!"
            except Exception as e:
                print(traceback.format_exc())
                return f"Я не справился! Горе мне! {str(e)}"

    def _reset(self, **kwargs):
        """
        Adding additional data to default system message

        :return:
        """
        super()._reset(**kwargs)
        wai = self.full_config.who_am_i.format(self.full_config.name)
        if self.chat_info and self.add_chat_info:
            conversation_information = self._get_telegram_chat_info()
            wai += f"[{conversation_information}]"
        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")

    def _get_telegram_chat_info(self):
        if self.chat_info is None:
            return ""
        chat_descr_string = "[Static info from client app]\n"
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
        chat_descr_string = f"{chat_descr_string}\n[End static info from client app]\n"

        # print(f"{self.__class__.__name__}: {chat_descr_string}")
        return chat_descr_string

    async def update_configuration(self, config_to_use: OpenAiExecutorConfig):
        if self.restrict_client_instance is True:
            raise RuntimeError("updating the running instance config is restricted!")
        if self.full_config.key != config_to_use.key or self.full_config.url != config_to_use.url:
            await self.client.close()
            self.client = AsyncOpenAI(base_url=config_to_use.url, api_key=config_to_use.key,
                                      max_retries=DEFAULT_CONFIG.max_retries)

        self.full_config = config_to_use
        self.model = config_to_use.model
        self.master_call = config_to_use.master_call
        self.reset_call = config_to_use.reset_call
        self._set_max_history_len(config=config_to_use)
        self.tools = config_to_use.tools

        print(f'- {self.__class__.__name__} for "{self.chat_info.full_name}" (id: {self.full_config.id}) update!')
        # print(f'- {self.tools_names}')
        # print(f'- {self.max_messages}')
        # print(f'- {self.model}')
        # print(f'- {self.full_config.who_am_i}')
        self._reset()
