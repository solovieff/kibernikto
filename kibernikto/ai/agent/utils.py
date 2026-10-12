from dataclasses import dataclass
from os import getenv
from typing import Literal

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings, OpenRouterReasoning
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from kibernikto.config import APP_SETTINGS

# How a provider produces images: chat completions with modalities, or the classic /images/generate.
ImageApi = Literal["chat", "images"]


class MissingProviderKeyError(RuntimeError):
    """The env variable holding a provider API key is unset or empty."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleSpec:
    """One OpenAI-compatible gateway: where it lives and which env var holds its key."""

    base_url: str
    key_env: str
    image_api: ImageApi = "images"


# Add a new OpenAI-compatible gateway here — one line, model prefix == dict key.
OPENAI_COMPATIBLE_PROVIDERS: dict[str, OpenAICompatibleSpec] = {
    "vsegpt": OpenAICompatibleSpec("https://api.vsegpt.ru:7090/v1", "VSEGPT_API_KEY"),
    "routerai": OpenAICompatibleSpec("https://routerai.ru/api/v1", "ROUTERAI_API_KEY", image_api="chat"),
    "beget": OpenAICompatibleSpec("https://api-llm.beget.com/v1/", "BEGET_AI_API_KEY"),
}


class KiberniktoOpenAIProvider(OpenAIProvider):
    """OpenAI-compatible provider that reports its registry prefix as ``.name`` and knows its image API."""

    def __init__(self, name: str, spec: OpenAICompatibleSpec, api_key: str) -> None:
        super().__init__(base_url=spec.base_url, api_key=api_key)
        self._name = name
        self.image_api: ImageApi = spec.image_api

    @property
    def name(self) -> str:
        return self._name


def register_openai_compatible(
        prefix: str, base_url: str, key_env: str, *, image_api: ImageApi = "images",
) -> None:
    """Register an extra OpenAI-compatible gateway at runtime (call before models are built)."""
    OPENAI_COMPATIBLE_PROVIDERS[prefix] = OpenAICompatibleSpec(base_url, key_env, image_api)


def known_prefixes() -> list[str]:
    return sorted({*OPENAI_COMPATIBLE_PROVIDERS, "openrouter"})


def infer_kibernikto_model(model: str | None) -> Model | None:
    """Resolve a provider-prefixed model string to a pydantic-ai Model.

    Returns ``None`` when ``model`` is ``None`` or empty — callers that only
    use the model optionally (e.g. image generation) must guard the result.

    Supported prefixes:
      * any key of ``OPENAI_COMPATIBLE_PROVIDERS`` (``vsegpt``, ``routerai``, ``beget``, ...)
      * ``openrouter:<name>`` — OpenRouter with medium reasoning effort
      * anything else         — delegated to ``pydantic_ai.infer_model``

    Raises ``ValueError`` when the string is non-empty but has no ``:`` separator,
    ``MissingProviderKeyError`` when a registered gateway's key env var is unset.
    """
    if not model:
        return None

    if ":" not in model:
        raise ValueError(
            f"Model name {model!r} has no provider prefix.  "
            f"Use one of: {', '.join(known_prefixes())} or any pydantic-ai model string like 'openai:gpt-4o'."
        )

    provider_name, model_name = model.split(":", maxsplit=1)

    if provider_name in OPENAI_COMPATIBLE_PROVIDERS:
        return OpenAIChatModel(model_name, provider=openai_compatible_provider(provider_name))
    if provider_name == "openrouter":
        settings = OpenRouterModelSettings(openrouter_reasoning=OpenRouterReasoning(effort="medium"))
        return OpenRouterModel(model_name, provider=openrouter_provider(), settings=settings)

    return infer_model(model=model)


def openai_compatible_provider(name: str) -> KiberniktoOpenAIProvider:
    """Build the provider for a registered gateway; the key is read from env at call time."""
    spec = OPENAI_COMPATIBLE_PROVIDERS[name]
    key = getenv(spec.key_env)
    if not key:
        raise MissingProviderKeyError(f"{spec.key_env} environment variable is not set (needed for '{name}:' models).")
    return KiberniktoOpenAIProvider(name, spec, key)


def openrouter_provider() -> OpenRouterProvider:
    return OpenRouterProvider(app_url=APP_SETTINGS.URL, app_title=APP_SETTINGS.INSTANCE_NAME)
