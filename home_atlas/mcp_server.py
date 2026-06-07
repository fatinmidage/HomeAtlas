from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from home_atlas.config import Settings, get_settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.orchestrator import home_atlas as run_home_atlas
from home_atlas.security import UnauthorizedError, resolve_actor_id


def build_fastmcp(settings: Settings | None = None):
    """Build the single-tool FastMCP server.

    FastMCP transport auth is adapter-specific. To keep Hermes' visible tool
    schema to a single `request` argument, this hook expects the authenticated
    token to be supplied by deployment middleware in MCP request `_meta` as
    `home_atlas_bearer_token`. The stdlib HTTP runner exercises direct
    Authorization-header handling for local smoke tests.
    """

    settings = settings or get_settings()
    engine = create_db_engine(settings)
    create_tables(engine)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)

    mcp = FastMCP("HomeAtlas")

    @mcp.tool()
    def home_atlas(request: str, ctx: Context) -> dict:
        """Delegate a household inventory request to the HomeAtlas orchestrator."""

        meta = ctx.request_context.meta
        bearer_token = getattr(meta, "home_atlas_bearer_token", None) if meta else None
        if bearer_token is None:
            raise UnauthorizedError("missing authenticated actor token in request meta")
        with session_scope(engine) as session:
            actor_id = resolve_actor_id(session, bearer_token, settings.token_map)
            return run_home_atlas(request, session, actor_id)

    return mcp
