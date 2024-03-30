import logging
import os
import re
from urllib.parse import urlparse

from openai import PermissionDeniedError
from openai.types.chat import ChatCompletion
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._kibernikto_plugin import KiberniktoPlugin, KiberniktoPluginException

_DEFAULT_TEXT = "What is displayed in the image?"


class ImagePluginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='IMAGE_SUMMARIZATION_')
    OPENAI_API_MODEL: str = "vis-anthropic/claude-3-sonnet"
    OPENAI_BASE_URL: str = "https://api.vsegpt.ru:6070/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_MAX_TOKENS: int = 800
    MESSAGE: str = _DEFAULT_TEXT


DEFAULT_SETTINGS = ImagePluginSettings()


class ImageSummaryPlugin(KiberniktoPlugin):
    index = 100
    """
    This plugin is used to get information about the given image.
    """

    @staticmethod
    def applicable():
        return DEFAULT_SETTINGS.OPENAI_API_KEY is not None

    def __init__(self):
        super().__init__(model=DEFAULT_SETTINGS.OPENAI_API_MODEL, base_url=DEFAULT_SETTINGS.OPENAI_BASE_URL,
                         api_key=DEFAULT_SETTINGS.OPENAI_API_KEY, post_process_reply=False, store_reply=True,
                         base_message=DEFAULT_SETTINGS.MESSAGE)

    async def run_for_message(self, message: str):
        try:
            result = await self._run(message)
            return result
        except PermissionDeniedError as pde:
            logging.error(f'PermissionDeniedError while getting image description from {message}: {pde}', )
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__,
                                            error_message=str("Failed to process the image! I am terribly sorry :("))
        except Exception as error:
            logging.error(f'failed to get image description from {message}: {str(error)}', )
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__, error_message=str(error))

    async def _run(self, message: str):
        web_link, text = _extract_image_link(message)

        if web_link is None:
            return None

        logging.info(f"found image link: {web_link}")

        summary = await self.get_image_description(web_link, text)
        return f"{summary}"

    async def get_image_description(self, image_link: str, image_text: str):
        text = image_text if image_text else self.base_message
        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": image_link
                }
            ]
        }

        completion: ChatCompletion = await self.client_async.chat.completions.create(model=self.model,
                                                                                     messages=[message],
                                                                                     max_tokens=DEFAULT_SETTINGS.OPENAI_MAX_TOKENS,
                                                                                     temperature=DEFAULT_SETTINGS.OPENAI_TEMPERATURE)
        response_text = completion.choices[0].message.content.strip()
        logging.info(response_text)
        return response_text


def _is_image(url):
    parsed = urlparse(url)
    path = parsed.path

    # Get the file extension from the path
    ext = os.path.splitext(path)[1].lower()

    # Check if the extension is a known image type
    return ext in ['.jpg', '.jpeg', '.png', '.gif']


def _extract_image_link(message):
    link_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'

    match = re.search(link_regex, message)
    if match:
        link = match.group()

        if _is_image(link):
            other_text = message.replace(link, "").strip()
            return link, other_text

    return None, None
