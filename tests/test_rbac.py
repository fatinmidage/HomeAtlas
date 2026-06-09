from __future__ import annotations

import pytest
from sqlmodel import Session

from home_atlas.actions import add_item, discard_item
from home_atlas.models import ItemKind, Person
from home_atlas.ontology import build_registry
from home_atlas.security import UnauthorizedError


def _create_person(session: Session, name: str, roles: list[str]) -> int:
    person = Person(name=name, roles=roles)
    session.add(person)
    session.commit()
    session.refresh(person)
    assert person.id is not None
    return person.id


def test_viewer_cannot_add_item(session: Session) -> None:
    viewer_id = _create_person(session, "观察者", ["viewer"])

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        add_item(
            session, actor_id=viewer_id, name="测试",
            kind=ItemKind.FOOD, location_name="冰箱",
        )


def test_member_can_add_but_not_discard(session: Session) -> None:
    member_id = _create_person(session, "成员", ["member"])

    item = add_item(
        session, actor_id=member_id, name="成员物品",
        kind=ItemKind.FOOD, location_name="冰箱",
    )
    assert item.id is not None

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        discard_item(session, actor_id=member_id, item_id=item.id, confirm=True)


def test_admin_can_do_everything(session: Session, actor_id: int) -> None:
    item = add_item(
        session, actor_id=actor_id, name="管理员物品",
        kind=ItemKind.FOOD, location_name="冰箱",
    )
    discarded = discard_item(session, actor_id=actor_id, item_id=item.id, confirm=True)
    assert discarded.archived is True


def test_check_permission_role_hierarchy() -> None:
    registry = build_registry()
    assert registry.check_permission("AddItem", ["admin"]) is True
    assert registry.check_permission("AddItem", ["member"]) is True
    assert registry.check_permission("AddItem", ["viewer"]) is False
    assert registry.check_permission("DiscardItem", ["admin"]) is True
    assert registry.check_permission("DiscardItem", ["member"]) is False
    assert registry.check_permission("DiscardItem", ["viewer"]) is False
