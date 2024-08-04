import logging
import traceback

from openai import PermissionDeniedError
from openai._types import NOT_GIVEN

from kibernikto.telegram.telegram_bot import TelegramBot, KiberniktoChatInfo
from kibernikto.interactors import OpenAiExecutorConfig, OpenAIRoles

from kibernikto.plugins import KiberniktoPluginException


class Kibernikto(TelegramBot):
    """
    Basic implementation of Telegram bot.
    """

    def __init__(self, master_id: str, username: str, config: OpenAiExecutorConfig, key=NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None, hide_errors=True, add_chat_info: bool = True, ):
        """
        :param master_id: telegram admin id
        :param username: telegram username
        :param config: ai bot config
        """
        self.key = key
        self.hide_errors = hide_errors
        self.add_chat_info = add_chat_info
        super().__init__(config=config, username=username, master_id=master_id, key=key, chat_info=chat_info)

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        if self.username in message:
            message_to_send = message.replace(f"@{self.username}", '')
        else:
            message_to_send = message

        if not self.hide_errors:
            return await super().heed_and_reply(message_to_send, author, save_to_history=save_to_history)
        else:
            try:
                return await super().heed_and_reply(message_to_send, author, save_to_history=save_to_history)
            except KiberniktoPluginException as e:
                return f" {e.plugin_name} не сработал!\n\n {str(e)}"
            except PermissionDeniedError as pde:
                logging.warning(f"Что-то грубое и недопустимое! {str(pde)}")
                return "Что-то грубое и недопустимое в ваших словах!"
            except Exception as e:
                print(traceback.format_exc())
                return f"Я не справился! Горе мне! {str(e)}"

    def _reset(self):
        """
        Adding additional data to default system message

        :return:
        """
        super()._reset()
        wai = self.full_config.who_am_i.format(self.full_config.name)
        if self.chat_info and self.add_chat_info:
            conversation_information = self._generate_chat_info()
            wai += f"\n{conversation_information}"
        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")

    def _generate_chat_info(self):
        if self.chat_info is None:
            return ""
        if self.chat_info.is_personal:
            chat_descr_string = f"{self.chat_info.aiogram_user.full_name} ищет твоей мудрости, не стесняйся иногда называть по имени (на русском!). При обращении учитывай мужчина это или женщина!"
            if self.chat_info.bio:
                chat_descr_string += f"В bio собеседника указано: {self.chat_info.bio}, учитывай это."
            if self.chat_info.birthday:
                chat_descr_string += f"День рождения: {self.chat_info.birthday}."
        else:
            chat_descr_string = f"Участники группы {self.chat_info.full_name} ищут твоей мудрости."
            if self.chat_info.description:
                chat_descr_string += f"В description указано: {self.chat_info.description}."
        chat_descr_string = f"[{chat_descr_string}]"

        print(f"chat info: {chat_descr_string}")
        return chat_descr_string
