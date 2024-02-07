import os

TG_CHANNEL_ID = int(os.environ.get('TG_CHANNEL_ID', 0))
TG_CHANNEL_POLITICS = os.environ.get('TG_CHANNEL_POLITICS', '0') in ('1', 'true', 'True', 'yes', 'Yes')

TG_CHANNEL_PUBLICATION_PERIOD_MINUTES = int(os.environ.get('TG_CHANNEL_PUBLICATION_PERIOD_MINUTES', 13))
TG_CHANNEL_NEWS_UPDATE_PERIOD_MINUTES = int(os.environ.get('TG_CHANNEL_NEWS_UPDATE_PERIOD_MINUTES', 60))
TG_CHANNEL_API_KEY = os.environ['TG_CHANNEL_API_KEY']
TG_CHANNEL_API_BASE_URL = os.environ.get('TG_CHANNEL_API_BASE_URL', "https://api.vsegpt.ru:6070/v1")
TG_CHANNEL_API_MODEL = os.environ.get('TG_CHANNEL_API_MODEL', "google/gemini-pro")

TG_CHANNEL_INTERESTS = os.environ.get('TG_CHANNEL_INTERESTS', 'fashion, lifestyle')
TG_CHANNEL_INTERESTS = "".join(TG_CHANNEL_INTERESTS.split())
TG_CHANNEL_INTERESTS = TG_CHANNEL_INTERESTS.split(",")
