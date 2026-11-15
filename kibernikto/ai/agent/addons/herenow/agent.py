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
from kibernikto.ai.agent.harness.expert_memory import expert_memory
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import HERENOW_INSTRUCTIONS, HERENOW_MEMORY_GUIDANCE, HERENOW_MEMORY_HEADING
from .client import HereNowClient, HereNowError, PublishedSite, SiteFile
from .config import HERENOW_SETTINGS, HereNowSettings
from .routing import active_slug, chat_label, delete_for_chat, publish_for_chat, site_for_chat

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

    path: str = Field(description='Path from the site root, e.g. index.html or assets/style.css')
    content: str = Field(description='Full file contents as text')


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
        capabilities=[expert_memory(HERENOW_EXPERT_NAME, heading=HERENOW_MEMORY_HEADING,
                                    guidance=HERENOW_MEMORY_GUIDANCE)],
        metadata={'reaction': '⚡'},
    )

    @agent.tool
    async def publish_site(ctx: RunContext[TelegramDeps], files: list[PageFile],
                           title: str | None = None) -> str:
        """Publish or update the site of this chat.

        Call when the person asks to build, change or republish a page. The first call creates the site and the
        permanent address of the chat; later calls update the same site. index.html is required.

        Args:
            files: Site files; usually a single index.html.
            title: Short owner-facing site title in here.now.
        """
        problems = _html_problems(files)
        if problems:
            return _rejected(problems)
        try:
            site = await publish_for_chat(herenow, ctx.deps, _site_files(files), title=title)
        except HereNowError as exc:
            return _error_text(exc)
        return _published_text(site)

    @agent.tool
    async def update_site_meta(ctx: RunContext[TelegramDeps], title: str | None = None,
                               password: str | None = None) -> str:
        """Change the title or set a visitor password on the published site without republishing it.

        Args:
            title: New owner-facing site title.
            password: Visitor password; an empty string removes it.
        """
        if title is None and password is None:
            return 'Nothing to change: pass title or password.'
        try:
            _, slug, _ = await site_for_chat(herenow, ctx.deps)
        except HereNowError as exc:
            return _error_text(exc)
        if not slug:
            return 'This chat has no site yet: publish it with publish_site first.'
        try:
            await herenow.patch_metadata(slug, title=title, password=password or None)
        except HereNowError as exc:
            return _error_text(exc)
        return 'Site settings updated.'

    @agent.tool
    async def read_site(ctx: RunContext[TelegramDeps]) -> str:
        """Read the index.html currently published for this chat.

        Call before editing: change the real page instead of inventing a new one blind.
        """
        try:
            slug = await active_slug(herenow, chat_label(ctx.deps))
            if slug is None:
                return 'This chat has no site yet: nothing to read.'
            html = await herenow.file_text(slug)
        except HereNowError as exc:
            return _error_text(exc)
        return f"index.html of this chat, {len(html)} chars:\n{html}"

    @agent.tool
    async def delete_site(ctx: RunContext[TelegramDeps]) -> str:
        """Delete the site of this chat for good.

        Call only on an explicit request to delete the site or the page. The address stops opening and the
        versions are gone; use publish_site for edits.
        """
        try:
            slug = await delete_for_chat(herenow, ctx.deps)
        except HereNowError as exc:
            return _error_text(exc)
        if slug is None:
            return 'This chat has no site: nothing to delete.'
        return f'Site deleted. {chat_label(ctx.deps)}.{_workspace_suffix(settings)} no longer opens.'

    @agent.tool
    async def site_info(ctx: RunContext[TelegramDeps]) -> str:
        """Show the address and state of the site of this chat. Call when the person asks where the site is."""
        try:
            label, slug, site = await site_for_chat(herenow, ctx.deps)
        except HereNowError as exc:
            return _error_text(exc)
        if site is None:
            return f'No site yet. On publish the address will be {label}.{_workspace_suffix(settings)}.'
        return f'Site of this chat: {site.url}'

    return SubAgent(
        agent,
        name=HERENOW_EXPERT_NAME,
        description=(
            'Publishing static sites on the internet: build a one-page site, landing page or business card '
            'and put it on the permanent address of this chat, then update and republish it. '
            'Not for researching information and not for working with files.'
        ),
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )


_PLACEHOLDERS = ('lorem ipsum', 'your tagline', 'section 1', 'placeholder text', 'dummy text')


def _html_problems(files: list[PageFile]) -> list[str]:
    """Static gate before anything goes live: a truncated or placeholder page is worse than none."""
    page = next((f for f in files if f.path.strip() == 'index.html'), None)
    if page is None:
        return ['no index.html at the site root']
    html = page.content
    lowered = html.lower()
    problems: list[str] = []
    if not lowered.strip().endswith('</html>'):
        problems.append('the file is not closed: the last tag must be </html> — the output looks truncated')
    if 'name="viewport"' not in lowered and "name='viewport'" not in lowered:
        problems.append('no <meta name="viewport"> — the page will slide on a phone')
    if lowered.count('<style') != lowered.count('</style>'):
        problems.append('unbalanced <style> tags')
    if lowered.count('<script') != lowered.count('</script>'):
        problems.append('unbalanced <script> tags')
    stubs = [word for word in _PLACEHOLDERS if word in lowered]
    if stubs:
        problems.append('filler instead of real text: ' + ', '.join(stubs))
    return problems


def _rejected(problems: list[str]) -> str:
    """Hand the model its own mistakes and ask for a rewrite in the same run."""
    return ('The page failed the checks and nothing was published:\n- ' + '\n- '.join(problems)
            + '\nRewrite index.html in full (closed </html>, viewport, real copy) and call publish_site again.')


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
    return f'The site is published and live.\n{url}'


def _error_text(exc: HereNowError) -> str:
    """Provider codes turned into something a person can act on."""
    logger.info('here.now tool failed: %s', exc)
    match exc.code:
        case 'workspace_not_ready':
            return 'Publishing is temporarily unavailable: the workspace domain is still being prepared. Try again in a minute.'
        case 'version_conflict':
            return 'The site was updated elsewhere at the same time. Re-read the current version and publish again.'
        case 'site_too_large' | 'too_many_files' | 'missing_index' | 'bad_path' | 'empty_site':
            return f'The site does not fit the publishing limits: {exc.message}. Simplify the structure and try again.'
        case 'invalid_label':
            return 'Could not claim the address for this chat. The site is reachable at the fallback link from the publish result.'
        case 'transport' | 'upload_failed':
            return 'here.now did not answer as expected. Try publishing again later.'
        case _:
            return f'Publishing failed ({exc.code}): {exc.message}'
