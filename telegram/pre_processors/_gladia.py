# https://www.twilio.com/en-us/blog/working-with-files-asynchronously-in-python-using-aiofiles-and-asyncio
import asyncio
import json
import logging
import os
import pprint
from asyncio import sleep
from http.client import HTTPException
from typing import Callable, Literal, Any

import aiofiles
import aiohttp
from aiohttp import ClientSession
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class GladiaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='VOICE_')
    GLADIA_API_KEY: str | None = None
    GLADIA_POLLING_INTERVAL_SECONDS: int = 13
    GLADIA_SUMMARIZATION_TYPE: Literal["general", "bullet_points", "concise"] = "general"
    GLADIA_UPLOAD_URL: str = "https://api.gladia.io/v2/upload/"
    # TRANSCRIPT_URL: str = "https://api.gladia.io/v2/transcription/"
    TRANSCRIPT_URL: str = "https://api.gladia.io/v2/pre-recorded"
    FILE_LOCATION: str = "/tmp"


class CompositeAudioReply(BaseModel):
    metadata: dict[str, Any] = {}
    summarization: str | None = None
    llm_response: str | None = None
    dialogue_location: str | None = None
    full_location: str | None = None
    full_transcript: str | None = None


DEFAULT_SETTINGS = GladiaSettings()

HEADERS = {
    "x-gladia-key": DEFAULT_SETTINGS.GLADIA_API_KEY,
    "accept": "application/json",
}


async def process_audio(file_path, audio_url=None, user_message=None, context_prompt=None, basic=True):
    """
    :param file_path: The path to the audio file to be processed. The file should be in a supported audio format.
    :type file_path: str
    :param audio_url: The URL of the audio file to be processed. If not provided, the file will be uploaded using the file_path.
    :type audio_url: str, optional
    :param user_message: The user message to be used as the default prompt for audio to text and summarization services. If not provided, a default prompt will be used.
    :type user_message: str, optional
    :param context_prompt: The context prompt to be used for summarization service. If not provided, no context prompt will be used.
    :type context_prompt: str, optional
    :param basic: Flag indicating if it is a usual user message or something more complicated. If basic is false callback is required.
    :type basic: bool, optional
    :return: transcript for basic, None for not basic (to use callback)
    :rtype: None

    """
    default_prompt = user_message if user_message else "Extract the key points from the transcription"

    async with aiohttp.ClientSession() as session:
        if not audio_url:
            audio_url = await _upload_file(session=session, file_path=file_path)

        if basic:
            transcript_request_data = {
                "audio_url": audio_url,
                "enable_code_switching": False,
                "diarization": False,
                "summarization": False,
                "audio_to_llm": False
            }
        else:
            transcript_request_data = {
                "audio_url": audio_url,
                "enable_code_switching": True,
                "diarization": True,
                "summarization": True,
                "summarization_config": {
                    "type": DEFAULT_SETTINGS.GLADIA_SUMMARIZATION_TYPE
                },
                "audio_to_llm": user_message is not None,
                "audio_to_llm_config": {
                    "prompts": [
                        default_prompt
                    ]
                }
            }

            if context_prompt:
                transcript_request_data['context_prompt'] = context_prompt

        transcript_response = await _retrieve_transcript_info(session=session,
                                                              transcript_data=transcript_request_data)
        result_poll_url = transcript_response["result_url"]
        # let async do the job! polling inside!
        transcript_results = await _poll_transcript_ready(result_url=result_poll_url, session=session)

        if basic:
            return transcript_results['transcription']['full_transcript'], None
        else:
            data = await _full_transcript_ready(transcript_results)
            return data.summarization, data


async def _poll_transcript_ready(result_url: str, session: ClientSession):
    transcript_headers = HEADERS.copy()
    transcript_headers["Content-Type"] = "application/json"
    while True:
        async with session.get(url=result_url, headers=transcript_headers) as poll_response:
            json = await poll_response.json()
            # pprint.pprint(json)
            if json["status"] == "done":
                print("+ Transcription done: \n")
                return json['result']
            elif json["status"] == "error":
                print("- Transcription failed")
                pprint.pprint(json)
                raise RuntimeError(f"Failed to get the transcript: {json['result']}")
            else:
                print("Transcription status:", json["status"])
            await sleep(DEFAULT_SETTINGS.GLADIA_POLLING_INTERVAL_SECONDS)


async def _retrieve_transcript_info(session: ClientSession, transcript_data):
    transcript_headers = HEADERS.copy()
    # transcript_headers["Content-Type"] = "application/json"

    post_params = {
        "url": DEFAULT_SETTINGS.TRANSCRIPT_URL,
        "headers": transcript_headers,
        "json": transcript_data
    }

    async with session.post(**post_params) as transcript_response:
        transcript_json = await transcript_response.json()
        if transcript_response.ok:
            print(f"Post response with Transcription ID: {transcript_json}")
            return transcript_json
        else:
            raise HTTPException(f"Failed to start file transcription {transcript_json}")


