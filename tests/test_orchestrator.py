from __future__ import annotations

import asyncio

from sqlmodel import Session

from home_atlas.config import Settings
from home_atlas.actions import recent_activity
from home_atlas.mcp_server import build_fastmcp
from home_atlas.orchestrator import home_atlas, route_request
from home_atlas.toolsets import all_toolsets, assert_tool_isolation


def test_domain_toolsets_are_prefix_isolated() -> None:
    assert_tool_isolation()
    names = {toolset.name for toolset in all_toolsets()}
    assert names == {"perishables", "cards_docs", "equipment"}


def test_orchestrator_routes_put_where_and_last_touched(session: Session, actor_id: int) -> None:
    created = home_atlas("把护照放进保险柜抽屉", session, actor_id)
    answer = home_atlas("护照在哪？", session, actor_id)
    touched = home_atlas("上次谁动了护照？", session, actor_id)

    assert created["domain"] == "cards_docs"
    assert answer["answer"] == "护照 在 保险柜抽屉"
    assert "你" in touched["answer"]
    assert recent_activity(session, limit=1)[0]["action"] == "AddItem"


def test_orchestrator_routes_expiring_request() -> None:
    routed = route_request("哪些药 7 天内临期？")
    assert routed.intent == "list_expiring"
    assert routed.args["within_days"] == 7


def test_fastmcp_exposes_single_request_argument() -> None:
    async def list_tool_schema() -> dict:
        mcp = build_fastmcp(
            Settings(
                database_url="sqlite:////private/tmp/home_atlas_test_mcp_schema.db",
                token_map={"you-token": "你"},
            )
        )
        tools = await mcp.list_tools()
        assert len(tools) == 1
        return tools[0].inputSchema

    schema = asyncio.run(list_tool_schema())
    assert set(schema["properties"]) == {"request"}
