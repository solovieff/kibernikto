"""Search-only Kiwi flight expert for the delegated agent roster."""

from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.utils import infer_kibernikto_model

from .config import KIWI_SETTINGS, KiwiSettings

KIWI_DESCRIPTION = 'Поиск авиабилетов через Kiwi.com: маршруты, даты, цены, багаж, пересадки и ссылки на бронирование.'
KIWI_INSTRUCTIONS = '''Ты эксперт по поиску авиабилетов Kiwi.com. Используй search-flight для актуальных рейсов.
Если маршрут или дата неизвестны, скажи, что именно нужно уточнить. Не выдумывай цены и наличие.
Кратко покажи подходящие варианты: маршрут, даты и время, пересадки, багаж, цену и ссылку bookingUrl.
Отмечай самостоятельные пересадки и смену аэропорта, если они есть. Цена и наличие могут измениться.
Возвращай краткую подборку, а не полный ответ сервера. Ссылки bookingUrl копируй дословно, не изменяя.
Ты не бронируешь и не покупаешь билеты: пользователь сам оформляет их на Kiwi.com.
'''


def search_only_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Expose flight search only; do not allow unsolicited feedback or future write tools."""
    def allow(_ctx: RunContext, tool: ToolDefinition) -> bool:
        return tool.name == 'search-flight'

    return toolset.filtered(allow)


def build_kiwi_expert(
        *, settings: KiwiSettings = KIWI_SETTINGS, model: Model | None = None,
        toolset: AbstractToolset | None = None,
) -> SubAgent:
    """Build a transport-free expert; no network request at construction."""
    selected_model = model if model is not None else (
        infer_kibernikto_model(settings.MODEL_NAME) if settings.MODEL_NAME else ...
    )
    tools = toolset if toolset is not None else MCPToolset(settings.MCP_URL)
    agent = build_kibernikto_agent(
        model=selected_model,
        deps_type=TelegramDeps,
        name='kiwi',
        metadata={'reaction': '😎'},
        persona=False,
        history_storage=None,
        instructions=KIWI_INSTRUCTIONS,
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
        toolsets=[search_only_toolset(tools)],
    )
    return SubAgent(agent, name='kiwi', description=KIWI_DESCRIPTION,
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))