async def _upload_file(session: ClientSession, file_path):
    head, file_name = os.path.split(file_path)
    path_name, file_extension = os.path.splitext(file_path)
    file_extension = file_extension[1:]

    logging.info(f"{file_path} is being processed by Gladia")

    async with aiofiles.open(file_path, mode='rb') as f:
        form_data = aiohttp.FormData()
        file_content = await f.read()
        upload_headers = HEADERS.copy()
        # upload_headers["Content-Type"] = "multipart/form-data"

        form_data.add_field('audio',
                            file_content,
                            filename=f"{file_name}",
                            content_type=f"audio/{file_extension}")

        async with session.post(url=DEFAULT_SETTINGS.GLADIA_UPLOAD_URL,
                                headers=upload_headers,
                                data=form_data) as upload_response:
            resp_json = await upload_response.json()
            if upload_response.ok:
                audio_url = resp_json['audio_url']
                pprint.pprint(resp_json)

                logging.info(f"successfully uploaded to {audio_url}")
                return audio_url
            else:
                raise HTTPException(f"Failed to upload the file {resp_json}")


async def _basic_transcript_ready(result):
    return result


async def _full_transcript_ready(result) -> CompositeAudioReply:
    # logging.debug(f"{result}")
    metadata = result.get('metadata', {})
    prefix = metadata.get('billing_time')

    summary_location = f'{DEFAULT_SETTINGS.FILE_LOCATION}/summary_{prefix}.txt'
    dialogue_location = f'{DEFAULT_SETTINGS.FILE_LOCATION}/audio_transcription_{prefix}.txt'
    full_location = f"{DEFAULT_SETTINGS.FILE_LOCATION}/full_data_{prefix}.json"

    if result.get('transcription', {}).get('utterances'):
        dialogue = process_dialogue(result['transcription']['utterances'])
    else:
        dialogue = None
        full_transcript = None
        dialogue_location = None

    if result.get('summarization', {}).get('success') is True:
        summarization = result["summarization"]["results"]
    else:
        summarization = None
        summary_location = None

    if result.get('audio_to_llm', {}).get('success') is True:
        llm_response = extract_llm_response(result)
        if llm_response:
            if summarization:
                summarization += f"\n{llm_response}"
            else:
                summarization = f"\n{llm_response}"
    else:
        llm_response = None

    async with aiofiles.open(full_location, 'w') as file:
        await file.write(json.dumps(result, indent=4, ensure_ascii=False))

    if dialogue:
        async with aiofiles.open(dialogue_location, 'w') as file:
            await file.write(dialogue)

    if summarization:
        async with aiofiles.open(summary_location, 'w') as file:
            await file.write(summarization)

    return CompositeAudioReply(metadata=metadata,
                               summarization=summarization,
                               llm_response=llm_response,
                               full_location=full_location,
                               dialogue_location=dialogue_location)


def process_dialogue(transcription_utterances: []):
    current_person = 0
    normal_utterances = []
    cur_utt = {
        "speaker": 0,
        "text": ""
    }
    for utterance in transcription_utterances:
        utterance_speaker = utterance["speaker"]
        text = utterance['text']
        if utterance_speaker != current_person:
            normal_utterances.append(cur_utt.copy())
            cur_utt = {
                "speaker": utterance_speaker,
                "text": ""
            }
            current_person = utterance_speaker
        cur_utt['text'] += f"{text}."

    normal_utterances.append(cur_utt.copy())
    result_string = ""
    for utterance in normal_utterances:
        result_string += f"\n\n{utterance['speaker']}:\n{utterance['text']}"

    return result_string


async def __pure_callback(result, is_error=False):
    if is_error:
        raise RuntimeError(f"Something bad happened {result}")
    data = await _full_transcript_ready(result)
    pprint.pprint(data)


if __name__ == '__main__':
    asyncio.run(
        process_audio(file_path="fox1.ogg",
                      context_prompt="Перед нами интервью",
                      user_message="Как бы ты оценил результаты интервью? Какие проблемы были озвучены?")
    )


def extract_llm_response(gladia_response: dict):
    """
    Extracts "audio_to_llm" section data from a gladia dict.

    :param gladia_response: Full gladia response dict.
    :return: The "audio_to_llm" data from the JSON file, or None if no data is found.
    """

    # Extract "audio_to_llm" section
    audio_to_llm = gladia_response.get('audio_to_llm')

    llm_response = None

    if isinstance(audio_to_llm, dict):
        print("audio_to_llm data found and is a dictionary:", audio_to_llm)
        if audio_to_llm and audio_to_llm.get('success') and audio_to_llm.get('results'):
            first_result = audio_to_llm['results'][0]

            if first_result.get('success') and 'results' in first_result:
                llm_response = first_result['results'].get('response')

    else:
        print("audio_to_llm data not found in the reply!")
    return llm_response
