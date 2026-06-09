from __future__ import annotations

from typing import Any

from sqlmodel import Session

from home_atlas.actions import add_item, move_item
from home_atlas.event_bus import get_event_bus
from home_atlas.models import EventAction, ItemKind


def test_event_bus_dispatches_to_subscriber(session: Session, actor_id: int) -> None:
    bus = get_event_bus()
    bus.unsubscribe_all()
    received: list[tuple[EventAction, int | None]] = []

    def handler(action: EventAction, item_id: int | None, after: dict[str, Any] | None) -> None:
        received.append((action, item_id))

    bus.subscribe(EventAction.ADD_ITEM, handler)
    add_item(session, actor_id=actor_id, name="测试物品", kind=ItemKind.FOOD, location_name="冰箱")

    assert len(received) == 1
    assert received[0][0] == EventAction.ADD_ITEM
    assert received[0][1] is not None
    bus.unsubscribe_all()


def test_event_bus_handler_failure_does_not_break_action(session: Session, actor_id: int) -> None:
    bus = get_event_bus()
    bus.unsubscribe_all()

    def bad_handler(action: EventAction, item_id: int | None, after: dict[str, Any] | None) -> None:
        raise RuntimeError("hook failed on purpose")

    bus.subscribe(EventAction.ADD_ITEM, bad_handler)
    item = add_item(session, actor_id=actor_id, name="安全物品", kind=ItemKind.FOOD, location_name="冰箱")

    assert item.id is not None
    assert item.name == "安全物品"
    bus.unsubscribe_all()


def test_event_bus_wildcard_subscriber(session: Session, actor_id: int) -> None:
    bus = get_event_bus()
    bus.unsubscribe_all()
    received_actions: list[EventAction] = []

    def wildcard(action: EventAction, item_id: int | None, after: dict[str, Any] | None) -> None:
        received_actions.append(action)

    bus.subscribe(None, wildcard)
    item = add_item(session, actor_id=actor_id, name="通配物品", kind=ItemKind.FOOD, location_name="冰箱")
    move_item(session, actor_id=actor_id, item_id=item.id, location_name="厨房")

    assert EventAction.ADD_ITEM in received_actions
    assert EventAction.MOVE_ITEM in received_actions
    bus.unsubscribe_all()
