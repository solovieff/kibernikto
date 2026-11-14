"""Anonymous read-only access to the Travala MCP: dynamic client registration + client_credentials token."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx2

from kibernikto.storage.config import STORAGE_SETTINGS

from .config import TRAVALA_SETTINGS, TravalaSettings

CLIENT_FILE = 'client.json'
TOKEN_DIRNAME = 'travala-oauth'
READ_SCOPE = 'mcp:read'
# Travala requires a loopback redirect even though this client never runs a browser flow.
REDIRECT_URI = 'http://127.0.0.1/callback'
EXPIRY_MARGIN_S = 60
HTTP_TIMEOUT_S = 20.0


class TravalaAuthError(RuntimeError):
    """Raised when the Travala OAuth endpoints refuse registration or token issue."""


def default_client_path() -> Path:
    return Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / TOKEN_DIRNAME / CLIENT_FILE


class TravalaAuth(httpx2.Auth):
    """Bearer auth that registers once, caches the client id/secret on disk and renews the token itself."""

    def __init__(self, settings: TravalaSettings = TRAVALA_SETTINGS, client_path: Path | None = None) -> None:
        self._settings = settings
        self._client_path = client_path or default_client_path()
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def async_auth_flow(self, request: httpx2.Request) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        request.headers['Authorization'] = f'Bearer {await self._bearer()}'
        response = yield request
        if response.status_code != 401:
            return
        request.headers['Authorization'] = f'Bearer {await self._bearer(force=True)}'
        yield request

    async def _bearer(self, *, force: bool = False) -> str:
        async with self._lock:
            if force or self._token is None or time.monotonic() >= self._expires_at:
                await self._refresh()
            assert self._token is not None
            return self._token

    async def _refresh(self) -> None:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S, headers={'User-Agent': self._settings.USER_AGENT}) as http:
            client = self._load_client() or await self._register(http)
            payload = await self._request_token(http, client)
            if payload is None:
                # Cached client was revoked or rotated: register a fresh one once.
                self._client_path.unlink(missing_ok=True)
                payload = await self._request_token(http, await self._register(http))
        if payload is None:
            raise TravalaAuthError('Travala refused the client_credentials token request')
        self._token = str(payload['access_token'])
        self._expires_at = time.monotonic() + max(int(payload.get('expires_in', 3600)) - EXPIRY_MARGIN_S, 0)

    def _load_client(self) -> dict[str, str] | None:
        try:
            data = json.loads(self._client_path.read_text())
        except OSError, ValueError:
            return None
        if not isinstance(data, dict) or not data.get('client_id') or not data.get('client_secret'):
            return None
        return {'client_id': str(data['client_id']), 'client_secret': str(data['client_secret'])}

    async def _register(self, http: httpx2.AsyncClient) -> dict[str, str]:
        response = await http.post(f'{self._settings.OAUTH_BASE_URL}/oauth/register', json={
            'client_name': 'kibernikto',
            'redirect_uris': [REDIRECT_URI],
            'grant_types': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_method': 'client_secret_post',
            'scope': READ_SCOPE,
        })
        if response.status_code >= 400:
            raise TravalaAuthError(f'Travala client registration failed: {response.status_code} {response.text[:200]}')
        data = response.json()
        client = {'client_id': str(data['client_id']), 'client_secret': str(data['client_secret'])}
        self._client_path.parent.mkdir(parents=True, exist_ok=True)
        self._client_path.write_text(json.dumps(client))
        self._client_path.chmod(0o600)
        return client

    async def _request_token(self, http: httpx2.AsyncClient, client: dict[str, str]) -> dict[str, object] | None:
        response = await http.post(f'{self._settings.OAUTH_BASE_URL}/oauth/token', data={
            'grant_type': 'client_credentials', 'scope': READ_SCOPE, **client,
        })
        if response.status_code in (400, 401):
            return None
        if response.status_code >= 400:
            raise TravalaAuthError(f'Travala token request failed: {response.status_code} {response.text[:200]}')
        return response.json()
