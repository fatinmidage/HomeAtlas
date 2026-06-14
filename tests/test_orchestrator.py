from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient
from sqlmodel import Session, select

from home_atlas.app.agents import HomeAtlasDeps, _tool_result, build_agents, should_use_ai
from home_atlas.interfaces.cli import init_db
from home_atlas.core.config import Settings
from home_atlas.app.actions import add_item, recent_activity
from home_atlas.interfaces.mcp_server import HomeAtlasTokenVerifier, build_fastmcp
from home_atlas.infra.db import create_db_engine, session_scope
from home_atlas.domain.models import Item, ItemKind
from home_atlas.app.orchestrator import home_atlas, route_request
from home_atlas.app.toolsets import all_toolsets, assert_tool_isolation


def test_domain_toolsets_are_prefix_isolated() -> None:
    assert_tool_isolation()
    names = {toolset.name for toolset in all_toolsets()}
    assert names == {"perishable", "cards_docs", "equipment"}


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


def test_orchestrator_routes_whole_home_inventory_list(session: Session, actor_id: int) -> None:
    home_atlas("把护照放进保险柜抽屉", session, actor_id)
    home_atlas("把螺丝刀放进工具箱", session, actor_id)

    result = home_atlas("家里有什么物品？", session, actor_id)

    assert result["intent"] == "list_items"
    assert {item["name"] for item in result["items"]} == {"护照", "螺丝刀"}


def _migrated_settings(tmp_path: Path, filename: str) -> Settings:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / filename}",
        token_map={"you-token": "你"},
    )
    init_db(settings)
    return settings


def test_fastmcp_exposes_read_write_split_tools(tmp_path: Path) -> None:
    async def list_tool_schemas() -> dict[str, dict]:
        mcp = build_fastmcp(_migrated_settings(tmp_path, "home_atlas_test_mcp_schema.db"))
        tools = await mcp.list_tools()
        tool_names = {tool.name for tool in tools}
        assert tool_names == {
            "home_atlas",
            "ontology_describe",
            "search_items",
            "add_item",
            "move_item",
            "discard_item",
            "update_item",
        }
        schemas = {tool.name: tool.inputSchema for tool in tools}
        ha_tool = next(t for t in tools if t.name == "home_atlas")
        assert set(ha_tool.inputSchema["properties"]) == {"request"}
        return schemas

    schemas = asyncio.run(list_tool_schemas())
    assert schemas["add_item"]["required"] == ["name", "kind", "location_name"]
    assert schemas["move_item"]["required"] == ["item_id", "location_name"]
    assert schemas["discard_item"]["required"] == ["item_id"]
    assert schemas["update_item"]["required"] == ["item_id"]
    assert {"query", "kind", "domain", "location", "expiring_within_days", "include_archived"} <= set(
        schemas["search_items"]["properties"]
    )


def test_fastmcp_structured_tools_write_and_return_snapshots(tmp_path: Path) -> None:
    async def run_tools() -> tuple[dict, dict, dict, dict, dict]:
        settings = _migrated_settings(tmp_path, "home_atlas_test_mcp_write_tools.db")
        mcp = build_fastmcp(settings)
        ctx = SimpleNamespace(
            request_context=SimpleNamespace(meta=SimpleNamespace(home_atlas_bearer_token="you-token"))
        )
        created = await mcp._tool_manager.call_tool(
            "add_item",
            {
                "name": "豆腐乳",
                "kind": "food",
                "location_name": "厨房柜子",
                "quantity": 2,
                "unit": "瓶",
                "expiry_date": "2026-12-14",
                "properties": {"brand": "测试牌"},
            },
            context=ctx,
        )
        found = await mcp._tool_manager.call_tool("search_items", {"query": "豆腐乳"}, context=ctx)
        item_id = found["items"][0]["id"]
        moved = await mcp._tool_manager.call_tool(
            "move_item",
            {"item_id": item_id, "location_name": "冰箱"},
            context=ctx,
        )
        updated = await mcp._tool_manager.call_tool(
            "update_item",
            {"item_id": item_id, "expiry_date": "2027-01-01", "quantity": 1},
            context=ctx,
        )
        discarded = await mcp._tool_manager.call_tool("discard_item", {"item_id": item_id}, context=ctx)

        engine = create_db_engine(settings)
        with session_scope(engine) as session:
            db_item = session.exec(select(Item).where(Item.id == item_id)).one()
            assert db_item.expiry_date == date(2027, 1, 1)
            assert db_item.archived is True

        return created, found, moved, updated, discarded

    created, found, moved, updated, discarded = asyncio.run(run_tools())
    assert created["status"] == "ok"
    assert created["item"]["expiry_date"] == "2026-12-14"
    assert created["item"]["location"] == "厨房柜子"
    assert found["items"][0]["id"] == created["item"]["id"]
    assert moved["item"]["location"] == "冰箱"
    assert updated["item"]["expiry_date"] == "2027-01-01"
    assert updated["item"]["quantity"] == 1.0
    assert discarded["item"]["archived"] is True


