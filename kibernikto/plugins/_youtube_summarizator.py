import logging
import re

import openai
import requests as requests
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, CouldNotRetrieveTranscript, TranscriptList

from kibernikto.constants import OPENAI_MAX_TOKENS
from kibernikto.utils.text import split_text
from ._kibernikto_plugin import KiberniktoPlugin, KiberniktoPluginException
from ._weblink_summarizator import _extract_link

YOUTUBE_VIDEO_PRE_URL = "https://www.youtube.com/watch?v="


class YoutubePlugin(KiberniktoPlugin):
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
            error_text = f'failed to get video transcript from {message}: {str(error)}'
            logging.error(error_text)
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__, error_message=str(error))

    async def _run(self, message: str):
        info, video, text = _get_video_details(message)

        if video is None:
            return None

        transcript = _get_video_transcript(video.video_id)

        if transcript is None:
            raise KiberniktoPluginException(plugin_name=self.__class__.__name__,
                                            error_message="Failed to load video data!")

        summary = await self.get_ai_text_summary(transcript, info, additional_text=text)
        return f"{summary}"

    async def get_ai_text_summary(self, transcript, info, additional_text):
        info_text = str(info) if info else ""
        user_text = additional_text if additional_text else ""

        content_to_summarize = self.base_message.format(info_text=info_text, text=transcript)
        message = {
            "role": "user",
            "content": f"{content_to_summarize} \n {additional_text}"
        }

        completion: ChatCompletion = await self.client_async.chat.completions.create(model=self.model,
                                                                                     messages=[message],
                                                                                     max_tokens=OPENAI_MAX_TOKENS,
                                                                                     temperature=0.8,
                                                                                     )
        response_text = completion.choices[0].message.content.strip()
        logging.info(response_text)
        return response_text


def _get_video_details(message):
    try:
        youtube_video, other_text = _get_video_from_text(message)
    except:
        return None, None, None

    if youtube_video is None:
        return None, None, None

    info = _get_video_info(youtube_video)
    return info, youtube_video, other_text


def _eyesore(string_to_check):
    eyesores = ['музыка', 'апплодисменты', 'ВИДЕО']
    for text in eyesores:
        if (string_to_check.find(text) == True):
            return True
    return False


def _get_sber_text_summary(text):
    NORMAL_LEN = 15000

    """
    returns text summary using api.aicloud.sbercloud.ru
    will break at any moment
    :param text:
    :return:
    """
    if len(text) > NORMAL_LEN:
        summary = ""
        pieces = split_text(text, NORMAL_LEN)
        for p in pieces:
            part_sum = _get_sber_text_summary(p)
            summary += f"\n\n{part_sum}"
        return summary

    r = requests.post('https://api.aicloud.sbercloud.ru/public/v2/summarizator/predict', json={
        "instances": [
            {
                "text": text,
                "num_beams": 5,
                "num_return_sequences": 3,
                "length_penalty": 0.5
            }
        ]
    })
    logging.debug(f"Status code: {r.status_code}")
    json_result = r.json()
    if 'prediction_best' in json_result:
        return f"{json_result['prediction_best']['bertscore']}"
    else:
        logging.error(f"can not get summary :(, {json_result['comment']}")
        return None


def _is_youtube_url(url):
    youtube_regex = r'(https?://)?(www\.)?((youtube\.com/watch\?v=)|(youtu\.be/))[^\s]+'
    match = re.match(youtube_regex, url)
    return bool(match)


def _get_video_from_text(text) -> YouTube:
    any_link = _extract_link(text)
    if any_link is None or not _is_youtube_url(any_link):
        return None

    other_text = text.replace(any_link, "").strip()
    youtube_video = YouTube(f'{any_link}')
    return youtube_video, other_text


def _get_video_transcript(video_id, langcode='ru'):
    transcript = None
    logging.info(f"getting transcripts for video {video_id}")
    transcripts: TranscriptList = YouTubeTranscriptApi.list_transcripts(video_id=video_id)
    try:
        transcript = transcripts.find_manually_created_transcript()
    except:
        try:
            transcript = transcripts.find_transcript(language_codes=[langcode])
        except:
            generated_transcripts = [trans for trans in transcripts if trans.is_generated]
            transcript = generated_transcripts[0]

    if not transcript:
        return None
    else:
        language_code = transcript.language_code
        transcript_chunks = transcript.fetch()
        logging.info(f"found transcript for video, language: {language_code}")
        full_text = ''.join(f"{t['text']} " for t in transcript_chunks if not _eyesore(t['text']))
        return full_text


def _get_video_info(movie: YouTube):
    movie_data = {
        'title': movie.title,
        'video_id': movie.video_id,
        'views': movie.views,
        'publish_date': movie.publish_date.strftime('%m/%d/%Y'),
        'author': movie.author,
        'duration_sec': movie.length
    }

    if movie.description:
        movie_data['description'] = movie.description.replace('\n', ''),

    return movie_data
