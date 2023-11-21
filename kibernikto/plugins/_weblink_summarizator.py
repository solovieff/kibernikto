import logging
import re

from kibernikto.plugins._img_summarizator import _is_image
from openai.types.chat import ChatCompletion

from kibernikto.constants import OPENAI_MAX_TOKENS
from kibernikto.utils.text import get_website_as_text
from ._kibernikto_plugin import KiberniktoPlugin


class WeblinkSummaryPlugin(KiberniktoPlugin):
    """
    This plugin is used to get video transcript and then get text summary from it.
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
        web_link = _extract_link(message)

        if web_link is None:
            return None

        if _is_image(web_link):
            return None
        logging.info(f"found web link: {web_link}", )
        transcript = None

        try:
            transcript = await get_website_as_text(web_link)
        except Exception as error:
            logging.error(f"{error}")
            return None

        if transcript is None:
            return None

        try:
            summary = await self.get_ai_text_summary(transcript)
            return f"{summary}"
        except Exception as error:
            logging.warning(f'failed to get ai text summary: {str(error)}', )
            # summary = _get_sber_text_summary(transcript)
            # summary = str(error)
            return None

    async def get_ai_text_summary(self, transcript):
        content_to_summarize = self.base_message.format(text=transcript)
        message = {
            "role": "user",
            "content": content_to_summarize
        }

        completion: ChatCompletion = await self.client_async.chat.completions.create(model=self.model,
                                                                                     messages=[message],
                                                                                     max_tokens=OPENAI_MAX_TOKENS,
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
        return link

    return None
