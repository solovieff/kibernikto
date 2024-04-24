# kibernikto

Kibernikto is an app/lib to easily run telegram bots connected to AI models with additional features.  
Kibernikto bots can be easily extended to be used outside telegram.  
Core and bots can be used as a core libs for creating ai-bot based apps.  

- ✍️ telegram conversations with different AIs in groups or privately (including hidden second-level AI-redactors)
- 🔉 voice messages recognition
- 👂 interviews and meetings (up to 2 hours) analysis right in Telegram using Gladia.io 
- 🎞 youtube video summarization
- 🔗 webpage summarization
- 📸 image recognition
- 🫡 openai function tools easy [integration](https://github.com/solovieff/kibernikto-planner). No more pain. ~~(anthropic xml format supported, too! looks like they changed it again)~~

Given an image Kibernikto will publish it to a free image hosting service and then process as a link.

By default `single_group_dispatcher` is used with a following rules:

- One Kibernikto instance **can privately talk only to one** (`TG_MASTER_ID`) user and work with **one group chat
  ** (`TG_FRIEND_GROUP_ID`).

If you want your bot to be able to work with **any user or group**, use `comprehensive_dispatcher`. You will need the
following `additional` env parameters if you want to restrict user/group ids.
Do not add it to your env if you want anyone
to
be able to use yr Kibernikto instance:

```dotenv
TG_MASTER_IDS=[XXXXXXXXX]
TG_FRIEND_GROUP_IDS=[-XXXXXXXXX]
```

or

``kibernikto --env_file_path=local.env --bot_type=kibernikto --dispatcher=multiuser``

Kibernikto can post-process messages returned by one AI using another AI (for now it's a hardcoded 2 step chain).

# install from pip

``pip install kibernikto``

# how to run

- Create telegram bot using @BotFather and obtain it's key. You can also change the picture and other details there. Set
  env `TG_BOT_KEY`.

  Turn off Group Privacy for your bot to be able to react to group messages:

  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/9f2ec25d-bde4-4eec-9ec6-65741101ce8d">  
  <br>
  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/bf1ac575-ad1a-464c-8535-2cf7f5ebb162">  

- Add your bot to the group you want. Set env `TG_FRIEND_GROUP_ID`. You can get the group ID using @getidsbot in
  telegram.
- Configure other env variables.

**run cmd**   
*(assuming local.env file is located in the same folder)*

``kibernikto --env_file_path=local.env``

**run code**  
*(assuming you set the environment yrself)*

- Install the requirements   
  `pip install -r requirements.txt`
- Run `main.py` file using the environment provided.

# environment:

First of all, full examples are in the [examples](/env_examples/) folder.

In general, you can use one Ai provider API for all available Kibernikto actions, in that case all the AI related
variables values will be the same.  
However it is strongly recommended to use cheaper models for summarization tasks.

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

Other AI behaviour options:

```dotenv
OPENAI_MAX_TOKENS=800  
OPENAI_WHO_AM_I=Answer all questions as {0}, the majestic lord of the universes with all the knowledge of our small planet.  
```

**Telegram**

```dotenv
# Telegram configuration
TG_BOT_KEY=XXXXXXXXXX:XXXxxxXXXxxxxXXXxxx  
TG_BOT_MAX_HISTORY=8  
TG_FRIEND_GROUP_ID=-XXXXXXXXXX  
# Your telegram ID. For example 122349243. Forward your message to @idstickerbot to get it.  
TG_MASTER_ID=XXXXXXXXX
# Kibernikto reacts to direct replies or when sees the following words. 
# Preserving pydantic-settings list format.  
TG_REACTION_CALLS=["киберникто","государь"]  
# sometimes Kibernikto sends stickers for fun together with his answers  
TG_STICKER_LIST=["CAACAgIAAxkBAAEKqsplQ8BRyPbGj_B_K4ujCLsDAe-l7wAC8AIAAs-71A7mCrGe-zzi0DME","CAACAgIAAxkBAAEIgoxkMaHv1maOeEne8CYAAY5s4kJ1e4wAAo4JAAIItxkCXSMuZ6bo59gvBA"]
```


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
VOICE_PROCESSOR=**auto**

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

# redactor mode

To run Kibernikto with additional redactor for each response change the `bot_type` to "vertihvostka":    
``kibernikto --env_file_path=local.env --bot_type=vertihvostka``  
And set the following env variables for a redactor network.

```dotenv
REDACTOR_OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
REDACTOR_OPENAI_BASE_URL=https://api.openai.com/v1
REDACTOR_OPENAI_API_MODEL=gpt-4-turbo-preview
#REDACTOR_OPENAI_WHO_AM_I=""
REDACTOR_MESSAGE="
    Replace several words in the text with their feminine equivalents; do not change the other words. In your response, return only the result without your comments:\n{message}
"
```

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
    # choose your bot
if args.bot_type == 'kibernikto':
    from kibernikto.bots.cybernoone import Kibernikto

    bot_class = Kibernikto
elif args.bot_type == 'vertihvostka':
    from kibernikto.bots.vertihvostka import Vertihvostka

    bot_class = Vertihvostka
else:
    raise RuntimeError("Wrong bot_type, should be in ('kibernikto','vertihvostka')")

# choose dispatcher type
if args.dispatcher == 'default':
    from kibernikto.telegram import single_group_dispatcher

    single_group_dispatcher.start(bot_class=bot_class)
elif args.dispatcher == 'multiuser':
    from kibernikto.telegram import comprehensive_dispatcher

    comprehensive_dispatcher.start(bot_class=bot_class)
else:
    raise RuntimeError("Wrong dispatcher!")
```

You can create your own bots and dispatchers and use it live above.

- I want to run an ai bot without your telegram dispatcher!

```python
from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.utils.text import split_text_by_sentences

executor_config = OpenAiExecutorConfig(name="Kibernikto",
                                       reaction_calls=["Hello", "Kiberman"])

your_bot = Kibernikto(username="kiberniktomiks",
                      master_id="some_master_user_id_or_any",
                      config=executor_config)
```

Now you can use your_bot `heed_and_reply` method.
Please note that in this case you will have to apply the plugins yourself. 

- I want to know how to make Kibernikto use my tools! Please!
Implemented, pls wait for the docs to be updated.
