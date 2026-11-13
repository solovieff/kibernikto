"""DaData-backed business expert for the delegated roster."""

from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.utils import infer_kibernikto_model

from .config import BUSINESS_SETTINGS, BusinessSettings

DADATA_MCP_URL = 'https://mcp.dadata.ru/mcp'
DADATA_ALLOWED_TOOLS = frozenset({'find_party', 'clean_address', 'find_company_by_domain', 'find_company_by_email'})
BUSINESS_INSTRUCTIONS = '''Ты бизнес-эксперт. Для сведений о российских компаниях и ИП используй DaData.
Ищи организацию или ИП по точному ИНН/ОГРН, либо владельца домена или корпоративной почты.
Уточняй неоднозначный идентификатор и не подменяй его похожим. Адрес можно стандартизировать через DaData.
Не выдумывай данные и не обещай, что сведения полны или обновлены прямо сейчас. Если поле отсутствует,
скажи, что данных нет; отсутствие записи или признаков риска не доказывает надёжность компании.
Отделяй факты от выводов, указывай источник DaData и ограничения предоставленных данных и тарифа.
Не раскрывай ключи, технические заголовки и иные секреты. Не отправляй в сервис лишние персональные данные.
Возвращай краткий результат по заданию с реквизитами, статусом и важными фактами, которые действительно получены.
'''


def build_dadata_toolset(settings: BusinessSettings = BUSINESS_SETTINGS) -> MCPToolset:
    """Send the composite key as a bearer token, not in the URL."""
    if not settings.configured or settings.DADATA_TOKEN is None:
        raise ValueError('DaData MCP requires a configured API key and secret key')
    return MCPToolset(DADATA_MCP_URL, auth=settings.DADATA_TOKEN.get_secret_value())


def dadata_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Expose only reviewed official read-only tools, not future server additions."""
    def allow(_ctx: RunContext, tool: ToolDefinition) -> bool:
        return tool.name in DADATA_ALLOWED_TOOLS
    return toolset.filtered(allow)


def build_business_expert(*, settings: BusinessSettings = BUSINESS_SETTINGS, model: Model | None = None,
                          toolset: AbstractToolset | None = None) -> SubAgent:
    """Build a transport-free expert with no network requests at construction."""
    selected_model = model if model is not None else (
        infer_kibernikto_model(settings.MODEL_NAME) if settings.MODEL_NAME else ...
    )
    remote = toolset if toolset is not None else build_dadata_toolset(settings)
    agent = build_kibernikto_agent(
        model=selected_model, deps_type=TelegramDeps, name='business', persona=False,
        history_storage=None, instructions=BUSINESS_INSTRUCTIONS, toolsets=[dadata_toolset(remote)],
        metadata={'reaction': '🤝'},
    )
    return SubAgent(
        agent, name='business',
        description='DaData: сведения о компаниях и ИП по ИНН, ОГРН, домену или почте; проверка адресов.',
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )
