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
from ._kibernikto_plugin import KiberniktoPlugin

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
            logging.error(f'failed to get video transcript from {message}: {str(error)}', )
            return None

    async def _run(self, message: str):
        info, video = _get_video_details(message)

        if video is None:
            return None

        transcript = _get_video_transcript(video.video_id)

        if transcript is None:
            return None

        try:
            summary = await self.get_ai_text_summary(transcript, info)
            return f"{summary}"
        except Exception as error:
            logging.warning(f'failed to get ai text summary: {str(error)}', )
            # summary = _get_sber_text_summary(transcript)
            # summary = str(error)
            return None

    async def get_ai_text_summary(self, transcript, info):
        info_text = str(info) if info else ""

        content_to_summarize = self.base_message.format(info_text=info_text, text=transcript)
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


def _get_video_details(message):
    try:
        youtube_video: YouTube = _get_video_from_text(message)
    except:
        return None, None

    if youtube_video is None:
        return None, None

    info = _get_video_info(youtube_video)
    return info, youtube_video


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


def _get_video_from_text(text):
    regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?(?P<id>[A-Za-z0-9\-=_]{11})')

    match = regex.match(text)
    if match:
        video_id = match.group('id')
        # youtube_video = YouTube(f'{YOUTUBE_VIDEO_PRE_URL}{video_id}')
        youtube_video = YouTube(f'{text}')
        return youtube_video
    else:
        return None


def _get_video_transcript(video_id, langcode='ru'):
    try:
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
    except CouldNotRetrieveTranscript as error:
        logging.warning(error)
        return None
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
