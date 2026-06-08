from __future__ import annotations

from urllib.parse import urlparse

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from home_atlas.config import Settings, get_settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.orchestrator import home_atlas as run_home_atlas
from home_atlas.security import UnauthorizedError, resolve_actor_id


class HomeAtlasTokenVerifier:
    def __init__(self, token_map: dict[str, str]):
        self._token_map = token_map

    async def verify_token(self, token: str) -> AccessToken | None:
        actor_name = self._token_map.get(token)
        if actor_name is None:
            return None
        return AccessToken(
            token=token,
            client_id=actor_name,
            subject=actor_name,
            scopes=["home_atlas"],
            claims={"home_atlas_actor": actor_name},
        )


def build_fastmcp(settings: Settings | None = None):
    """Build the single-tool FastMCP server.

    FastMCP's built-in bearer auth middleware validates the Authorization header
    before tool execution. The authenticated token remains server-side and is
    not part of the `home_atlas(request)` tool schema.
    """

    settings = settings or get_settings()
    engine = create_db_engine(settings)
    create_tables(engine)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)

    auth_settings = None
    token_verifier = None
    if settings.token_map:
        auth_settings = AuthSettings(
            issuer_url=settings.mcp_issuer_url,
            resource_server_url=settings.mcp_resource_server_url,
            required_scopes=["home_atlas"],
        )
        token_verifier = HomeAtlasTokenVerifier(settings.token_map)

    # FastMCP 默认开启 DNS-rebinding 保护，只允许 localhost 的 Host header。
    # 经 Cloudflare 隧道访问时 Host 是公网域名，必须把它加入 allowed_hosts，否则
    # 请求通过认证后会在 Host 校验处被 server 返回 421 Misdirected Request。
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    resource_host = urlparse(settings.mcp_resource_server_url).hostname
    if resource_host and resource_host not in ("127.0.0.1", "localhost", "::1"):
        allowed_hosts += [resource_host, f"{resource_host}:*"]
        allowed_origins.append(f"https://{resource_host}")
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

    # json_response=True 让 MCP 返回普通 JSON（带 Content-Length）而非 chunked SSE 流，对隧道/代理更友好。
    mcp = FastMCP(
        "HomeAtlas",
        auth=auth_settings,
        token_verifier=token_verifier,
        json_response=True,
        transport_security=transport_security,
    )

    @mcp.tool()
    async def home_atlas(request: str, ctx: Context) -> dict:
        """Delegate a household inventory request to the HomeAtlas orchestrator."""

        access_token = get_access_token()
        bearer_token = access_token.token if access_token else None
        if bearer_token is None:
            meta = ctx.request_context.meta
            bearer_token = getattr(meta, "home_atlas_bearer_token", None) if meta else None
        if bearer_token is None:
            raise UnauthorizedError("missing authenticated actor token")

        def _run() -> dict:
            # Run the synchronous orchestrator (including Pydantic AI's run_sync
            # chain) in a worker thread, where no event loop is already running.
            with session_scope(engine) as session:
                actor_id = resolve_actor_id(session, bearer_token, settings.token_map)
                return run_home_atlas(request, session, actor_id, settings)

        return await anyio.to_thread.run_sync(_run)

    return mcp


def main() -> None:
    settings = get_settings()
    mcp = build_fastmcp(settings)
    mcp.settings.host = settings.host
    mcp.settings.port = settings.port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
