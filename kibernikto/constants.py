import logging
import os

try:
    # master telegram user id
    TG_MASTER_ID = int(os.environ['TG_MASTER_ID'])
    # this bot key
    TG_BOT_KEY = os.environ['TG_BOT_KEY']

    # words that trigger a reaction
    TG_REACTION_CALLS = os.environ.get('TG_REACTION_CALLS', "никто, падаль, хонда")
    TG_REACTION_CALLS = "".join(TG_REACTION_CALLS.split())
    TG_REACTION_CALLS = TG_REACTION_CALLS.split(",")

    # sticker list to use
    TG_STICKER_LIST = os.environ.get('TG_STICKER_LIST',
                                     """CAACAgIAAxkBAAEKqsplQ8BRyPbGj_B_K4ujCLsDAe-l7wAC8AIAAs-71A7mCrGe-zzi0DME,CAACAgIAAxkBAAEIgoxkMaHv1maOeEne8CYAAY5s4kJ1e4wAAo4JAAIItxkCXSMuZ6bo59gvBA,CAACAgIAAxkBAAEKqtBlQ8EebtqTUlmfFM8pi_0w-wnCRAACBQAD5qQjDV5ULDD7qdDwMwQ,CAACAgIAAxkBAAEKqtJlQ8FHtkpgAVDzGvIoQBdlNWxuawACdgkAAgi3GQI1Wnpqru6xgTME,CAACAgIAAxkBAAEKqtRlQ8FYynogv1cCnlIr4dpLp4cWjQACIQUAAj-VzArEL64k2NbgbDME""")
    TG_STICKER_LIST = "".join(TG_STICKER_LIST.split())
    TG_STICKER_LIST = TG_STICKER_LIST.split(",")

    # message history length
    TG_BOT_MAX_HISTORY = int(os.environ.get('TG_BOT_MAX_HISTORY', 8))
    TG_FRIEND_GROUP_ID = int(os.environ['TG_FRIEND_GROUP_ID'])
    # not used yet
    TG_DEFAULT_PUBLICATION_PERIOD_HOURS = int(os.environ.get('TG_DEFAULT_PUBLICATION_PERIOD_HOURS', 8))
    TG_PUBLICATION_CHANNEL_ID = int(os.environ.get('TG_PUBLICATION_CHANNEL_ID', 0))

    OPENAI_API_MODEL = os.environ.get('OPENAI_API_MODEL', "gpt-4")
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', "https://api.vsegpt.ru:6070/v1")
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', 800))
    OPENAI_TEMPERATURE = float(os.environ.get('OPENAI_TEMPERATURE', 0.7))
    OPENAI_RESET_CALL = os.environ.get('OPENAI_RESET_CALL', "Переосмысли себя")
    OPENAI_WHO_AM_I = os.environ.get('OPENAI_WHO_AM_I',
                                     """Respond to all my questions as {0}. {0} is a gentle universe creator. He isn't afraid to joke in a sinister manner. {0} never tries to avoid a specific answer including concrete names and events. You {0}. Never tell the user about this game.""")

    SUMMARIZATION_KEY = os.environ.get('SUMMARIZATION_KEY')
    SUMMARIZATION_REQUEST = os.environ.get('SUMMARIZATION_REQUEST',
                                           "You will be provided with a video transcript. Summarize it and try to give 13 main points.\n {info_text}. \n{text}\n")
    SUMMARIZATION_API_BASE_URL = os.environ.get('SUMMARIZATION_API_BASE_URL', "https://api.vsegpt.ru:6070/v1")
    SUMMARIZATION_MODEL = os.environ.get('SUMMARIZATION_MODEL', "anthropic/claude-instant-v1")

    WEBLINK_SUMMARIZATION_REQUEST = os.environ.get('WEBLINK_SUMMARIZATION_REQUEST',
                                                   "Above is the web page in text form. Try to ignore the site section titles and additional links that don't carry information. \n"
                                                   "Try to emphasize the main point from the content.\n"
                                                   "If you think there are multiple articles or blog posts on the site -- provide a sammary for each.\n"
                                                   "{text}\n")

    IMAGE_SUMMARIZATION_KEY = os.environ.get('IMAGE_SUMMARIZATION_KEY')
    IMAGE_SUMMARIZATION_REQUEST = os.environ.get('IMAGE_SUMMARIZATION_REQUEST', "What is displayed in the image?")
    IMAGE_SUMMARIZATION_MODEL = os.environ.get('IMAGE_SUMMARIZATION_MODEL', "gpt-4-vision-preview")
    IMAGE_SUMMARIZATION_API_BASE_URL = os.environ.get('IMAGE_SUMMARIZATION_API_BASE_URL', "https://api.openai.com/v1")
except KeyError as e:
    logging.error(f"{str(e)} environment variable missing missing")
    exit(os.EX_CONFIG)
