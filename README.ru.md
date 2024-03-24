# kibernikto

Kibernikto - это библиотека для быстрого запуска ботов в Telegram, связанных с моделями искусственного интеллекта.

Имея ссылку, боты на базе Kibernikto могут обобщать большинство

- видеороликов youtube
- веб-страниц
- изображений

Получив изображение, Kibernikto опубликует его на бесплатном хостинге изображений, а затем обработает как ссылку.  
Kibernikto может постобработать сообщения, возвращенные одним ИИ, с помощью другого ИИ (пока это жестко закодированная
двухшаговая цепочка).

По умолчанию используется `single_group_dispatcher` со следующими правилами:

- Один экземпляр Kibernikto может быть подключен к одному боту Telegram и работать с одним групповым чатом. Приватно он
  общается только с master user (это вы).
  и отвечает остальным пользователям отказом общаться.
- Kibernikto может быть добавлен в любой групповой чат (`TG_FRIEND_GROUP_ID`). Бот должен иметь доступ к сообщениям
  чата, установленный в группе чтобы работать.
- Приватный чат доступен только для одного главного пользователя (`TG_MASTER_ID`).

# install from pip

``pip install kibernikto``

# how to run

- Создайте телеграм-бота с помощью @BotFather и получите его ключ. Там же можно изменить картинку и другие детали.
  Установите
  env `TG_BOT_KEY`.

  Чтобы бот мог реагировать на групповые сообщения, отключите Group Privacy:
  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/9f2ec25d-bde4-4eec-9ec6-65741101ce8d">  
  <br>
  <img width="383" alt="image" src="https://github.com/solovieff/kibernikto/assets/5033247/bf1ac575-ad1a-464c-8535-2cf7f5ebb162">
- Добавьте своего бота в нужную вам группу. Установите параметр env `TG_FRIEND_GROUP_ID`. Вы можете получить
  идентификатор группы, используя @getidsbot в telegram.
- Настройте другие переменные env.

**run cmd**   
*(если предположить, что файл local.env находится в той же папке)*

``kibernikto --env_file_path local.env``

**run code**  
*(при условии, что вы сами устанавливаете переменные окружения)*

- Install the requirements   
  `pip install -r requirements.txt`
- Run `main.py` file using the environment provided.

# environment:

Примеры в папке [examples](/env_examples/).

В целом, вы можете использовать один API Ai провайдера для всех доступных действий Kibernikto, в этом случае все
связанные с AI
переменные будут иметь почти одинаковые значения.  
Однако для задач суммаризации настоятельно рекомендуется использовать более дешевые модели.

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

Настройки бота:

```dotenv
OPENAI_MAX_TOKENS=800  
OPENAI_WHO_AM_I=Answer all questions as {0}, the majestic lord of the universes with all the knowledge of our small planet.  
```

WeblinkSummaryPlugin and YoutubePlugin чтобы работать со ссылками.

```dotenv
# If no key is provided, youtube videos and webpages will be ignored.
SUMMARIZATION_OPENAI_API_KEY=sk-yr-key
SUMMARIZATION_OPENAI_API_BASE_URL=https://api.vsegpt.ru:6070/v1  
SUMMARIZATION_OPENAI_API_MODEL=anthropic/claude-instant-v1
```

ImageSummaryPlugin для работы с изображениями.

```dotenv
# If no key is provided, images will not be processed.
IMAGE_SUMMARIZATION_OPENAI_API_KEY=yr-key
IMAGE_SUMMARIZATION_OPENAI_API_MODEL=gpt-4-vision-preview
IMAGE_SUMMARIZATION_OPENAI_API_BASE_URL=https://api.openai.com/v1

# You can get your key here: https://imgbb.com. If you do no set up this variable, default one will be used.  
# This is needed to store images send to the bot.  
IMAGE_STORAGE_API_KEY = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

Telegram

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

For the full list of variables, see `env_examples` folder.
# redactor mode
Чтобы запустить Kibernikto с дополнительным редактором для каждого ответа, измените `bot_type` на "vertihvostka":    
``kibernikto --env_file_path=local.env --bot_type=vertihvostka``    
И установите следующие переменные env для сети редакторов.

```dotenv
REDACTOR_OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
REDACTOR_OPENAI_BASE_URL=https://api.openai.com/v1
REDACTOR_OPENAI_API_MODEL=gpt-4
#REDACTOR_OPENAI_WHO_AM_I=""
REDACTOR_MESSAGE="
    Замените несколько слов в тексте на их женские эквиваленты; остальные слова не меняйте. В своем ответе верните только результат без комментариев:\n{message}
"
```

# useful links

To create and operate your bot: https://t.me/BotFather  
To obtain group/user ids etc: https://t.me/getidsbot  
To obtain sticker ids: https://t.me/idstickerbot  
To get familiar with basic OpenAI principles: https://openai.com  
Basics on Gpt-4 vision: https://gptpluginz.com/gpt-4-vision-api  
To find out more on models and multi-model api details: https://vsegpt.ru/Docs/Models  
Website to text and other helpful tools https://toolsyep.com  
Free image hosting: https://imgbb.com

# code details

*(Игнорируйте его, если не планируете создавать собственные плагины или боты Kibernikto, используя Kibernikto как
библиотеку)*

Вы можете написать собственных ботов, расширяющих класс `TelegramBot` из пакета `kibernikto.telegram`.  
Более подробную информацию смотрите в пакете `bots`.

Плагины - это сущности, которые предварительно обрабатывают вводимый пользователем текст перед отправкой его AI. В
настоящее время доступны 3 плагина (см.
см. пакет `plugins`):

- ImageSummaryPlugin (префикс env `IMAGE_SUMMARIZATION_`)
- YoutubePlugin (префикс env  `SUMMARIZATION_`)
- WeblinkSummaryPlugin (префикс env `SUMMARIZATION_`)

Каждый плагин переопределяет метод `applicable` из суперкласса и имеет свои Settings, т.е:

```python
class YoutubePluginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUMMARIZATION_')

    OPENAI_API_MODEL: str = "anthropic/claude-instant-v1"
    OPENAI_BASE_URL: str = "https://api.vsegpt.ru:6070/v1"
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

