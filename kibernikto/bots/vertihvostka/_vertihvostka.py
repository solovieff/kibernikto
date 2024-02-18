from openai._types import NOT_GIVEN

from kibernikto import constants
from kibernikto.interactors import BaseTextConfig, InteractorOpenAI
from kibernikto.bots.cybernoone.prompt_preqs import MAIN_VERBAGE
import openai

from kibernikto.plugins import KiberniktoPluginException


class Vertihvostka(InteractorOpenAI):

    def __init__(self, max_messages=10, master_id=None, name="Вертихвостка", username="vertihvostka_bot",
                 who_am_i=MAIN_VERBAGE['who_am_i'],
                 reaction_calls=['verti', 'привет', 'хонда']):
        """

        :param max_messages: message history length
        :param master_id: telegram id of the master user
        :param name: current bot name
        :param who_am_i: default avatar prompt
        :param reaction_calls: words that trigger a reaction
        """
        pp = BaseTextConfig(who_am_i=who_am_i,
                            reaction_calls=reaction_calls, my_name=name)
        self.master_id = master_id
        self.name = name
        self.username = username
        super().__init__(model=constants.OPENAI_API_MODEL, max_messages=max_messages, default_config=pp)

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        try:
            reply = await super().heed_and_reply(message, author, save_to_history=save_to_history)
            return reply
        except KiberniktoPluginException as e:
            return f" {e.plugin_name} не сработала!\n\n {str(e)}"
        except Exception as e:
            return f"Я не знаю что сказать! {str(e)}"

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        return parent_should or self.username in message_text
