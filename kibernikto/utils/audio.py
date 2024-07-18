import os
from typing import Literal

from pydub import AudioSegment

# won't work without this.
# don't think we actually need it anymore cause openai is fine with ogg
AudioSegment.ffmpeg = os.environ.get("FFMPEG_PATH")


def convert_ogg_audio(ogg_file_path, format: Literal["mp3", "wav"] = "mp3"):
    with open(ogg_file_path, "rb") as f:
        voice = AudioSegment.from_ogg(f)
        new_file_path = f"{ogg_file_path}.{format}"
        voice_converted = voice.export(new_file_path, format=format)
        os.remove(f"{ogg_file_path}")
        os.remove(new_file_path)
        return voice_converted, new_file_path
