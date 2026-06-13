from __future__ import annotations

import pytest
from sqlmodel import Session

from home_atlas.app import actions
from home_atlas.domain.links import auto_traverse, traverse_chain, traverse_link
from home_atlas.domain.models import ItemKind, Location
from home_atlas.domain.ontology import build_registry
from home_atlas.core.security import HomeAtlasError


def test_stored_at_returns_location(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session, actor_id=actor_id, name="护照", kind=ItemKind.DOCUMENT, location_name="保险柜"
    )
    results = traverse_link(session, "Item", item.id, "storedAt")
    assert len(results) == 1
    assert results[0]["name"] == "保险柜"


def test_added_by_returns_person(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session, actor_id=actor_id, name="螺丝刀", kind=ItemKind.TOOL, location_name="工具箱"
    )
    results = traverse_link(session, "Item", item.id, "addedBy")
    assert len(results) == 1
    assert results[0]["name"] == "你"


def test_item_events_returns_history(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session, actor_id=actor_id, name="牛奶", kind=ItemKind.FOOD, location_name="冰箱"
    )
    actions.move_item(session, actor_id=actor_id, item_id=item.id, location_name="厨房台面")
    results = traverse_link(session, "Item", item.id, "itemEvents")
    assert len(results) == 2


def test_parent_location(session: Session) -> None:
    parent = Location(name="客厅")
    session.add(parent)
    session.flush()
    child = Location(name="电视柜", parent_id=parent.id)
    session.add(child)
    session.commit()
    session.refresh(child)

    results = traverse_link(session, "Location", child.id, "parentLocation")
    assert len(results) == 1
    assert results[0]["name"] == "客厅"


def test_unknown_link_raises(session: Session) -> None:
    with pytest.raises(HomeAtlasError, match="unknown link type"):
        traverse_link(session, "Item", 1, "doesNotExist")


def test_wrong_source_type_raises(session: Session) -> None:
    with pytest.raises(HomeAtlasError, match="expects source"):
        traverse_link(session, "Person", 1, "storedAt")


def test_traverse_chain_item_to_parent_location(session: Session, actor_id: int) -> None:
    parent = Location(name="客厅")
    session.add(parent)
    session.flush()
    child = Location(name="电视柜", parent_id=parent.id)
    session.add(child)
    session.commit()

    item = actions.add_item(
        session, actor_id=actor_id, name="遥控器", kind=ItemKind.OTHER, location_name="电视柜"
    )
    results = traverse_chain(session, "Item", item.id, ["storedAt", "parentLocation"])
    assert len(results) == 1
    assert results[0]["name"] == "客厅"


def test_shortest_path_item_to_event() -> None:
    registry = build_registry()
    path = registry.shortest_path("Item", "Event")
    assert path == ["itemEvents"]


def test_auto_traverse_item_to_parent(session: Session, actor_id: int) -> None:
    parent = Location(name="卧室")
    session.add(parent)
    session.flush()
    child = Location(name="床头柜", parent_id=parent.id)
    session.add(child)
    session.commit()

    item = actions.add_item(
        session, actor_id=actor_id, name="手表", kind=ItemKind.OTHER, location_name="床头柜"
    )
    results = auto_traverse(session, "Item", item.id, "Location")
    assert len(results) == 1
    assert results[0]["name"] == "床头柜"


def test_auto_traverse_location_to_items_uses_inverse_link(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session, actor_id=actor_id, name="钥匙", kind=ItemKind.OTHER, location_name="玄关柜"
    )
    location_id = item.location_id

    results = auto_traverse(session, "Location", location_id, "Item")

    assert [result["name"] for result in results] == ["钥匙"]


def test_auto_traverse_same_type_returns_full_source_row(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session, actor_id=actor_id, name="手电筒", kind=ItemKind.TOOL, location_name="工具箱"
    )

    results = auto_traverse(session, "Item", item.id, "Item")

    assert len(results) == 1
    assert results[0]["id"] == item.id
    assert results[0]["name"] == "手电筒"


def test_auto_traverse_masks_secret_item_properties(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session,
        actor_id=actor_id,
        name="家庭保单",
        kind=ItemKind.INSURANCE_POLICY,
        location_name="保险柜",
        properties={"policy_number": "POL12345678", "provider": "测试保险"},
    )

    results = auto_traverse(session, "Item", item.id, "Item")

    assert results[0]["properties"]["policy_number"] == "****5678"
    assert results[0]["properties"]["provider"] == "测试保险"


def test_traverse_events_masks_secret_snapshots(session: Session, actor_id: int) -> None:
    item = actions.add_item(
        session,
        actor_id=actor_id,
        name="会员卡",
        kind=ItemKind.MEMBERSHIP_CARD,
        location_name="钱包",
        properties={"member_id": "MEM12345678", "issuer": "测试商户"},
    )

    results = auto_traverse(session, "Item", item.id, "Event")

    assert results[0]["after"]["properties"]["member_id"] == "****5678"
    assert results[0]["after"]["properties"]["issuer"] == "测试商户"
