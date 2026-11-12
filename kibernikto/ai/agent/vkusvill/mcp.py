"""VkusVill MCP toolset factory — anonymous catalog access or OAuth 2.0 + PKCE."""

from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import FileTreeStore
from pydantic_ai.mcp import MCPToolset, ProcessToolCallback

from .config import VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir


def build_vkusvill_toolset(
        settings: VkusvillSettings = VKUSVILL_SETTINGS,
        process_tool_call: ProcessToolCallback | None = None,
) -> MCPToolset[object]:
    """Tools from mcp.vkusvill.ru; the token store survives restarts in oauth mode."""
    # 401 on personalized tools must reach the model as an error, not abort the run after a retry.
    if settings.AUTH_MODE == 'anonymous':
        return MCPToolset(
            settings.MCP_URL,
            process_tool_call=process_tool_call,
            tool_error_behavior='failed',
        )

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
    return MCPToolset(settings.MCP_URL, auth=oauth, process_tool_call=process_tool_call, tool_error_behavior='failed')
