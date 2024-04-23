# https://www.twilio.com/en-us/blog/working-with-files-asynchronously-in-python-using-aiofiles-and-asyncio
import asyncio
import json
import logging
import os
import pprint
from asyncio import sleep
from http.client import HTTPException
from typing import Callable

import aiofiles
import aiohttp
from aiohttp import ClientSession
from pydantic_settings import BaseSettings, SettingsConfigDict


class GladiaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='VOICE_')
    GLADIA_API_KEY: str | None = None
    UPLOAD_URL: str = "https://api.gladia.io/v2/upload/"
    TRANSCRIPT_URL: str = "https://api.gladia.io/v2/transcription/"
    FILE_LOCATION: str = "/tmp"


DEFAULT_SETTINGS = GladiaSettings()

HEADERS = {
    "x-gladia-key": DEFAULT_SETTINGS.GLADIA_API_KEY,
    "accept": "application/json",
}


async def process_audio(file_path, callback, audio_url=None, user_message=None, context_prompt=None, basic=True):
    """
    :param file_path: The path to the audio file to be processed. The file should be in a supported audio format.
    :type file_path: str
    :param callback: The callback function that will be called when the processing is done. The function should accept two arguments - the processed data and a flag indicating if there was
    * an error.
    :type callback: callable
    :param audio_url: The URL of the audio file to be processed. If not provided, the file will be uploaded using the file_path.
    :type audio_url: str, optional
    :param user_message: The user message to be used as the default prompt for audio to text and summarization services. If not provided, a default prompt will be used.
    :type user_message: str, optional
    :param context_prompt: The context prompt to be used for summarization service. If not provided, no context prompt will be used.
    :type context_prompt: str, optional
    :param basic: Flag indicating if the basic transcription service should be used. Default is True.
    :type basic: bool, optional
    :return: None
    :rtype: None

    """
    default_prompt = user_message if user_message else "Extract the key points from the transcription"

    async def callback_preprocessor(result, is_error):
        if is_error:
            await callback(result, True)
        if basic:
            data = await _basic_transcript_ready(result)
        else:
            data = await _full_transcript_ready(result)
        await callback(data, False)

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
                    "type": "bullet_points"
                },
                "audio_to_llm": True,
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
        polling_task = asyncio.get_event_loop().create_task(
            _poll_transcript_ready(result_url=result_poll_url, callback=callback_preprocessor))
        await polling_task


async def _poll_transcript_ready(result_url: str, callback: Callable):
    transcript_headers = HEADERS
    transcript_headers["Content-Type"] = "application/json"
    if result_url:
        async with aiohttp.ClientSession() as session:
            while True:
                print("Polling for results...")
                async with session.get(url=result_url, headers=transcript_headers) as poll_response:
                    json = await poll_response.json()
                    if json["status"] == "done":
                        print("+ Transcription done: \n")
                        await callback(json["result"])
                        break
                    elif json["status"] == "error":
                        print("- Transcription failed")
                        pprint.pprint(json)
                        await callback(json, True)
                    else:
                        print("Transcription status:", json["status"])
                    await sleep(5)


async def _retrieve_transcript_info(session: ClientSession, transcript_data):
    transcript_headers = HEADERS
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


def make_normal_dialogue(transcription_utterances: []):
    current_person = 0
    normal_utterances = []
    cur_utt = {
        "speaker": 0,
        "text": ""
    }
    for utterance in transcription_utterances:
        speaker_string = f"Speaker {utterance['speaker']}"
        text = utterance['text']
        if utterance['speaker'] != current_person:
            normal_utterances.append(cur_utt.copy())
            cur_utt = {
                "speaker": speaker_string,
                "text": ""
            }
        cur_utt['text'] += f"{text}."

    normal_utterances.append(cur_utt.copy())

    return normal_utterances


async def _upload_file(session: ClientSession, file_path):
    file_name, file_extension = os.path.splitext(
        file_path
    )

    logging.info(f"{file_name}.{file_extension} is being processed by Gladia")

    if os.path.exists(file_path):  # This is here to check if the file exists
        print("- File exists")
    else:
        print("- File does not exist")

    async with aiofiles.open(file_path, mode='rb') as f:
        form_data = aiohttp.FormData()
        file_content = await f.read()
        upload_headers = HEADERS
        # upload_headers["Content-Type"] = "multipart/form-data"

        form_data.add_field('audio',
                            file_content,
                            filename=f"{file_name}{file_extension}",
                            content_type=f"audio/{file_extension[1:]}")

        async with session.post(url=DEFAULT_SETTINGS.UPLOAD_URL,
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
    pprint.pprint(result)
    return json.dumps(result, indent=4, ensure_ascii=False)


async def _full_transcript_ready(result):
    pprint.pprint(result)
    summary_location = f'{DEFAULT_SETTINGS.FILE_LOCATION}/summary.txt'
    dialogue_location = f'{DEFAULT_SETTINGS.FILE_LOCATION}/dialogue.json'
    full_location = f"{DEFAULT_SETTINGS.FILE_LOCATION}/full_data.json"

    dialogue = make_normal_dialogue(result['transcription']['utterances'])

    if "summarization" in result:
        summarization = result["summarization"]["results"]
    else:
        summarization = None
        summary_location = None
    async with aiofiles.open(full_location, 'w') as file:
        await file.write(json.dumps(result, indent=4, ensure_ascii=False))
    async with aiofiles.open(dialogue_location, 'w') as file:
        await file.write(json.dumps(dialogue, indent=4, ensure_ascii=False))

    if summarization:
        async with aiofiles.open(summary_location, 'w') as file:
            await file.write(json.dumps(summarization, indent=4, ensure_ascii=False))

    return {
        "summary_location": summary_location,
        "dialogue_location": dialogue_location,
        "full_location": full_location,
    }


async def __pure_callback(result, is_error=False):
    if is_error:
        raise RuntimeError(f"Someting bad happened {result}")
    data = await _full_transcript_ready(result)
    pprint.pprint(data)


if __name__ == '__main__':
    # asyncio.run(_process_audio(file_path="interview_test.ogg", callback=fake_callback))
    # asyncio.run(_process_audio(file_path="anna-and-sasha-16000.wav", callback=fake_callback,
    # audio_url="https://api.gladia.io/file/1c3b9cbb-61cc-455a-a2d3-5e2c6735fdd4"))
    asyncio.run(
        process_audio(file_path="fox1.ogg", callback=__pure_callback,
                      context_prompt="Перед нами интервью",
                      user_message="Как бы ты оценил результаты интервью? Какие проблемы были озвучены?")
    )
