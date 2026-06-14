from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from home_atlas.app.actions import item_snapshot
from home_atlas.app.dispatcher import dispatch_action, dispatch_function
from home_atlas.app.orchestrator import home_atlas as run_home_atlas
from home_atlas.core.config import Settings, get_settings
from home_atlas.core.security import UnauthorizedError, resolve_actor_id
from home_atlas.domain.models import Item
from home_atlas.infra.db import create_db_engine, seed_people_from_tokens, session_scope
from home_atlas.infra.db_isolation import grant_select_on_new_tables, verify_readonly_isolation
from home_atlas.infra.schema_migration import require_schema_version
from home_atlas.domain.ontology import get_registry


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
    """Build the HomeAtlas FastMCP server.

    FastMCP's built-in bearer auth middleware validates the Authorization header
    before tool execution. The authenticated token remains server-side and is
    not part of any tool schema.
    """

    settings = settings or get_settings()
    engine = create_db_engine(settings)
    grant_select_on_new_tables(settings)
    verify_readonly_isolation(settings)
    with session_scope(engine) as session:
        require_schema_version(session)
        seed_people_from_tokens(session, settings.token_map, settings.admins)

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

        bearer_token = _bearer_token(ctx)

        def _run() -> dict:
            # Run the synchronous orchestrator (including Pydantic AI's run_sync
            # chain) in a worker thread, where no event loop is already running.
            with session_scope(engine) as session:
                actor_id = resolve_actor_id(session, bearer_token, settings.token_map)
                return run_home_atlas(request, session, actor_id, settings)

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    async def ontology_describe() -> dict:
        """Return the full Ontology schema: all Object Types, Link Types, and Action Types."""

        return get_registry().to_dict()

    @mcp.tool()
    async def search_items(
        ctx: Context,
        query: str | None = None,
        kind: str | None = None,
        domain: str | None = None,
        location: str | None = None,
        expiring_within_days: int | None = None,
        include_archived: bool = False,
    ) -> dict:
        """Search inventory items and return structured item snapshots with ids."""

        params = _compact_params(
            query=query,
            kind=kind,
            domain=domain,
            location=location,
            expiring_within_days=expiring_within_days,
            include_archived=include_archived,
        )
        bearer_token = _bearer_token(ctx)

        def _run() -> dict:
            with session_scope(engine) as session:
                actor_id = resolve_actor_id(session, bearer_token, settings.token_map)
                items = dispatch_function(session, actor_id, "search_items", params)
                return {"status": "ok", "items": items}

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    async def add_item(
        ctx: Context,
        name: str,
        kind: str,
        location_name: str,
        quantity: float | None = None,
        unit: str | None = None,
        expiry_date: date | None = None,
        renewal_date: date | None = None,
        purchase_date: date | None = None,
        properties: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> dict:
        """Add an item and return the written row as a structured snapshot."""

        return await _run_item_action(
            ctx,
            engine,
            settings,
            "AddItem",
            _compact_params(
                name=name,
                kind=kind,
                location_name=location_name,
                quantity=quantity,
                unit=unit,
                expiry_date=expiry_date,
                renewal_date=renewal_date,
                purchase_date=purchase_date,
                properties=properties,
                notes=notes,
            ),
        )

    @mcp.tool()
    async def move_item(ctx: Context, item_id: int, location_name: str) -> dict:
        """Move an item to a new location and return the written row."""

        return await _run_item_action(
            ctx,
            engine,
            settings,
            "MoveItem",
            {"item_id": item_id, "location_name": location_name},
        )

    @mcp.tool()
    async def discard_item(ctx: Context, item_id: int) -> dict:
        """Archive an item after the user has confirmed the destructive change."""

        return await _run_item_action(
            ctx,
            engine,
            settings,
            "DiscardItem",
            {"item_id": item_id},
            confirm=True,
        )

    @mcp.tool()
    async def update_item(
        ctx: Context,
        item_id: int,
        name: str | None = None,
        kind: str | None = None,
        quantity: float | None = None,
        unit: str | None = None,
        expiry_date: date | None = None,
        renewal_date: date | None = None,
        purchase_date: date | None = None,
        properties: dict[str, Any] | None = None,
        notes: str | None = None,
        confirm: bool = False,
    ) -> dict:
        """Update item fields and return the written row."""

        params = _compact_params(
            item_id=item_id,
            name=name,
            kind=kind,
            quantity=quantity,
            unit=unit,
            expiry_date=expiry_date,
            renewal_date=renewal_date,
            purchase_date=purchase_date,
            properties=properties,
            notes=notes,
        )
        if confirm:
            params["confirm"] = confirm
        return await _run_item_action(ctx, engine, settings, "UpdateItem", params)

    return mcp


def _bearer_token(ctx: Context) -> str:
    access_token = get_access_token()
    bearer_token = access_token.token if access_token else None
    if bearer_token is None:
        meta = ctx.request_context.meta
        bearer_token = getattr(meta, "home_atlas_bearer_token", None) if meta else None
    if bearer_token is None:
        raise UnauthorizedError("missing authenticated actor token")
    return bearer_token


def _compact_params(**params: Any) -> dict[str, Any]:
    return {name: value for name, value in params.items() if value is not None}


async def _run_item_action(
    ctx: Context,
    engine: Any,
    settings: Settings,
    action_name: str,
    params: dict[str, Any],
    confirm: bool = False,
) -> dict:
    bearer_token = _bearer_token(ctx)

    def _run() -> dict:
        with session_scope(engine) as session:
            actor_id = resolve_actor_id(session, bearer_token, settings.token_map)
            item = dispatch_action(session, actor_id, action_name, params, confirm=confirm)
            if not isinstance(item, Item):
                raise TypeError(f"{action_name} returned {type(item).__name__}, expected Item")
            return {"status": "ok", "item": item_snapshot(session, item)}

    return await anyio.to_thread.run_sync(_run)


def main() -> None:
    settings = get_settings()
    mcp = build_fastmcp(settings)
    mcp.settings.host = settings.host
    mcp.settings.port = settings.port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
