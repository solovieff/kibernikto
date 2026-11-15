"""here.now publishing expert: turns a chat request into a live static site on its own label."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import HERENOW_INSTRUCTIONS
from .client import HereNowClient, HereNowError, PublishedSite, SiteFile
from .config import HERENOW_SETTINGS, HereNowSettings
from .routing import publish_for_chat, site_for_chat

logger = logging.getLogger(__name__)

HERENOW_EXPERT_NAME = 'herenow'
_CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json',
    '.svg': 'image/svg+xml',
    '.txt': 'text/plain; charset=utf-8',
}


class PageFile(BaseModel):
    """One file of the site; CSS and JS are only needed if you refuse to inline them."""

    path: str = Field(description='Путь от корня сайта, например index.html или assets/style.css')
    content: str = Field(description='Полное содержимое файла как текст')


def build_herenow_expert(*, settings: HereNowSettings = HERENOW_SETTINGS, model: Model | None = None,
                         client: HereNowClient | None = None) -> SubAgent:
    """Build the expert; no network request happens until a tool is called."""
    herenow = client or HereNowClient(settings)
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.MODEL_NAME),
        deps_type=TelegramDeps,
        name=HERENOW_EXPERT_NAME,
        persona=False,
        history_storage=None,
        instructions=HERENOW_INSTRUCTIONS,
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
        metadata={'reaction': '⚡'},
    )

    @agent.tool
    async def publish_site(ctx: RunContext[TelegramDeps], files: list[PageFile],
                           title: str | None = None) -> str:
        """Опубликовать или обновить сайт этого чата.

        Вызывай, когда человек просит сделать, изменить или переопубликовать страницу. Первый вызов создаёт
        сайт и постоянный адрес чата, следующие обновляют тот же сайт. index.html обязателен.

        Args:
            files: Файлы сайта; обычно один index.html.
            title: Название сайта для владельца в here.now, коротко.
        """
        try:
            site = await publish_for_chat(herenow, ctx.deps, _site_files(files), title=title)
        except HereNowError as exc:
            return _error_text(exc)
        return _published_text(site)

    @agent.tool
    async def update_site_meta(ctx: RunContext[TelegramDeps], title: str | None = None,
                               password: str | None = None) -> str:
        """Изменить название или поставить пароль на уже опубликованный сайт этого чата без перепубликации.

        Args:
            title: Новое название сайта для владельца.
            password: Пароль для посетителей; пустая строка снимает пароль.
        """
        if title is None and password is None:
            return 'Нечего менять: нужен title или password.'
        try:
            _, slug, _ = await site_for_chat(herenow, ctx.deps)
        except HereNowError as exc:
            return _error_text(exc)
        if not slug:
            return 'У этого чата ещё нет сайта: сначала опубликуй его через publish_site.'
        try:
            await herenow.patch_metadata(slug, title=title, password=password or None)
        except HereNowError as exc:
            return _error_text(exc)
        return 'Настройки сайта обновлены.'

    @agent.tool
    async def site_info(ctx: RunContext[TelegramDeps]) -> str:
        """Показать адрес и состояние сайта этого чата. Вызывай, когда человек спрашивает, где его сайт."""
        try:
            label, slug, site = await site_for_chat(herenow, ctx.deps)
        except HereNowError as exc:
            return _error_text(exc)
        if site is None:
            return f'Сайта ещё нет. Адрес при публикации будет {label}.{_workspace_suffix(settings)}.'
        return f'Сайт чата: {site.url}'

    return SubAgent(
        agent,
        name=HERENOW_EXPERT_NAME,
        description=(
            'Публикация статических сайтов в интернете: собрать одностраничный сайт, лендинг или визитку '
            'и выложить по постоянному адресу этого чата, обновлять и переопубликовывать его. '
            'Не для поиска информации и не для работы с файлами.'
        ),
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )


def _site_files(files: list[PageFile]) -> list[SiteFile]:
    """Content type comes from the extension: the model should not have to think about headers."""
    return [SiteFile(path=f.path.strip(), content=f.content, content_type=_content_type(f.path))
            for f in files]


def _content_type(path: str) -> str:
    dot = path.rfind('.')
    return _CONTENT_TYPES.get(path[dot:].lower(), 'application/octet-stream') if dot > 0 else 'text/html; charset=utf-8'


def _workspace_suffix(settings: HereNowSettings) -> str:
    return f'{settings.WORKSPACE}.here.now' if settings.WORKSPACE else 'here.now'


def _published_text(site: PublishedSite) -> str:
    """Hand the address over as a bare URL on its own line: the prompt copies it verbatim."""
    url = site.label_url or site.url
    return f'Сайт опубликован и живой.\n{url}'


def _error_text(exc: HereNowError) -> str:
    """Provider codes turned into something a person can act on."""
    logger.info('here.now tool failed: %s', exc)
    match exc.code:
        case 'workspace_not_ready':
            return 'Публикация временно недоступна: домен воркспейса ещё готовится. Попробуй через минуту.'
        case 'version_conflict':
            return 'Сайт одновременно обновили в другом месте. Перечитай текущую версию и опубликуй заново.'
        case 'site_too_large' | 'too_many_files' | 'missing_index' | 'bad_path' | 'empty_site':
            return f'Сайт не проходит ограничения публикации: {exc.message}. Упрости структуру и попробуй снова.'
        case 'invalid_label':
            return 'Не удалось занять адрес для этого чата. Сайт доступен по резервной ссылке из публикации.'
        case 'transport' | 'upload_failed':
            return 'here.now не ответил как ожидалось. Попробуй опубликовать ещё раз позже.'
        case _:
            return f'Публикация не удалась ({exc.code}): {exc.message}'
