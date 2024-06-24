import logging
import re

from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.plugins._img_summarizator import _is_image
from openai.types.chat import ChatCompletion

from kibernikto.utils.text import get_website_as_text, get_website_html
from ._kibernikto_plugin import KiberniktoPlugin, KiberniktoPluginException

_DEFAULT_TEXT = """Above is the web page in text form. Try to ignore the site section titles and additional links that don't carry information. \n"
"Try to emphasize the main point from the content.\n"
"If you think there are multiple articles or blog posts on the site -- provide a sammary for each.\n"
"{text}\n"""


class WeblinkPluginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUMMARIZATION_')
    OPENAI_API_MODEL: str = "anthropic/claude-instant-v1"
    OPENAI_BASE_URL: str = "https://api.vsegpt.ru:6070/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_MAX_TOKENS: int = 800
    WEBLINK_MESSAGE: str = _DEFAULT_TEXT
    WEBLINK_ENABLED: bool = True


DEFAULT_SETTINGS = WeblinkPluginSettings()


class WeblinkSummaryPlugin(KiberniktoPlugin):
    index = 10000
    """
    This plugin is used to get weblink transcript and then get text summary from it.
    It uses toolsyep to get text repr of the website
    """

    @staticmethod
    def applicable():
        return DEFAULT_SETTINGS.OPENAI_API_KEY is not None and DEFAULT_SETTINGS.WEBLINK_ENABLED is True

    def __init__(self, model: str = DEFAULT_SETTINGS.OPENAI_API_MODEL, base_url: str = DEFAULT_SETTINGS.OPENAI_BASE_URL,
                 api_key: str = DEFAULT_SETTINGS.OPENAI_API_KEY,
                 summarization_request: str = DEFAULT_SETTINGS.WEBLINK_MESSAGE):
        if DEFAULT_SETTINGS.OPENAI_API_KEY:
            super().__init__(model=model,
                             base_url=base_url,
                             api_key=api_key,
                             base_message=summarization_request,
                             post_process_reply=False, store_reply=True,
                             )
        else:
            raise EnvironmentError("No SUMMARIZATION_OPENAI_API_KEY provided!")

    async def run_for_message(self, message: str):
        try:
            result = await self._run(message)
            return result
        except Exception as error:
            logging.error(f'failed to get webpage data from {message}: {str(error)}', )
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__,
                                            error_message='failed to get webpage data')

    async def _run(self, message: str):
        web_link, other_text = _extract_link(message)

        if web_link is None:
            return None

        if _is_image(web_link):
            return None
        logging.info(f"found web link: {web_link}", )

        # transcript = await get_website_html(web_link)
        transcript = await get_website_as_text(web_link)

        if 'Error 404' in transcript or transcript is None:
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__,
                                            error_message="Failed to load web link!")

        summary = await self.get_ai_text_summary(transcript, other_text)
        return f"{summary}"

    async def get_ai_text_summary(self, transcript, user_text=""):
        content_to_summarize = self.base_message.format(text=transcript)
        if user_text:
            content_to_summarize += f"\n{user_text}"
        message = {
            "role": "user",
            "content": content_to_summarize
        }

        completion: ChatCompletion = await self.client_async.chat.completions.create(model=self.model,
                                                                                     messages=[message],
                                                                                     max_tokens=DEFAULT_SETTINGS.OPENAI_MAX_TOKENS,
                                                                                     temperature=0.8,
                                                                                     )
        response_text = completion.choices[0].message.content.strip()
        logging.info(response_text)
        return response_text


def _extract_link(message):
    link_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'

    match = re.search(link_regex, message)
    if match:
        link = match.group()

        other_text = message.replace(link, "").strip()

        return link, other_text

    return None, None
