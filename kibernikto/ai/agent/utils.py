from os import getenv

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings, OpenRouterReasoning
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from kibernikto.config import APP_SETTINGS

_KNOWN_PREFIXES = {"vsegpt", "routerai", "openrouter"}


class RouterAiProvider(OpenAIProvider):
    """routerai — OpenAI-compatible provider with an identifiable .name."""

    @property
    def name(self) -> str:
        return "routerai"


def infer_kibernikto_model(model: str | None) -> Model | None:
    """Resolve a provider-prefixed model string to a pydantic-ai Model.

    Returns ``None`` when ``model`` is ``None`` or empty — callers that only
    use the model optionally (e.g. image generation) must guard the result.

    Supported prefixes:
      * ``vsegpt:<name>``     — OpenAI-compatible via vsegpt.ru
      * ``routerai:<name>``   — OpenAI-compatible via routerai.ru
      * ``openrouter:<name>`` — OpenRouter with medium reasoning effort
      * anything else         — delegated to ``pydantic_ai.infer_model``

    Raises ``ValueError`` when the string is non-empty but has no ``:`` separator
    (which would otherwise produce a confusing ``ValueError`` from ``split``).
    """
    if not model:
        return None

    if ":" not in model:
        raise ValueError(
            f"Model name {model!r} has no provider prefix.  "
            f"Use one of: {', '.join(_KNOWN_PREFIXES)} or any pydantic-ai model string like 'openai:gpt-4o'."
        )

    provider_name, model_name = model.split(":", maxsplit=1)

    if provider_name == "vsegpt":
        return OpenAIChatModel(model_name, provider=_vse_gpt_provider())
    if provider_name == "routerai":
        return OpenAIChatModel(model_name, provider=_routerai_provider())
    if provider_name == "openrouter":
        settings = OpenRouterModelSettings(openrouter_reasoning=OpenRouterReasoning(effort="medium"))
        return OpenRouterModel(model_name, provider=_openrouter_provider(), settings=settings)

    return infer_model(model=model)


# ── Private provider factories ────────────────────────────────────────────────

def _vse_gpt_provider() -> OpenAIProvider:
    key = getenv("VSEGPT_API_KEY")
    assert key, "VSEGPT_API_KEY environment variable is not set."
    return OpenAIProvider(base_url="https://api.vsegpt.ru:7090/v1", api_key=key)


def _routerai_provider() -> RouterAiProvider:
    key = getenv("ROUTERAI_API_KEY")
    assert key, "ROUTERAI_API_KEY environment variable is not set."
    return RouterAiProvider(base_url="https://routerai.ru/api/v1", api_key=key)


def _openrouter_provider() -> OpenRouterProvider:
    return OpenRouterProvider(app_url=APP_SETTINGS.URL, app_title=APP_SETTINGS.INSTANCE_NAME)


# ── Public aliases (kept for backwards-compat) ────────────────────────────────
vse_gpt_provider = _vse_gpt_provider
routerai_provider = _routerai_provider
openrouter_provider = _openrouter_provider
