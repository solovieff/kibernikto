from kibernikto import constants
from kibernikto.interactors import BaseTextConfig, InteractorOpenAI
from kibernikto.bots.cybernoone.prompt_preqs import MAIN_VERBAGE
import openai

class Cybernoone(InteractorOpenAI):

    def __init__(self, max_messages=10, master_id=None, name="Киберникто", who_am_i=MAIN_VERBAGE['who_am_i'],
                 reaction_calls=['никто', 'падаль', 'хонда']):
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
        super().__init__(model=constants.OPENAI_API_MODEL, max_messages=max_messages, default_config=pp)

    async def ask_pure(self, prompt):
        response = await openai.ChatCompletion.acreate(
            model=self.model,
            messages=prompt,
            max_tokens=constants.OPENAI_MAX_TOKENS,
            temperature=constants.OPENAI_TEMPERATURE,
        )
        response_text = response['choices'][0]['message']['content'].strip()
        print(response_text)
        return response_text

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id
