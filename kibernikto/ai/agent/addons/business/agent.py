"""DaData-backed business expert for the delegated roster."""

from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import allow_tools, resolve_expert_model
from kibernikto.ai.agent.harness.expert_memory import expert_memory
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import BUSINESS_INSTRUCTIONS, BUSINESS_MEMORY_GUIDANCE, BUSINESS_MEMORY_HEADING
from .config import BUSINESS_SETTINGS, BusinessSettings

BUSINESS_EXPERT_NAME = 'business'
DADATA_MCP_URL = 'https://mcp.dadata.ru/mcp'
DADATA_ALLOWED_TOOLS = frozenset({'find_party', 'clean_address', 'find_company_by_domain', 'find_company_by_email'})


def build_dadata_toolset(settings: BusinessSettings = BUSINESS_SETTINGS) -> MCPToolset:
    """Send the composite key as a bearer token, not in the URL."""
    if not settings.configured or settings.DADATA_TOKEN is None:
        raise ValueError('DaData MCP requires a configured API key and secret key')
    return MCPToolset(DADATA_MCP_URL, auth=settings.DADATA_TOKEN.get_secret_value())


def dadata_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Expose only reviewed official read-only tools, not future server additions."""
    return allow_tools(toolset, DADATA_ALLOWED_TOOLS)


def build_business_expert(*, settings: BusinessSettings = BUSINESS_SETTINGS, model: Model | None = None,
                          toolset: AbstractToolset | None = None) -> SubAgent:
    """Build a transport-free expert with no network requests at construction."""
    remote = toolset if toolset is not None else build_dadata_toolset(settings)
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.MODEL_NAME),
        deps_type=TelegramDeps,
        name=BUSINESS_EXPERT_NAME,
        persona=False,
        history_storage=None,
        instructions=BUSINESS_INSTRUCTIONS,
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
        toolsets=[dadata_toolset(remote)],
        capabilities=[expert_memory(BUSINESS_EXPERT_NAME, heading=BUSINESS_MEMORY_HEADING,
                                    guidance=BUSINESS_MEMORY_GUIDANCE)],
        metadata={'reaction': '🤝'},
    )
    return SubAgent(
        agent,
        name='business',
        description=(
            'DaData (только РФ): проверка российских компаний и ИП по ИНН, ОГРН, домену или почте; '
            'стандартизация адресов РФ. Не для зарубежных компаний и общих вопросов.'
        ),
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )
