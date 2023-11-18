import logging
import os
import re
from urllib.parse import urlparse

from openai.types.chat import ChatCompletion
from pydantic import HttpUrl

from kibernikto.constants import OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE
from ._kibernikto_plugin import KiberniktoPlugin


class ImageSummaryPlugin(KiberniktoPlugin):
    """
    This plugin is used to get information about the given image.
    """

    def __init__(self, model: str, base_url: str, api_key: str, summarization_request: str):
        super().__init__(model=model, base_url=base_url, api_key=api_key, post_process_reply=False, store_reply=True,
                         base_message=summarization_request)

    async def run_for_message(self, message: str):
        try:
            result = await self._run(message)
            return result
        except Exception as error:
            logging.error(f'failed to get webpage transcript from {message}: {str(error)}', )
            return None

    async def _run(self, message: str):
        web_link, text = _extract_image_link(message)

        if web_link is None:
            return None

        logging.info(f"found image link: {web_link}")

        try:
            summary = await self.get_ai_text_summary(web_link, text)
            return f"{summary}"
        except Exception as error:
            logging.warning(f'failed to get ai text summary: {str(error)}', )
            # summary = _get_sber_text_summary(transcript)
            # summary = str(error)
            return None

    async def get_ai_text_summary(self, image_link: HttpUrl, image_text: str):
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
                                                                                     max_tokens=OPENAI_MAX_TOKENS,
                                                                                     temperature=OPENAI_TEMPERATURE)
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
