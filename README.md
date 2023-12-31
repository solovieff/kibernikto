# kibernikto

Kibernikto is the app to easily run telegram bots connected to AI models.

Having a link, Kibernikto based bots can summarize most of

- youtube videos
- webpages
- images

Given an image Kibernikto will publish it to a free image hosting service and then process as a link.

One Kibernikto instance can be connected to one Telegram bot and work with one group chat. Privately it talks to master
only and denies other users.

Kibernikto can be added to any group chat (`TG_FRIEND_GROUP_ID`). The bot will need chat messages access set in group to
operate.
Private chat is only available for one master user (`TG_MASTER_ID`).

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
``kibernikto --env_file_path local.env``

**run code**

- Install the requirements `pip install -r requirements.txt`
- Run `main.py` file using the environment provided.

# environment:

In general, you can use one Ai provider API for all available Kibernikto actions, in that case all the AI related
variables values will be the same.  
However it is strongly recommended to use cheaper models for summarization tasks.

- Default [OpenAI](https://openai.com)

```
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODEL=gpt-4
OPENAI_API_KEY=yr-key  
```

- Multimodel [vsegpt.ru](https://vsegpt.ru/)

```
OPENAI_BASE_URL=https://api.vsegpt.ru:6070/v1  
OPENAI_API_KEY=sk-yr-key  
OPENAI_API_MODEL=openai/gpt-4  
```

```
OPENAI_MAX_TOKENS=800  
OPENAI_WHO_AM_I=Answer all questions as {0} named Киберникто, the majestic lord of the universes with all the knowledge of our small planet.  

# Youtube videos and webpages summaries
# If no key is provided, youtube videos and webpages will be ignored.
SUMMARIZATION_KEY=sk-yr-key
SUMMARIZATION_API_BASE_URL=https://api.vsegpt.ru:6070/v1  
SUMMARIZATION_MODEL=anthropic/claude-instant-v1

# image analysis. works only with gpt-4-vision-preview and direct openai for now  
IMAGE_SUMMARIZATION_KEY=yr-key
IMAGE_SUMMARIZATION_MODEL=gpt-4-vision-preview
IMAGE_SUMMARIZATION_API_BASE_URL=https://api.openai.com/v1

# You can get your key here: https://imgbb.com. If you do no set up this variable, default one will be used.  
# This is needed to store images send to the bot.  
IMAGE_STORAGE_API_KEY = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

# Telegram configuration
TG_BOT_KEY=XXXXXXXXXX:XXXxxxXXXxxxxXXXxxx  
TG_BOT_MAX_HISTORY=8  
TG_FRIEND_GROUP_ID=-XXXXXXXXXX  
# Your telegram ID. For example 122349245. Forward your message to @idstickerbot to get it.  
TG_MASTER_ID=XXXXXXXXX
# Kibernikto reacts to direct replies or when sees the following words  
TG_REACTION_CALLS=киберникто,государь  
# sometimes Kibernikto sends stickers for fun together with his answers  
TG_STICKER_LIST=CAACAgIAAxkBAAEKqsplQ8BRyPbGj_B_K4ujCLsDAe-l7wAC8AIAAs-71A7mCrGe-zzi0DME,CAACAgIAAxkBAAEIgoxkMaHv1maOeEne8CYAAY5s4kJ1e4wAAo4JAAIItxkCXSMuZ6bo59gvBA
```

For the full list of variables, see `constants.py` file.

# useful links

To create and operate your bot: https://t.me/BotFather  
To obtain group/user ids etc: https://t.me/getidsbot  
To obtain sticker ids: https://t.me/idstickerbot  
To get familiar with basic OpenAI principles: https://openai.com  
Basics on Gpt-4 vision: https://gptpluginz.com/gpt-4-vision-api  
To find out more on models and multi-model api details: https://vsegpt.ru/Docs/Models  
Website to text and other helpful tools https://toolsyep.com  
Free image hosting: https://imgbb.com  
