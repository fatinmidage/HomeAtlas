from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlmodel import Session, select

from home_atlas.actions import (
    add_item,
    adjust_quantity,
    discard_item,
    last_touched,
    list_expiring,
    move_item,
    recent_activity,
    set_quantity,
    update_item,
    upsert_card_reference,
    where_is,
)
from home_atlas.models import Event, EventAction, ItemKind
from home_atlas.security import HomeAtlasError, UnauthorizedError, resolve_actor_id


def test_add_move_and_audit_actor(session: Session, actor_id: int) -> None:
    item = add_item(
        session,
        actor_id=actor_id,
        name="护照",
        kind=ItemKind.DOCUMENT,
        location_name="保险柜抽屉",
    )
    moved = move_item(session, actor_id=actor_id, item_id=item.id, location_name="主卧衣柜")

    assert where_is(session, "护照")["location"] == "主卧衣柜"
    assert moved.updated_by_id == actor_id
    events = session.exec(select(Event).where(Event.item_id == item.id)).all()
    assert [event.action for event in events] == [EventAction.ADD_ITEM, EventAction.MOVE_ITEM]
    assert all(event.actor_id == actor_id for event in events)


def test_quantity_actions_validate_and_write_events(session: Session, actor_id: int) -> None:
    item = add_item(
        session,
        actor_id=actor_id,
        name="鸡蛋",
        kind=ItemKind.FOOD,
        location_name="冰箱",
        quantity=10,
        unit="个",
    )

    adjust_quantity(session, actor_id=actor_id, item_id=item.id, delta=-2)
    updated = set_quantity(session, actor_id=actor_id, item_id=item.id, quantity=6)

    assert updated.quantity == 6
    with pytest.raises(HomeAtlasError):
        adjust_quantity(session, actor_id=actor_id, item_id=item.id, delta=-7)


def test_update_and_discard_require_confirmation(session: Session, actor_id: int) -> None:
    item = add_item(
        session,
        actor_id=actor_id,
        name="电钻",
        kind=ItemKind.TOOL,
        location_name="工具箱",
    )

    with pytest.raises(HomeAtlasError):
        update_item(session, actor_id=actor_id, item_id=item.id, name="冲击钻")

    updated = update_item(session, actor_id=actor_id, item_id=item.id, confirm=True, name="冲击钻")
    assert updated.name == "冲击钻"

    with pytest.raises(HomeAtlasError):
        discard_item(session, actor_id=actor_id, item_id=item.id)

    discarded = discard_item(session, actor_id=actor_id, item_id=item.id, confirm=True)
    assert discarded.archived is True


def test_payment_card_stores_reference_only(session: Session, actor_id: int) -> None:
    with pytest.raises(HomeAtlasError):
        upsert_card_reference(
            session,
            actor_id=actor_id,
            name="招商信用卡",
            location_name="钱包",
            card_type=ItemKind.PAYMENT_CARD,
            properties={"issuer": "招商", "last4": "4242", "physical_location": "钱包", "raw": "4242424242424242"},
        )
    with pytest.raises(HomeAtlasError):
        upsert_card_reference(
            session,
            actor_id=actor_id,
            name="招商信用卡",
            location_name="钱包",
            card_type=ItemKind.PAYMENT_CARD,
            properties={"issuer": "招商", "last4": "4242", "cvv": "123"},
        )

    item = upsert_card_reference(
        session,
        actor_id=actor_id,
        name="招商信用卡",
        location_name="钱包",
        card_type=ItemKind.PAYMENT_CARD,
        properties={"issuer": "招商", "card_type": "Visa", "last4": "4242", "expiry_my": "08/29", "physical_location": "钱包"},
    )
    assert item.properties["last4"] == "4242"


def test_list_expiring_uses_expiry_and_renewal(session: Session, actor_id: int) -> None:
    add_item(
        session,
        actor_id=actor_id,
        name="牛奶",
        kind=ItemKind.FOOD,
        location_name="冰箱",
        expiry_date=date.today() + timedelta(days=3),
    )
    add_item(
        session,
        actor_id=actor_id,
        name="车险",
        kind=ItemKind.INSURANCE_POLICY,
        location_name="文件夹",
        renewal_date=date.today() + timedelta(days=5),
    )

    names = {item["name"] for item in list_expiring(session, within_days=7)}
    assert names == {"牛奶", "车险"}


def test_token_resolution_creates_actor_and_rejects_bad_token(session: Session) -> None:
    actor_id = resolve_actor_id(session, "spouse-token", {"spouse-token": "配偶"})
    assert actor_id > 0
    with pytest.raises(UnauthorizedError):
        resolve_actor_id(session, "bad-token", {"spouse-token": "配偶"})


def test_recent_and_last_touched_report_actor(session: Session, actor_id: int) -> None:
    add_item(session, actor_id=actor_id, name="会员卡", kind=ItemKind.MEMBERSHIP_CARD, location_name="钱包")

    assert recent_activity(session, limit=1)[0]["actor"] == "你"
    assert last_touched(session, "会员卡")["actor"] == "你"

