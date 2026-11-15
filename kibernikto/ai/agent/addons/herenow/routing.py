"""Chat → site routing: the workspace label is the index, so nothing about slugs is stored locally."""

from __future__ import annotations

import logging
from dataclasses import replace

from kibernikto.ai.agent.harness.expert_memory import conversation_key

from .address import label_for_chat
from .client import HereNowClient, HereNowError, PublishedSite, SiteFile

logger = logging.getLogger(__name__)

# Label points at a site that is gone (deleted or renamed): publish a fresh one and re-route.
_STALE_CODES = frozenset({'http_404', 'http_410', 'not_found', 'site_not_found'})


def chat_label(deps: object) -> str:
    """Readable label for this chat: Telegram username when usable, else the chat id."""
    return label_for_chat(getattr(deps, 'username', None), conversation_key(deps))


async def active_slug(client: HereNowClient, label: str) -> str | None:
    """Slug currently served under ``label``, if any: the routing table is the source of truth."""
    return _slug_for(await client.labels(), label)


async def publish_for_chat(client: HereNowClient, deps: object, files: list[SiteFile], *,
                           title: str | None = None) -> PublishedSite:
    """Update this chat's site, or create it and claim the chat's label on the first publish."""
    label = chat_label(deps)
    slug = await active_slug(client, label)
    if slug:
        try:
            site = await client.publish(files, slug=slug, title=title)
        except HereNowError as exc:
            if exc.code not in _STALE_CODES:
                raise
            logger.warning('here.now label %s points at missing site %s; republishing', label, slug)
        else:
            return await _route(client, label, site)
    site = await client.publish(files, title=title)
    await _open(client, site.slug)
    return await _route(client, label, site)


async def delete_for_chat(client: HereNowClient, deps: object) -> str | None:
    """Delete this chat's site; returns its slug, or ``None`` when the chat never had one."""
    slug = await active_slug(client, chat_label(deps))
    if not slug:
        return None
    try:
        await client.delete_site(slug)
    except HereNowError as exc:
        if exc.code not in _STALE_CODES:
            raise
        logger.info('here.now site %s was already gone', slug)
    return slug


async def site_for_chat(client: HereNowClient, deps: object) -> tuple[str, str | None, PublishedSite | None]:
    """Label, slug and live site of this chat; the site is ``None`` before the first publish."""
    label = chat_label(deps)
    slug = await active_slug(client, label)
    if not slug:
        return label, None, None
    details = await client.site(slug)
    site = PublishedSite(
        slug=slug,
        url=str(details.get('siteUrl') or ''),
        version_id=details.get('currentVersionId'),
        label_url=None,
    )
    return label, slug, site


async def _route(client: HereNowClient, label: str, site: PublishedSite) -> PublishedSite:
    """Claim ``{label}.{workspace}.here.now``; a failed claim must not lose the published site."""
    records = await client.labels()
    held = records.get(label)
    if held and held.get('slug') == site.slug:
        return replace(site, label_url=_label_url(held))  # already ours: nothing to do
    if held and await _exists(client, str(held.get('slug'))):
        logger.warning('here.now label %s already serves site %s', label, held.get('slug'))
        return site
    if held:
        await _drop(client, label)  # the site behind the label is gone: the chat reclaimed its name
    # here.now mints a label from the site title; a site may hold one label, so drop it first.
    for auto_label, record in records.items():
        if record.get('slug') == site.slug and auto_label != label:
            await _drop(client, auto_label)
    try:
        record = await client.assign_label(label, site.slug)
    except HereNowError as exc:
        logger.warning('here.now label %s not assigned to %s: %s', label, site.slug, exc)
        return site
    return replace(site, label_url=_label_url(record))


async def _open(client: HereNowClient, slug: str) -> None:
    """Best effort: a workspace site is members-only until opened, and a chat site is meant to be public."""
    try:
        await client.set_access(slug)
    except HereNowError as exc:
        logger.warning('here.now site %s access not opened: %s', slug, exc)


async def _exists(client: HereNowClient, slug: str) -> bool:
    """Whether a site still lives behind a label; an unknown answer keeps the label untouched."""
    try:
        await client.site(slug)
    except HereNowError as exc:
        return exc.code not in _STALE_CODES
    return True


async def _drop(client: HereNowClient, label: str) -> None:
    """Best effort: a label we cannot free only means the assign below reports a conflict."""
    try:
        await client.delete_label(label)
    except HereNowError as exc:
        logger.warning('here.now label %s not deleted: %s', label, exc)


def _slug_for(records: dict, label: str) -> str | None:
    record = records.get(label)
    return str(record['slug']) if record and record.get('slug') else None


def _label_url(record: dict) -> str | None:
    url = record.get('url') or record.get('hostname')
    return str(url) if url else None
