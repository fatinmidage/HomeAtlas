from __future__ import annotations

import asyncio

from starlette.testclient import TestClient
from sqlmodel import Session

from home_atlas.agents import build_agents, should_use_ai
from home_atlas.config import Settings
from home_atlas.actions import recent_activity
from home_atlas.mcp_server import HomeAtlasTokenVerifier, build_fastmcp
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
                _env_file=None,
                database_url="sqlite:////private/tmp/home_atlas_test_mcp_schema.db",
                token_map={"you-token": "你"},
            )
        )
        tools = await mcp.list_tools()
        assert len(tools) == 1
        return tools[0].inputSchema

    schema = asyncio.run(list_tool_schema())
    assert set(schema["properties"]) == {"request"}


def test_fastmcp_requires_bearer_auth_when_tokens_are_configured() -> None:
    mcp = build_fastmcp(
        Settings(
            _env_file=None,
            database_url="sqlite:////private/tmp/home_atlas_test_mcp_auth.db",
            token_map={"you-token": "你"},
        )
    )
    client = TestClient(mcp.streamable_http_app())

    response = client.post("/mcp", json={})

    assert response.status_code == 401


def test_home_atlas_token_verifier_maps_bearer_to_actor() -> None:
    async def verify() -> tuple[str | None, str | None]:
        token = await HomeAtlasTokenVerifier({"you-token": "你"}).verify_token("you-token")
        missing = await HomeAtlasTokenVerifier({"you-token": "你"}).verify_token("bad")
        return token.client_id if token else None, missing.client_id if missing else None

    actor_name, missing_name = asyncio.run(verify())
    assert actor_name == "你"
    assert missing_name is None


def test_pydantic_ai_agents_construct_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    agents = build_agents("test")

    assert agents.orchestrator.name is None
    assert should_use_ai(Settings(_env_file=None, agent_mode="auto")) is False
    assert should_use_ai(Settings(_env_file=None, agent_mode="ai")) is True


def test_agent_mode_rules_keeps_deterministic_orchestrator(session: Session, actor_id: int) -> None:
    result = home_atlas("把护照放进保险柜抽屉", session, actor_id, Settings(_env_file=None, agent_mode="rules"))

    assert result["intent"] == "add_item"
