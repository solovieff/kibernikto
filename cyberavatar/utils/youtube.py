import logging
import pprint
import re
import openai

import requests as requests
from pytube import YouTube, extract, exceptions
from youtube_transcript_api import YouTubeTranscriptApi, CouldNotRetrieveTranscript

from cyberavatar import constants
from cyberavatar.constants import OPENAI_MAX_TOKENS
from .text import split_text

YOUTUBE_VIDEO_PRE_URL = "https://www.youtube.com/watch?v="


def get_transcript_if_video(message):
    try:
        youtube_video = _get_video_from_text(message)
        if not youtube_video:
            return None
        transcripts = _get_video_transcripts(youtube_video.video_id)
        full_text = ''.join(f"{t['text']} " for t in transcripts if not _eyesore(t['text']))
        transcript = f"{full_text}"

        info = _get_video_info(youtube_video)
        try:
            summary = get_ai_text_summary(transcript, info)
        except Exception as error:
            logging.warning(f'failed to get ai text summary: {str(error)}. Trying sber solution.', )
            summary = get_sber_text_summary(transcript)

        return f"{summary}"
    except Exception as error:
        # processing error
        logging.error('failed to get video transcript', error)
        logging.error(error)
        return None


def _eyesore(string_to_check):
    eyesores = ['музыка', 'апплодисменты', 'ВИДЕО']
    for text in eyesores:
        if (string_to_check.find(text) == True):
            return True
    return False


def get_ai_text_summary(text, info=None):
    info_text = str(info) if info else ""
    if info_text:
        info_text = "Детали видео: " + info_text

    content = constants.SUMMARIZATION_REQUEST.format(info_text=info_text, text=text)
    message = {
        "role": "user",
        "content": content
    }
    response = openai.ChatCompletion.create(api_key=constants.SUMMARIZATION_KEY,
                                            api_base=constants.SUMMARIZATION_API_BASE,
                                            model=constants.SUMMARIZATION_MODEL,
                                            messages=[message],
                                            max_tokens=OPENAI_MAX_TOKENS,
                                            temperature=constants.OPENAI_TEMPERATURE,
                                            )
    response_text = response['choices'][0]['message']['content'].strip()
    logging.info(response_text)
    return response_text


def get_sber_text_summary(text):
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
            part_sum = get_sber_text_summary(p)
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
        youtube_video = YouTube(f'{YOUTUBE_VIDEO_PRE_URL}{video_id}')
        return youtube_video
    else:
        return None


def _get_video_transcripts(video_id, langcode=None):
    try:
        our_transcript = None
        logging.info(f"getting transcripts for video {video_id}")
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id=video_id)
        for transcript in transcript_list:
            if not langcode or langcode in transcript.language_code:
                our_transcript = transcript
                break
            print(transcript.language_code)
    except CouldNotRetrieveTranscript as error:
        logging.warning(error)
        return None
    if not our_transcript:
        return None
    else:
        return our_transcript.fetch()


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


if __name__ == "__main__":
    text = "https://www.youtube.com/watch?v=QjPjsXyRwCM"
    transcript = get_transcript_if_video(text)
    print(transcript)
    summary = get_ai_text_summary(transcript)
    pprint.pprint(summary)
