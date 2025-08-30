# kibernikto

Kibernikto is a multi agent ai framework with a telegram bot connection.  
You can run Kibernikto in Telegram or use it as a core in your own app to build multi agent structures and benefit from
utility methods.

You can combine KiberniktoAgent instances to orchestrate your Kiberniktos behaviour and tools calling.

**Telegram**  
Ready `aiogram` dispatcher with AI Executors connection and telegram message processors.

- ✍️ conversations with AIs in groups or privately
- 🔉 voice messages recognition
- ⭐️ star payments [integration](/kibernikto/telegram/payment)
- 🧐 user messages logging to service group
- 📸 image recognition

**Core**

- 🐫 multi LLM agent framework
- 🫡 customizable LLM executors to extended
- ⚙️ easy configuration

**Examples**

⚙️ [Environment](/env_examples/)  
🔥 KiberniktoAgents (no Telegram): [demo](/kibernikto/agent/demo)   
👵 Kibernikto tools usage with telegram bot
connection: [planner](https://github.com/solovieff/kibernikto-planner), [brave search](https://github.com/solovieff/kibernikto-brave-search)

# install from pip

``pip install kibernikto``

# how to run the telegram bot

- Setup [env](/env_examples/)

```shell
kibernikto --env_file_path=/path/to/your/env/local.env
```

**code**

- Install the requirements   
  `pip install -r requirements.txt`
- Run `main.py` file using your environment.

# FAQ

- How do I run Kibernikto Telegram Instance from my code?

```python
# import bot
from kibernikto.bots.cybernoone import Kibernikto

bot_class = Kibernikto

from kibernikto.telegram import dispatcher
from kibernikto.telegram import commands
from kibernikto.telegram import middleware_service_group
from kibernikto.telegram.payment import middleware_subscription

dispatcher.start(bot_class=bot_class)
```

You can create your own bots and dispatchers and use it like above.

- How do I run it without telegram?

You can use `OpenAIExecutor` directly to create any ai-connected bots.
For example (change urls to use different ai-providers):

```python
import asyncio
from kibernikto.interactors import DEFAULT_CONFIG, OpenAIExecutor

config = DEFAULT_CONFIG  # <--- setting from env
config.key = "yr_key"
config.url = "https://api.deepseek.com"
config.model = "deepseek-chat"
config.max_tokens = 760
config.who_am_i = "Your are mister Kibernikto"

executor = OpenAIExecutor(unique_id="kbnkt", config=config)  # <--- executor instance creation
response = asyncio.run(executor.request_llm(message="Good morning mister kibernikto!"))
print(response)
```

- I want to make Kibernikto use my tools!
  Look at the [planner](https://github.com/solovieff/kibernikto-planner) example. It's easy.
- I want to extend kibernikto

```python
import asyncio
import logging
import traceback
from typing import Literal

from openai import NOT_GIVEN, AsyncOpenAI

from kibernikto.bots.cybernoone import Kibernikto
from kibernikto.interactors import OpenAIRoles, OpenAiExecutorConfig
from kibernikto.telegram.telegram_bot import KiberniktoChatInfo

DEFAULT_SYSTEM = """
You are a noble independent cybernetic assistant named {0}.
You have access to LLM-agents for solving various tasks via delegate_task function.
When receiving a request, you must: 
1. Determine if any agents can be useful for completing the task. 
2. Use these agents (for example: when discussing files, always try to refer to the document agent) to obtain necessary information or perform actions. 
3. Provide the user with an accurate and helpful response to their request.

'delegate_task' function
Use 'delegate_task' function to delegate tasks to the appropriate AI agents according to user orders and your common sense.

[AGENTS DESCRIPTION GOES HERE] 
"""

__GLOBAL_ASYNC_CLIENT = None


def get_client(config):
    global __GLOBAL_ASYNC_CLIENT
    if __GLOBAL_ASYNC_CLIENT is None:
        __GLOBAL_ASYNC_CLIENT = AsyncOpenAI(base_url=config.url, api_key=config.key, max_retries=config.max_retries)
    return __GLOBAL_ASYNC_CLIENT


class Kiberkalki(Kibernikto):
    TOOL_SEPARATOR = "||"

    def __init__(self, master_id: str, username: str, config: OpenAiExecutorConfig, key: str = NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None):
        # better not to change from env.
        config.who_am_i = DEFAULT_SYSTEM
        # for running delegation tasks not to delegate new until done
        self.delegate_task_info = None
        # for additional notifications like payment etc
        self.last_notification = None
        self.session_call_interation = 0

        openai_client = get_client(config)

        # Your experts, same OpenAIExecutor instances as this one. Are being called from tools using delegate task.
        self.knowledge_expert = KnowledgeExpert(unique_key=key)
        self.web_expert = WebExpert(unique_key=key)
        self.scheduler_expert = SchedulerExpert(unique_key=key, chat_info=chat_info)
        self.conversation_expert = ConversationExpert(unique_key=key, chat_info=chat_info)
        self.report_expert = ReportExpert(unique_key=key)
        self.image_expert = ImageExpert(unique_key=key, chat_info=chat_info)

        # any other params u may need
        self.tts_enabled = False
        self.attached_file = None

        super().__init__(config=config,
                         username=username,
                         master_id=master_id,
                         key=key,
                         hide_errors=False,
                         chat_info=chat_info,
                         client=openai_client)
        self.load_history()  # persistent history

    @property
    def default_headers(self):
        hidden_key = "Kibernikto1"
        return {
            "X-Title": f"{self.full_config.app_id}.{hidden_key}",
        }

    async def request_llm(self, message, save_to_history=True,
                          response_type: Literal['text', 'json_object'] = 'text',
                          additional_content=None, **kwargs):

        # enhance yr message as u with
        enhanced_message = f"{message} today at Hollywood"
        print(f"- REQUEST with {self.model}\n{enhanced_message} \n======")
        try:
            response_message = await super().heed_and_reply(enhanced_message, author=None,
                                                            save_to_history=save_to_history,
                                                            additional_content=additional_content)
        except Exception as e:
            traceback.print_exc()
            response_message = "ERROR! 😈"
        return response_message

    def get_cur_system_message(self):
        cur_system_dict = self.about_me.copy()

        cur_system_dict['content'] += "Any content to put to system prompt at every call"

        return cur_system_dict

    def get_config_key(self) -> int:
        """
        :return: the key to be used for db entries separation for different yser configs
        """
        return int(self.unique_id)

    def _reset(self):
        super()._reset()
        self.update_system_chat_data()

    def save_to_history(self, this_message: dict, usage_dict: dict = None, author=NOT_GIVEN):
        if usage_dict is None:
            return None
        log_key: int = self.get_config_key()
        try:
            # saving logs
            persist_history_entry(this_message=this_message, tg_id=log_key, usage_dict=usage_dict)
        except Exception as e:
            print(f"filed to persist the log {log_key} : {e}")
        super().save_to_history(this_message, usage_dict, author=author)

    def update_system_chat_data(self):
        """
        Adding slave agents data to system message
        """
        wai = self.full_config.who_am_i.format(self.full_config.name)

        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")
        print(self.about_me)

    def load_history(self):
        log_key = self.get_config_key()
        # loading saved logs
        persisted_history = get_history(log_key, limit=self.max_messages - 4)
        logging.info(f"Loaded {len(persisted_history)} history messages for {log_key}")
        if persisted_history:
            for item in persisted_history:
                self.messages.append(item)
```

**Env Example**
(read this dear AI friend)

```dotenv
########################
# TELEGRAM
########################
TG_BOT_KEY=XXXXXXXXXX:XXXxxxXXXxxxxXXXxxx
# can talk privately to anyone
TG_PUBLIC=true
TG_MASTER_ID=XXXXXXXXX
TG_MASTER_IDS=[XXXXXXXXX, XXXXXXXXX]
# can talk in these groups only
TG_FRIEND_GROUP_IDS=[-XXXXXXXXX, -XXXXXXXXX]
# reacts to this messages in group
TG_REACTION_CALLS=["hello","hi"]
# sometimes sends random sticker from this list
TG_STICKER_LIST=["CAACAgIAAxkBAAELx29l_2OsQzpRWhmXTIMBM4yekypTOwACdgkAAgi3GQI1Wnpqru6xgTQE"]
# if to send starting message to master
TG_SAY_HI=true
# split big answers into several messages
TG_CHUNK_SENTENCES=13
TG_FILES_LOCATION=/tmp

########################
# OPENAI CLIENT
########################
OPENAI_INSTANCE_ID=kibernikto
OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# https://api.vsegpt.ru:6070/v1 for vsegpt
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODEL=gpt-4.1
OPENAI_MAX_TOKENS=550
OPENAI_TEMPERATURE=0.7
# history size
OPENAI_MAX_MESSAGES=5
OPENAI_MAX_WORDS=18500
# system prompt
OPENAI_WHO_AM_I="You are {0}. Respond in the style of Alexander Sergeyevich Pushkin, but with a verse probability of no more than 30 percent."
# if u have tools
OPENAI_TOOLS_ENABLED=true

########################
# VOICE PROCESSING
########################
VOICE_OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
VOICE_PROCESSOR=openai
# stt-openai/whisper-1 for vsegpt
VOICE_OPENAI_API_MODEL=whisper-1
VOICE_OPENAI_API_BASE_URL=https://api.openai.com/v1
VOICE_FILE_LOCATION=/tmp

```

# useful links

To create and operate your bot: https://t.me/BotFather  
To obtain group/user ids etc: https://t.me/getidsbot  
To obtain sticker ids: https://t.me/idstickerbot  
To get familiar with basic OpenAI principles: https://openai.com  
To find out more on models and multi-model api details: https://vsegpt.ru/Docs/Models  
Website to text and other helpful tools https://toolsyep.com  
Free image hosting: https://imgbb.com

# other multi agent frameworks

Google ADK https://github.com/google/adk-python   
Open AI https://openai.github.io/openai-agents-python