def test_fastmcp_write_tool_snapshots_mask_secret_properties(tmp_path: Path) -> None:
    async def add_membership_card() -> dict:
        settings = _migrated_settings(tmp_path, "home_atlas_test_mcp_masking.db")
        mcp = build_fastmcp(settings)
        ctx = SimpleNamespace(
            request_context=SimpleNamespace(meta=SimpleNamespace(home_atlas_bearer_token="you-token"))
        )
        return await mcp._tool_manager.call_tool(
            "add_item",
            {
                "name": "超市会员卡",
                "kind": "membership_card",
                "location_name": "钱包",
                "properties": {"issuer": "测试超市", "member_id": "ABC123456789"},
            },
            context=ctx,
        )

    result = asyncio.run(add_membership_card())

    assert result["item"]["properties"]["member_id"] == "****6789"


def test_fastmcp_requires_bearer_auth_when_tokens_are_configured(tmp_path: Path) -> None:
    mcp = build_fastmcp(_migrated_settings(tmp_path, "home_atlas_test_mcp_auth.db"))
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
    monkeypatch.delenv("HOME_ATLAS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    agents = build_agents("test")

    assert agents.orchestrator.name is None
    tool_names = {
        name
        for toolset in agents.orchestrator.toolsets
        if hasattr(toolset, "tools")
        for name in toolset.tools
    }
    assert {"atlas_last_touched", "atlas_list_expiring", "atlas_list_items"} <= tool_names
    assert should_use_ai(Settings(_env_file=None, agent_mode="auto")) is False
    assert should_use_ai(Settings(_env_file=None, agent_mode="ai")) is True


def test_generated_ai_toolsets_keep_existing_tool_names() -> None:
    from home_atlas.app.agents import _build_ai_toolset_for_domain
    from home_atlas.domain.models import ItemDomain

    expected = {
        ItemDomain.PERISHABLE: {
            "perishable_add_item",
            "perishable_discard",
            "perishable_search",
            "perishable_list_expiring",
        },
        ItemDomain.CARDS_DOCS: {
            "card_add_document",
            "card_discard",
            "card_upsert_payment_reference",
            "card_search",
            "card_where_is",
        },
        ItemDomain.EQUIPMENT: {"equipment_add_item", "equipment_discard", "equipment_search"},
    }
    for domain, names in expected.items():
        toolset = _build_ai_toolset_for_domain(domain)
        assert set(toolset.tools) == names


def test_discard_item_declares_ai_tools_for_each_domain() -> None:
    from home_atlas.domain.models import ItemDomain
    from home_atlas.domain.ontology import get_registry

    discard = get_registry().action_types["DiscardItem"]

    assert discard.required_role == "member"
    assert {tool.domain for tool in discard.ai_tools} == {
        ItemDomain.PERISHABLE,
        ItemDomain.CARDS_DOCS,
        ItemDomain.EQUIPMENT,
    }
    assert {tool.name for tool in discard.ai_tools} == {
        "perishable_discard",
        "card_discard",
        "equipment_discard",
    }


def test_generated_ai_discard_tool_archives_with_confirmation(session: Session, actor_id: int) -> None:
    from home_atlas.app.agents import _build_ai_toolset_for_domain
    from home_atlas.domain.models import ItemDomain

    item = add_item(session, actor_id=actor_id, name="鸡腿软骨", kind=ItemKind.FOOD, location_name="冰箱")
    tool = _build_ai_toolset_for_domain(ItemDomain.PERISHABLE).tools["perishable_discard"]
    ctx = SimpleNamespace(deps=HomeAtlasDeps(session=session, actor_id=actor_id))

    result = tool.function(ctx, item_id=item.id)

    assert result["archived"] is True
    assert result["name"] == "鸡腿软骨"


def test_generated_ai_action_tools_hold_db_lock(monkeypatch, session: Session, actor_id: int) -> None:
    from home_atlas.app import agents
    from home_atlas.app.agents import _build_ai_toolset_for_domain
    from home_atlas.domain.models import ItemDomain

    class RecordingLock:
        def __init__(self) -> None:
            self.entered = False
            self.checked_during_dispatch = False

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.entered = False

    lock = RecordingLock()

    def fake_dispatch_action(*args, **kwargs):
        lock.checked_during_dispatch = lock.entered
        return SimpleNamespace(id=1, name="鸡腿软骨", location_id=1, archived=True, properties={})

    monkeypatch.setattr(agents, "dispatch_action", fake_dispatch_action)
    tool = _build_ai_toolset_for_domain(ItemDomain.PERISHABLE).tools["perishable_discard"]
    ctx = SimpleNamespace(deps=HomeAtlasDeps(session=session, actor_id=actor_id, db_lock=lock))

    result = tool.function(ctx, item_id=1)

    assert result["archived"] is True
    assert lock.checked_during_dispatch is True


def test_generated_ai_toolset_detects_registry_action_without_agent_changes(monkeypatch) -> None:
    from home_atlas.app.agents import _build_ai_toolset_for_domain, build_agents
    from home_atlas.domain.models import EventAction, ItemDomain, ItemKind
    from home_atlas.domain.ontology import AIToolDef, ActionParameterDef, ActionTypeDef, get_registry

    build_agents.cache_clear()
    registry = get_registry()
    patched_actions = dict(registry.action_types)
    patched_actions["PingItem"] = ActionTypeDef(
        api_name="PingItem",
        event_action=EventAction.UPDATE_ITEM,
        applicable_to=frozenset({ItemKind.FOOD}),
        parameters=(ActionParameterDef("item_id", int, True, "物品 ID"),),
        implementation="tests.test_orchestrator._ping_item",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.PERISHABLE,
                name="perishable_ping_item",
                parameter_names=("item_id",),
                description="Ping a food item.",
            ),
        ),
    )
    monkeypatch.setattr(registry, "action_types", patched_actions)

    toolset = _build_ai_toolset_for_domain(ItemDomain.PERISHABLE)

    assert "perishable_ping_item" in toolset.tools


