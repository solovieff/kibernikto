import requests
import random

from kibernikto.interactors.tools import Toolbox


async def get_weather(city: str) -> dict:
    """
    Retrieves weather data for a given city using an API key.

    :param city: Name of the city to fetch the weather for.
    :return: A dictionary containing the weather data or an error message.
    """
    random_temperature = random.randint(-30, 50)
    return f"There is {random_temperature}°C in {city}."


def get_weather_tool():
    """
    Returns the OpenAI tool specification for the get_weather function.

    :return: A dictionary describing the tool and its parameters.
    """
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Fetches weather information for a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Name of the city to retrieve the weather for."
                    }
                },
                "required": ["city"]
            }
        }
    }


weather_tool = Toolbox(function_name="get_weather", definition=get_weather_tool(), implementation=get_weather)
