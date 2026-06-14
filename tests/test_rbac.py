from __future__ import annotations

import pytest
from sqlmodel import Session, select

from home_atlas.app.actions import add_item, discard_item, set_person_role, update_item
from home_atlas.domain.models import Event, EventAction, ItemKind, Person
from home_atlas.domain.ontology import build_registry
from home_atlas.core.security import UnauthorizedError


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


def test_member_can_add_and_discard_but_not_update(session: Session) -> None:
    member_id = _create_person(session, "成员", ["member"])

    item = add_item(
        session, actor_id=member_id, name="成员物品",
        kind=ItemKind.FOOD, location_name="冰箱",
    )
    assert item.id is not None

    discarded = discard_item(session, actor_id=member_id, item_id=item.id, confirm=True)
    assert discarded.archived is True

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        update_item(session, actor_id=member_id, item_id=item.id, confirm=True, name="新名字")


def test_admin_can_do_everything(session: Session, actor_id: int) -> None:
    item = add_item(
        session, actor_id=actor_id, name="管理员物品",
        kind=ItemKind.FOOD, location_name="冰箱",
    )
    discarded = discard_item(session, actor_id=actor_id, item_id=item.id, confirm=True)
    assert discarded.archived is True


def test_person_defaults_to_member_role() -> None:
    assert Person(name="默认成员").roles == ["member"]


def test_set_person_role_requires_admin_and_writes_audit(session: Session, actor_id: int) -> None:
    member_id = _create_person(session, "普通成员", ["member"])

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        set_person_role(session, actor_id=member_id, person_name="普通成员", role="admin")

    person = set_person_role(session, actor_id=actor_id, person_name="普通成员", role="admin")
    assert person.roles == ["admin"]

    event = session.exec(select(Event).where(Event.action == EventAction.SET_PERSON_ROLE)).one()
    assert event.actor_id == actor_id
    assert event.after["roles"] == ["admin"]


def test_check_permission_role_hierarchy() -> None:
    registry = build_registry()
    assert registry.check_permission("AddItem", ["admin"]) is True
    assert registry.check_permission("AddItem", ["member"]) is True
    assert registry.check_permission("AddItem", ["viewer"]) is False
    assert registry.check_permission("DiscardItem", ["admin"]) is True
    assert registry.check_permission("DiscardItem", ["member"]) is True
    assert registry.check_permission("DiscardItem", ["viewer"]) is False
