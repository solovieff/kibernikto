import logging
import re

from openai.types.chat import ChatCompletion
from pydantic_settings import BaseSettings, SettingsConfigDict
# from pytube import YouTube
from pytubefix import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, CouldNotRetrieveTranscript, TranscriptList

from ._kibernikto_plugin import KiberniktoPlugin, KiberniktoPluginException
from ._weblink_summarizator import _extract_link

# fix for bad title handling :(


YOUTUBE_VIDEO_PRE_URL = "https://www.youtube.com/watch?v="

_DEFAULT_TEXT = "You will be provided with a video transcript. Summarize it and try to give 13 main points.\n {info_text}. \n{text}\n"


class YoutubePluginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUMMARIZATION_')
    OPENAI_API_MODEL: str = "anthropic/claude-3-haiku"
    OPENAI_BASE_URL: str = "https://api.vsegpt.ru:6070/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_MAX_TOKENS: int = 800
    VIDEO_MESSAGE: str = _DEFAULT_TEXT


DEFAULT_SETTINGS = YoutubePluginSettings()


class YoutubePlugin(KiberniktoPlugin):
    index = 1000

    @staticmethod
    def applicable():
        return DEFAULT_SETTINGS.OPENAI_API_KEY is not None

    """
    This plugin is used to get video transcript and then get text summary from it.
    """

    def __init__(self):
        if DEFAULT_SETTINGS.OPENAI_API_KEY:
            super().__init__(model=DEFAULT_SETTINGS.OPENAI_API_MODEL,
                             base_url=DEFAULT_SETTINGS.OPENAI_BASE_URL,
                             api_key=DEFAULT_SETTINGS.OPENAI_API_KEY, post_process_reply=False, store_reply=True,
                             base_message=DEFAULT_SETTINGS.VIDEO_MESSAGE)
        else:
            raise EnvironmentError("No SUMMARIZATION_OPENAI_API_KEY provided!")

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
                                                                                     max_tokens=DEFAULT_SETTINGS.OPENAI_MAX_TOKENS,
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


def _is_youtube_url(url):
    youtube_regex = r'(https?://)?(www\.)?((youtube\.com/watch\?v=)|(youtu\.be/))[^\s]+'
    match = re.match(youtube_regex, url)
    return bool(match)


def _get_video_from_text(text) -> YouTube:
    any_link, other_text = _extract_link(text)
    if any_link is None or not _is_youtube_url(any_link):
        return None, None

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