def _ping_item(session: Session, *, actor_id: int, item_id: int) -> dict[str, int]:
    return {"item_id": item_id}


def test_generated_ai_add_item_schema_matches_action_parameter_definitions() -> None:
    from home_atlas.app.agents import _build_ai_toolset_for_domain
    from home_atlas.domain.models import ItemDomain

    tool = _build_ai_toolset_for_domain(ItemDomain.PERISHABLE).tools["perishable_add_item"]
    schema = tool.function_schema.json_schema

    assert set(schema["properties"]) == {
        "name",
        "kind",
        "location_name",
        "quantity",
        "unit",
        "expiry_date",
        "purchase_date",
    }
    assert schema["required"] == ["name", "location_name"]
    assert schema["properties"]["kind"]["default"] == "food"


def test_generated_ai_add_item_writes_expiry_date(session: Session, actor_id: int) -> None:
    from home_atlas.app.agents import _build_ai_toolset_for_domain
    from home_atlas.app.actions import where_is
    from home_atlas.domain.models import ItemDomain

    tool = _build_ai_toolset_for_domain(ItemDomain.PERISHABLE).tools["perishable_add_item"]
    ctx = SimpleNamespace(deps=HomeAtlasDeps(session=session, actor_id=actor_id))

    result = tool.function(ctx, name="鸡蛋", location_name="冷藏区", expiry_date=date(2026, 7, 13))

    assert result["name"] == "鸡蛋"
    assert where_is(session, "鸡蛋")["expiry_date"] == "2026-07-13"


