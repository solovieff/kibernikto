from os import getenv

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings, OpenRouterReasoning
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from kibernikto.config import APP_SETTINGS


def infer_kibernikto_model(
        model: str
) -> Model:
    provider_name, model_name = model.split(':', maxsplit=1)
    if provider_name == 'vsegpt':
        provider = vse_gpt_provider()
        model = OpenAIChatModel(model_name, provider=provider)
    elif provider_name == 'routerai':
        provider = vse_gpt_provider()
        model = OpenAIChatModel(model_name, provider=provider)
    elif provider_name == 'openrouter':
        provider = openrouter_provider()
        model_settings = OpenRouterModelSettings(openrouter_reasoning=OpenRouterReasoning(effort='medium'))
        model = OpenRouterModel(model_name, provider=provider, settings=model_settings)
    else:
        model = infer_model(model=model)
    return model


def vse_gpt_provider() -> OpenAIProvider:
    vsegpt_key = getenv('VSEGPT_API_KEY')
    assert vsegpt_key is not None, (
        'VSEGPT_API_KEY environment variable is not set. '
    )
    return OpenAIProvider(base_url='https://api.vsegpt.ru:7090/v1', api_key=vsegpt_key)


def routerai_provider() -> OpenAIProvider:
    routerai_key = getenv('ROUTERAI_API_KEY')
    assert routerai_key is not None, (
        'ROUTER_AI_KEY environment variable is not set. '
    )
    return OpenAIProvider(base_url='https://routerai.ru/api/v1', api_key=routerai_key)


def openrouter_provider() -> OpenRouterProvider:
    return OpenRouterProvider(app_url=APP_SETTINGS.URL, app_title=APP_SETTINGS.INSTANCE_NAME)
