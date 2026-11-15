"""here.now HTTP client: publish a static site into a workspace and route it by label."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx2

from .config import HERENOW_SETTINGS, HereNowSettings

logger = logging.getLogger(__name__)

CLIENT_NAME = 'kibernikto'  # X-HereNow-Client: how here.now attributes the calling platform
DEFAULT_CONTENT_TYPE = 'text/html; charset=utf-8'
ANYONE_WITH_LINK = 'anyone_with_link'  # workspace sites default to members-only
_RETRY_STATUSES = frozenset({429, 503})
_MAX_ERROR_TEXT = 200


class HereNowError(RuntimeError):
    """A here.now call failed; ``code`` is the provider's machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SiteFile:
    """One file of the site; ``path`` is relative to the site root."""

    path: str
    content: str
    content_type: str = DEFAULT_CONTENT_TYPE

    @property
    def data(self) -> bytes:
        return self.content.encode('utf-8')


@dataclass(frozen=True)
class PublishedSite:
    """A live site: its slug, canonical URL, live version and (when routed) its label URL."""

    slug: str
    url: str
    version_id: str | None = None
    label_url: str | None = None


class HereNowClient:
    """Thin, typed wrapper over the here.now publishing, metadata and label endpoints."""

    def __init__(self, settings: HereNowSettings = HERENOW_SETTINGS) -> None:
        self._settings = settings
        self._account_id: str | None = None

    # ── transport ────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Auth plus the account selector: sites must land in the bot's workspace, not a personal account."""
        headers = {'X-HereNow-Client': CLIENT_NAME}
        if self._settings.key is not None:
            headers['Authorization'] = f'Bearer {self._settings.key}'
        if self._settings.WORKSPACE:
            headers['X-HereNow-Account'] = self._settings.WORKSPACE
        return headers

    def _session(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=self._settings.BASE_URL.rstrip('/'),
            headers=self._headers(),
            timeout=self._settings.REQUEST_TIMEOUT_SECONDS,
        )

    async def _call(self, session: httpx2.AsyncClient, method: str, url: str, *,
                    ok: tuple[int, ...] = (200, 201, 202), **kwargs) -> dict:
        """One retry on rate limit, then a typed error — never a raw httpx exception."""
        response: httpx2.Response | None = None
        for attempt in (1, 2):
            try:
                response = await session.request(method, url, **kwargs)
            except httpx2.HTTPError as exc:
                raise HereNowError('transport', type(exc).__name__) from exc
            if response.status_code in _RETRY_STATUSES and attempt == 1:
                await asyncio.sleep(_retry_after(response))
                continue
            break
        if response is None or response.status_code not in ok:
            raise _provider_error(response)
        return response.json() if response.content else {}

    # ── accounts and labels ──────────────────────────────────────────────────

    async def account_id(self) -> str:
        """Workspace id selected by ``WORKSPACE``; the personal account when it is unset."""
        if self._account_id:
            return self._account_id
        async with self._session() as session:
            body = await self._call(session, 'GET', '/api/v1/accounts')
        accounts = body.get('accounts') or []
        wanted = self._settings.WORKSPACE
        if wanted is None:
            match = next((a for a in accounts if a.get('type') == 'personal'), None)
        else:
            match = next((a for a in accounts if a.get('subdomain') == wanted), None)
        if match is None:
            raise HereNowError('workspace_not_found', f'no account for workspace {wanted!r}')
        self._account_id = str(match['accountId'])
        return self._account_id

    async def labels(self) -> dict[str, dict]:
        """Active label records of the workspace, keyed by label: the routing is the index."""
        account = await self.account_id()
        async with self._session() as session:
            body = await self._call(session, 'GET', f'/api/v1/accounts/{account}/site-labels')
        return {item['label']: item for item in body.get('siteLabels') or []
                if item.get('status') == 'active' and item.get('slug')}

    async def assign_label(self, label: str, slug: str) -> dict:
        """Route ``{label}.{workspace}.here.now`` to an owned site; admin only, one label per site."""
        account = await self.account_id()
        async with self._session() as session:
            body = await self._call(session, 'POST', f'/api/v1/accounts/{account}/site-labels',
                                    json={'label': label, 'slug': slug})
        return body.get('siteLabel') or body

    async def delete_label(self, label: str) -> None:
        """Free the label; the site keeps its ``{slug}.here.now`` address."""
        account = await self.account_id()
        async with self._session() as session:
            await self._call(session, 'DELETE', f'/api/v1/accounts/{account}/site-labels/{label}',
                             ok=(200, 202, 204))

    # ── sites ────────────────────────────────────────────────────────────────

    async def publish(self, files: list[SiteFile], *, slug: str | None = None, title: str | None = None,
                      base_version_id: str | None = None) -> PublishedSite:
        """Create the site (no ``slug``) or replace its live version; limits are checked before any request."""
        self._check_limits(files)
        payload: dict[str, object] = {
            'files': [{'path': f.path, 'size': len(f.data), 'contentType': f.content_type} for f in files],
        }
        if title:
            payload['displayName'] = title[:80]
        if base_version_id:
            payload['baseVersionId'] = base_version_id
        async with self._session() as session:
            created = await self._call(session, 'PUT' if slug else 'POST',
                                       f'/api/v1/publish/{slug}' if slug else '/api/v1/publish', json=payload)
            site_slug = str(created.get('slug') or slug)
            upload = created.get('upload') or {}
            targets = {item['path']: item for item in upload.get('uploads') or []}
            for file in files:
                target = targets.get(file.path)
                if target is None:
                    raise HereNowError('upload_missing', f'no upload target for {file.path}')
                await self._upload(target, file)
            finalized = await self._call(session, 'POST', upload.get('finalizeUrl')
                                         or f'/api/v1/publish/{site_slug}/finalize',
                                         json={'versionId': upload.get('versionId')})
        site_url = str(finalized.get('siteUrl') or created.get('siteUrl') or '')
        primary = finalized.get('primaryUrl')
        return PublishedSite(
            slug=site_slug,
            url=site_url,
            version_id=finalized.get('currentVersionId') or upload.get('versionId'),
            label_url=str(primary) if primary and primary != site_url else None,
        )

    async def site(self, slug: str) -> dict:
        """Live site details, including ``currentVersionId`` for the optimistic-concurrency guard."""
        async with self._session() as session:
            return await self._call(session, 'GET', f'/api/v1/publish/{slug}')

    async def set_access(self, slug: str, mode: str = ANYONE_WITH_LINK) -> dict:
        """Set the visitor policy; workspace sites start as members-only, so a new chat site must be opened."""
        async with self._session() as session:
            return await self._call(session, 'PATCH', f'/api/v1/publish/{slug}/access', json={'mode': mode})

    async def patch_metadata(self, slug: str, *, title: str | None = None, password: str | None = None) -> dict:
        """Change owner-facing title or the visitor password without publishing a version."""
        payload: dict[str, object] = {}
        if title is not None:
            payload['displayName'] = title[:80]
        if password is not None:
            payload['password'] = password
        if not payload:
            raise ValueError('nothing to patch')
        async with self._session() as session:
            return await self._call(session, 'PATCH', f'/api/v1/publish/{slug}/metadata', json=payload)

    # ── internals ────────────────────────────────────────────────────────────

    def _check_limits(self, files: list[SiteFile]) -> None:
        """Reject a site the bot should not publish before it costs a round trip."""
        if not files:
            raise HereNowError('empty_site', 'no files to publish')
        if len(files) > self._settings.MAX_FILES:
            raise HereNowError('too_many_files', f'{len(files)} files > {self._settings.MAX_FILES}')
        total = sum(len(f.data) for f in files)
        if total > self._settings.MAX_TOTAL_BYTES:
            raise HereNowError('site_too_large', f'{total} bytes > {self._settings.MAX_TOTAL_BYTES}')
        for file in files:
            _check_path(file.path)
        if 'index.html' not in {f.path for f in files}:
            raise HereNowError('missing_index', 'index.html is required at the site root')

    async def _upload(self, target: dict, file: SiteFile) -> None:
        """PUT the bytes to the presigned URL, signed by ``content-type`` alone: a clean client, no bearer."""
        headers = {str(k): str(v) for k, v in (target.get('headers') or {}).items()}
        headers.setdefault('content-type', file.content_type)
        try:
            async with httpx2.AsyncClient(timeout=self._settings.REQUEST_TIMEOUT_SECONDS) as uploader:
                response = await uploader.put(target['url'], content=file.data, headers=headers)
        except httpx2.HTTPError as exc:
            raise HereNowError('transport', type(exc).__name__) from exc
        if response.status_code not in (200, 201, 204):
            raise HereNowError('upload_failed', f'{file.path}: HTTP {response.status_code}')


def _check_path(path: str) -> None:
    """Only plain relative paths inside the site root."""
    parts = path.split('/')
    if not path or path.startswith(('/', '\\')) or '\\' in path or '..' in parts or '' in parts:
        raise HereNowError('bad_path', f'unsupported path {path!r}')


def _retry_after(response: httpx2.Response) -> float:
    """Server hint capped at five seconds — a chat should not wait longer than that."""
    try:
        return min(5.0, float(response.headers.get('retry-after') or 0)) or 1.0
    except ValueError:
        return 1.0


def _provider_error(response: httpx2.Response | None) -> HereNowError:
    """Map a here.now error body to a typed error without leaking request headers."""
    if response is None:
        return HereNowError('transport', 'no response')
    code = f'http_{response.status_code}'
    message = ''
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        code = str(body.get('code') or code)
        message = str(body.get('message') or body.get('error') or '')[:_MAX_ERROR_TEXT]
    else:
        message = response.text[:_MAX_ERROR_TEXT]
    logger.info('here.now call failed: %s %s', code, message)
    return HereNowError(code, message)
