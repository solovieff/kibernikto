# kibernikto

Kibernikto is an app/lib to easily run telegram bots connected to AI models with additional features.  
You can run Kibernikto with your params or use it as a core in your own app.

Kibernikto base `OpenAiExecutorConfig` class can be easily extended to be used outside telegram.

- ✍️ telegram conversations with different AIs in groups or privately via OpenAI api spec
- 🔉 voice messages recognition
- 👂 interviews and meetings (up to 2 hours) analysis right in Telegram using Gladia.io
- 🎞 youtube video summarization
- 🔗 webpage summarization
- 🧐 user messages logging to service group
- 📸 image recognition
- 🫡 openai function tools easy [integration](https://github.com/solovieff/kibernikto-planner). No more pain. It will work for antrophic, too, if u use a proxy.
- 🙈 [Brave search api](https://brave.com/search/api/) integration with openai tools.
  See [Kiberwebber](https://github.com/solovieff/kibernikto-brave-search) project for details.

Given an image Kibernikto will publish it to a free image hosting service and then process as a link.

- One Kibernikto instance can privately talk to one (`TG_MASTER_ID`) or several (`TG_MASTER_IDS`) users and be added to
  several (`TG_FRIEND_GROUP_IDS`) groups.
- Set `TG_PUBLIC` env to true to open your bot to everyone.

# install from pip

``pip install kibernikto``

# how to run

- Create telegram bot using @BotFather and obtain it's key. You can also change the picture and other details there. Set
  env `TG_BOT_KEY`.

  Turn off Group Privacy for your bot to be able to react to group messages:

  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/9f2ec25d-bde4-4eec-9ec6-65741101ce8d">  
  <br>
  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/bf1ac575-ad1a-464c-8535-2cf7f5ebb162">  

- Setup minimal env    
  First of all, all examples are in the [examples](/env_examples/) folder. See default ones for minimal config and fulls
  for more complicated cases.

**AI ENV**

- Default [OpenAI](https://openai.com)

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODEL=gpt-4
OPENAI_API_KEY=yr-key  
```

- Multimodel [vsegpt.ru](https://vsegpt.ru/)

```dotenv
OPENAI_BASE_URL=https://api.vsegpt.ru:6070/v1  
OPENAI_API_KEY=sk-yr-key  
OPENAI_API_MODEL=openai/gpt-4  
```

Other AI behaviour options, _not required_:

```dotenv
# system prompt
OPENAI_WHO_AM_I=Answer all questions as {0}, the majestic lord of the universes.
# chat history size
OPENAI_MAX_MESSAGES=5
# LLM temp param
OPENAI_TEMPERATURE=0.7
# LLM answer size
OPENAI_MAX_TOKENS=450
# summarize the dialog using same model after it contains more than OPENAI_MAX_WORDS words 
OPENAI_MAX_WORDS=8500
# if you want to use tools.
OPENAI_TOOLS_ENABLED=true
# if kibernikto knows the prices he can track the usage
OPENAI_OUTPUT_PRICE=0.000015
OPENAI_INPUT_PRICE=0.000005  
```

**Telegram ENV**

```dotenv
# Telegram configuration
TG_BOT_KEY=XXXXXXXXXX:XXXxxxXXXxxxxXXXxxx  
TG_PUBLIC=true
TG_MASTER_ID=XXXXXXXXX
```

Other TG related options, _not required_:

```dotenv
# Until TG_PUBLIC=true can talk only in the given groups
TG_FRIEND_GROUP_IDS=[-XXXXXXXXXX,-XXXXXXXXXX]  
# Other master accounts. Until TG_PUBLIC=true can talk only with these.
TG_MASTER_IDS=[XXXXXXXXX,XXXXXXXXX]
# Kibernikto reacts to direct replies or when sees the following words. 
TG_REACTION_CALLS=["киберникто","государь"]
# Allows /system_message command to be run by masters
TG_ADMIN_COMMANDS_ALLOWED=true
# Set this group ID with your bot added, to log all user messages to this service group
TG_SERVICE_GROUP_ID=-XXXXXXXXXX  
# sometimes Kibernikto sends stickers for fun together with his answers  
TG_STICKER_LIST=["CAACAgIAAxkBAAEKqsplQ8BRyPbGj_B_K4ujCLsDAe-l7wAC8AIAAs-71A7mCrGe-zzi0DME","CAACAgIAAxkBAAEIgoxkMaHv1maOeEne8CYAAY5s4kJ1e4wAAo4JAAIItxkCXSMuZ6bo59gvBA"]
```

**run cmd**

```shell
kibernikto --env_file_path=/path/to/your/env/local.env
```

**run code**  
*(assuming you set the environment yrself)*

- Install the requirements   
  `pip install -r requirements.txt`
- Run `main.py` file using the environment provided.

# plugins:

In general, you can use one Ai provider API for all available Kibernikto actions, in that case all the AI related
variables values will be the same.  
However it is strongly recommended to use cheaper models for summarization tasks.

- **WeblinkSummaryPlugin and YoutubePlugin**

```dotenv
# If no key is provided, youtube videos and webpages will be ignored.
SUMMARIZATION_OPENAI_API_KEY=yr-key
SUMMARIZATION_OPENAI_API_BASE_URL=https://api.openai.com/v1  
SUMMARIZATION_OPENAI_API_MODEL=gpt-4-turbo-preview
```

- **ImageSummaryPlugin to process images.**

```dotenv
# If no key is provided, images will not be processed.
IMAGE_SUMMARIZATION_OPENAI_API_KEY=yr-key
IMAGE_SUMMARIZATION_OPENAI_API_MODEL=gpt-4-vision-preview
IMAGE_SUMMARIZATION_OPENAI_API_BASE_URL=https://api.openai.com/v1

# You can get your key here: https://imgbb.com. If you do no set up this variable, default one will be used.  
# This is needed to store images send to the bot.  
IMAGE_STORAGE_API_KEY = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

- **Voice messages** processing using **OpenAI**:

```dotenv
# If no key is provided, voice messages will not be processed.
VOICE_PROCESSOR=openai
VOICE_OPENAI_API_KEY=yr-key
VOICE_OPENAI_API_MODEL=whisper-1
VOICE_OPENAI_API_BASE_URL=https://api.openai.com/v1
VOICE_FILE_LOCATION=/tmp
```

- **Voice messages** processing using [gladia.io](https://gladia.io):  
  **Gladia** Audio Intelligence API, is designed to enable any company to easily
  embed top-quality Audio AI into their applications, whatever the tech stack.

As whisper api is limited to 25 megs, [gladia.io](https://glaudia.io) helps to process bigger files.

Kibernikto treats voice messages with duration less than `VOICE_MIN_COMPLEX_SECONDS` as usual AI interaction ones.
For longer durations Kibernikto will return detailed audio
analysis including summary etc.

Perfect solution for analyzing interviews and meeting.  
Gladia price policies are also very affordable.

```dotenv
VOICE_PROCESSOR=gladia
VOICE_GLADIA_API_KEY=yr-gladia-key
VOICE_GLADIA_SUMMARIZATION_TYPE=concise
VOICE_MIN_COMPLEX_SECONDS=300
```    

- **Smart voice messages** processing using both [gladia.io](https://gladia.io) and OpenAI:

Whisper api is a bit faster and looks better to use just for talking with your bot.

```dotenv
VOICE_PROCESSOR=auto

VOICE_OPENAI_API_KEY=yr-key
VOICE_OPENAI_API_MODEL=whisper-1
VOICE_OPENAI_API_BASE_URL=https://api.openai.com/v1
VOICE_FILE_LOCATION=/tmp

#starting this audio length Kibernikto will start using Gladia and deeper analysis
VOICE_MIN_COMPLEX_SECONDS=300
VOICE_GLADIA_API_KEY=yr-gladia-key
VOICE_GLADIA_SUMMARIZATION_TYPE=concise
VOICE_GLADIA_CONTEXT=We have before us an interview for the position of office manager
```

For the full list of variables, see `env_examples` folder.

# useful links

To create and operate your bot: https://t.me/BotFather  
To obtain group/user ids etc: https://t.me/getidsbot  
To obtain sticker ids: https://t.me/idstickerbot  
To get familiar with basic OpenAI principles: https://openai.com  
Basics on Gpt-4 vision: https://gptpluginz.com/gpt-4-vision-api  
To find out more on models and multi-model api details: https://vsegpt.ru/Docs/Models  
Audio analysis: https://gladia.io  
Website to text and other helpful tools https://toolsyep.com  
Free image hosting: https://imgbb.com

# code details

*(ignore it if dont plan to create yr own plugins or Kibernikto bots using Kibernikto as a library)*

You can write yr own bots extending `TelegramBot` class from `kibernikto.telegram` package.  
See `bots` package for more details.

You can use `OpenAIExecutor` directly to create non-telegram ai-connected bots.
For example:

```python
from kibernikto.interactors import OpenAIExecutor, OpenAiExecutorConfig


class AnyBot(OpenAIExecutor):
    def __init__(self, config: OpenAiExecutorConfig, master_id, username):
        self.master_id = master_id
        self.username = username
        super().__init__(config=config)

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        return parent_should or self.username in message_text

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id
```

Plugins are entities that pre-process user input text before sending it to ai. Currently 3 plugins are available (
see `plugins` package):

- ImageSummaryPlugin (`IMAGE_SUMMARIZATION_` env prefix)
- YoutubePlugin (`SUMMARIZATION_` env prefix)
- WeblinkSummaryPlugin (`SUMMARIZATION_` env prefix)

Each plugin overrides the `applicable` method from superclass, i.e.:

```python
class YoutubePluginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUMMARIZATION_')

    OPENAI_API_MODEL: str = "gpt-4-turbo-preview"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_MAX_TOKENS: int = 800
    VIDEO_MESSAGE: str = _DEFAULT_TEXT


DEFAULT_SETTINGS = YoutubePluginSettings()


class YoutubePlugin(KiberniktoPlugin):
    index = 0

    @staticmethod
    def applicable():
        return DEFAULT_SETTINGS.OPENAI_API_KEY is not None

    ...
```

# FAQ

- How do I run Kibernikto Instance from my code?

```python
# import bot
from kibernikto.bots.cybernoone import Kibernikto

bot_class = Kibernikto

from kibernikto.telegram import comprehensive_dispatcher
from kibernikto.telegram import commands
from kibernikto.telegram import service

comprehensive_dispatcher.start(bot_class=bot_class)
```

You can create your own bots and dispatchers and use it like above.

- I want to run an ai bot without your telegram dispatcher!

```python
from kibernikto.interactors import OpenAiExecutorConfig

executor_config = OpenAiExecutorConfig(name="Kibernikto",
                                       reaction_calls=["Hello", "Kiberman"], model="gpt-4")

your_bot = Kibernikto(username="kiberniktomiks",
                      master_id="some_master_user_id_or_any",
                      config=executor_config)
```

Now you can use your_bot `heed_and_reply` method.
Please note that in this case you will have to apply the plugins yourself.

- I want to know how to make Kibernikto use my tools! Please!
  Implemented, pls wait for the docs to be updated. For now look at
  the [planner](https://github.com/solovieff/kibernikto-planner) example.
