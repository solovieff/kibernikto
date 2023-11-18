import logging
import typing

from aiogram.client.session import aiohttp
from pydantic import HttpUrl

MAX_MESSAGE_LENGTH = 4096


def split_text(text: str, length: int = MAX_MESSAGE_LENGTH) -> typing.List[str]:
    """
    Split long text

    :param text:
    :param length:
    :return: list of parts
    :rtype: :obj:`typing.List[str]`
    """
    return [text[i:i + length] for i in range(0, len(text), length)]


def safe_split_text(text: str, length: int = MAX_MESSAGE_LENGTH, split_separator: str = ' ') -> typing.List[str]:
    """
    Split long text

    :param text:
    :param length:
    :param split_separator
    :return:
    """
    # TODO: More informative description

    temp_text = text
    parts = []
    while temp_text:
        if len(temp_text) > length:
            try:
                split_pos = temp_text[:length].rindex(split_separator)
            except ValueError:
                split_pos = length
            if split_pos < length // 4 * 3:
                split_pos = length
            parts.append(temp_text[:split_pos])
            temp_text = temp_text[split_pos:].lstrip()
        else:
            parts.append(temp_text)
            break
    return parts


async def get_website_as_text(url: HttpUrl):
    to_reader_url = "https://toolsyep.com/en/webpage-to-plain-text/"
    async with aiohttp.ClientSession() as session:
        async with session.get(to_reader_url, params={
            "u": url
        }) as response:
            html = await response.text(encoding=response.charset)
    return html