def test_ai_tool_result_masks_secret_properties(session: Session, actor_id: int) -> None:
    from home_atlas.app import actions

    item = actions.add_item(
        session,
        actor_id=actor_id,
        name="护照",
        kind=ItemKind.DOCUMENT,
        location_name="保险柜",
        properties={"document_number": "E12345678", "issuing_authority": "测试机关"},
    )

    result = _tool_result(item)

    assert result["properties"]["document_number"] == "****5678"
    assert result["properties"]["issuing_authority"] == "测试机关"


def test_generated_toolset_covers_registry_actions() -> None:
    from home_atlas.domain.models import ItemDomain
    from home_atlas.domain.ontology import get_registry
    from home_atlas.app.toolsets import toolset_for_domain, _ACTION_TOOL_SUFFIX, _DOMAIN_PREFIX

    registry = get_registry()
    for domain in (ItemDomain.PERISHABLE, ItemDomain.CARDS_DOCS, ItemDomain.EQUIPMENT):
        ts = toolset_for_domain(domain)
        prefix = _DOMAIN_PREFIX[domain]
        ots = registry.object_types_for_domain(domain)
        registry_actions = set()
        for ot in ots:
            for at in registry.actions_for_object_type(ot.api_name):
                registry_actions.add(at.api_name)
        for action_name in registry_actions:
            suffix = _ACTION_TOOL_SUFFIX.get(action_name)
            if suffix is None:
                continue
            expected_tool = f"{prefix}{suffix}"
            assert expected_tool in ts.tools, (
                f"domain {domain.value} missing tool {expected_tool} for {action_name}"
            )


def test_agent_mode_rules_keeps_deterministic_orchestrator(session: Session, actor_id: int) -> None:
    result = home_atlas("把护照放进保险柜抽屉", session, actor_id, Settings(_env_file=None, agent_mode="rules"))

    assert result["intent"] == "add_item"


def test_classify_domain_uses_registry_keywords() -> None:
    from home_atlas.app.orchestrator import _classify_domain

    assert _classify_domain("牛奶") == "perishables"
    assert _classify_domain("螺丝刀") == "equipment"
    assert _classify_domain("护照") == "cards_docs"
    assert _classify_domain("信用卡") == "cards_docs"
    assert _classify_domain("洗衣机") == "equipment"
    assert _classify_domain("遥控器") == "other"


def test_orchestrator_unknown_put_uses_other_domain(session: Session, actor_id: int) -> None:
    result = home_atlas("把遥控器放进电视柜", session, actor_id)

    assert result["domain"] == "other"
    assert home_atlas("遥控器在哪？", session, actor_id)["answer"] == "遥控器 在 电视柜"


def test_agent_mode_auto_without_key_returns_configuration_notice(
    monkeypatch,
    session: Session,
    actor_id: int,
) -> None:
    monkeypatch.delenv("HOME_ATLAS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = home_atlas("家里有什么物品？", session, actor_id, Settings(_env_file=None, agent_mode="auto"))

    assert result["intent"] == "configuration_required"
    assert result["agent_mode"] == "auto"
    assert "HOME_ATLAS_LLM_API_KEY" in result["answer"]
    assert "HOME_ATLAS_AGENT_MODE" in result["answer"]
