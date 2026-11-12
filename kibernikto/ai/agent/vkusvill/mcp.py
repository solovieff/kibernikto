"""VkusVill MCP toolset factory — anonymous catalog access or OAuth 2.0 + PKCE."""

from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import FileTreeStore
from pydantic_ai.mcp import MCPToolset

from .config import VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir


def build_vkusvill_toolset(settings: VkusvillSettings = VKUSVILL_SETTINGS) -> MCPToolset[object]:
    """Tools from mcp.vkusvill.ru; the token store survives restarts in oauth mode."""
    if settings.AUTH_MODE == 'anonymous':
        return MCPToolset(settings.MCP_URL)

    token_dir = resolve_token_dir(settings)
    token_dir.mkdir(parents=True, exist_ok=True)
    # fastmcp OAuth is an httpx.Auth subclass, so it satisfies MCPToolset's auth parameter directly.
    oauth = OAuth(
        mcp_url=settings.MCP_URL,
        client_id=settings.OAUTH_CLIENT_ID,
        client_secret=settings.OAUTH_CLIENT_SECRET,
        scopes=list(settings.OAUTH_SCOPES),
        callback_port=settings.OAUTH_CALLBACK_PORT,
        callback_host=settings.OAUTH_CALLBACK_HOST,
        token_storage=FileTreeStore(data_directory=token_dir),
    )
    return MCPToolset(settings.MCP_URL, auth=oauth)
