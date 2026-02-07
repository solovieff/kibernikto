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