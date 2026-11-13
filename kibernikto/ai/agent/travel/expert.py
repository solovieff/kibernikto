"""Travel coordinator with isolated, search-only Kiwi and Tutu delegates."""

from collections.abc import Sequence
from datetime import datetime, timezone

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.capabilities import AgentCapability
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.kiwi.expert import build_kiwi_expert
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.utils import infer_kibernikto_model

from .config import TRAVEL_SETTINGS, TravelSettings

TUTU_ALLOWED_TOOLS = frozenset({
    'search_hotels', 'search_avia', 'search_rail', 'search_bus', 'search_etrain', 'search_multitransport',
    'get_offer_details', 'get_rail_seatmap', 'get_avia_instructions', 'get_rail_instructions',
    'get_bus_instructions', 'get_etrain_instructions', 'get_hotels_instructions',
    'get_multitransport_instructions', 'create_checkout_link', 'fetch_resource',
})

TUTU_INSTRUCTIONS = '''Ты эксперт Туту по поиску билетов, отелей и маршрутов.
Используй инструменты Туту и возвращай предложения с исходными ссылками без изменений.
Не выдумывай цену, наличие, багаж, завтрак, условия отмены и возврата или актуальность данных.
Цена и наличие могут измениться: предложи проверить их на сайте. Не утверждай, что бронирование или оплата выполнены.
Не запрашивай и не передавай паспортные или иные платёжные данные.
Для маршрута с пересадками не доверяй duration_min: вызови elapsed_minutes с ISO departure_at и arrival_at
каждого направления отдельно, включая часовые пояса и пересадки. Для каждой пересадки используй время
прибытия и следующего отправления.
Если часовой пояс неизвестен, не выдумывай полное время пути. Цены на авиа — за всю группу, на поезд — за место.
Для отеля называй число ночей и цену за всё проживание. Если даты или другие необходимые данные не указаны,
верни координатору, что нужно уточнить. Ссылку на выбранный вариант можно построить create_checkout_link;
сами бронирование и оплата происходят на сайте, только по действию пользователя.
'''

TRAVEL_INSTRUCTIONS = '''Ты координатор путешествий. Получи актуальные предложения через специалистов.
Для отелей, поездов, автобусов и электричек используй tutu. Для авиабилетов по умолчанию используй tutu;
если человек просит Kiwi, выбери kiwi. Сравнивай tutu и kiwi только по просьбе сравнить источники,
либо если первый источник не сработал или ничего не нашёл. Не делай два поиска без необходимости.
Делегат не видит историю: передай маршрут, даты, число пассажиров, предпочтения и другие важные условия.
Если обязательные данные отсутствуют — сообщи главному агенту, что надо уточнить, не выдумывай их.
Возвращай реальные варианты и точные ссылки, которые прислали специалисты; не меняй ссылки.
Сохраняй их оговорки о цене, багаже, пересадках и актуальности. Не утверждай, что бронирование оплачено.
'''


def elapsed_minutes(departure: str, arrival: str) -> int:
    """Minutes between ISO-8601 timestamps with explicit time zones, including connections."""
    try:
        start = datetime.fromisoformat(departure)
        end = datetime.fromisoformat(arrival)
    except ValueError as exc:
        raise ModelRetry('Use ISO-8601 timestamps with UTC offsets') from exc
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ModelRetry('Both timestamps must include a UTC offset')
    seconds = (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()
    if seconds < 0:
        raise ModelRetry('Arrival cannot precede departure')
    return int(seconds // 60)


def tutu_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Allow explicitly reviewed read-only tools and URL generation, never passenger registration."""
    def allow(_ctx: RunContext, tool: ToolDefinition) -> bool:
        return tool.name in TUTU_ALLOWED_TOOLS
    return toolset.filtered(allow)


def _model(model: Model | None, model_name: str | None) -> object:
    if model is not None:
        return model
    return infer_kibernikto_model(model_name) if model_name else ...


def build_tutu_expert(*, settings: TravelSettings = TRAVEL_SETTINGS, model: Model | None = None,
                      toolset: AbstractToolset | None = None) -> SubAgent:
    """Build a Tutu delegate without network access until a run."""
    remote = toolset if toolset is not None else MCPToolset(settings.TUTU_MCP_URL)
    agent = build_kibernikto_agent(
        model=_model(model, settings.TUTU_MODEL_NAME), deps_type=TelegramDeps, name='tutu',
        persona=False, history_storage=None, instructions=TUTU_INSTRUCTIONS, metadata={'reaction': '🤓'},
        model_settings={**default_model_settings(), 'max_tokens': settings.TUTU_MODEL_MAX_TOKENS},
        toolsets=[tutu_toolset(remote), FunctionToolset([elapsed_minutes])],
    )
    return SubAgent(agent, name='tutu', description='Туту: авиа, отели, поезда, автобусы и электрички.',
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))


def build_travel_expert(*, settings: TravelSettings = TRAVEL_SETTINGS, model: Model | None = None,
                        experts: list[SubAgent] | None = None,
                        shared_capabilities: Sequence[AgentCapability[TelegramDeps]] = ()) -> SubAgent:
    """Build the coordinator; its isolated delegates share the caller's deps and usage."""
    children = experts if experts is not None else [build_tutu_expert(settings=settings), build_kiwi_expert()]
    roster = KiberniktoSubAgents(agents=children, agent_folders=None, contain_errors=True,
                                shared_capabilities=shared_capabilities)
    agent = build_kibernikto_agent(
        model=_model(model, settings.MODEL_NAME), deps_type=TelegramDeps, name='travel',
        persona=False, history_storage=None, instructions=TRAVEL_INSTRUCTIONS, capabilities=[roster],
        metadata={'reaction': '👀'},
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
    )
    return SubAgent(agent, name='travel',
                    description='Поиск путешествий: авиабилеты, отели, поезда и другие маршруты через Туту и Kiwi.',
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))
