from __future__ import annotations

import pytest
from sqlmodel import Session

from home_atlas import actions
from home_atlas.links import traverse_link
from home_atlas.models import ItemKind, Location
from home_atlas.security import HomeAtlasError


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
