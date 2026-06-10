from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, or_, select

from home_atlas.models import (
    Event,
    EventAction,
    Item,
    ItemDomain,
    ItemKind,
    Location,
    Person,
    domain_for_kind,
    utc_now,
)
from home_atlas.event_bus import enqueue_event
from home_atlas.ontology import get_registry
from home_atlas.property_schemas import validate_item_properties
from home_atlas.security import HomeAtlasError, check_action_permission, reject_payment_card_secrets, scan_sensitive_text


def _snapshot(item: Item | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind.value,
        "domain": item.domain.value,
        "location_id": item.location_id,
        "quantity": item.quantity,
        "unit": item.unit,
        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        "renewal_date": item.renewal_date.isoformat() if item.renewal_date else None,
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "properties": item.properties,
        "notes": item.notes,
        "archived": item.archived,
    }


def _next_version(session: Session, item_id: int | None) -> int | None:
    if item_id is None:
        return None
    from sqlalchemy import func
    dialect = session.bind.dialect.name if session.bind else ""
    if dialect == "postgresql":
        session.exec(select(Item.id).where(Item.id == item_id).with_for_update()).first()
    result = session.exec(
        select(func.coalesce(func.max(Event.version), 0)).where(Event.item_id == item_id)
    ).one()
    return result + 1


def _event(
    session: Session,
    *,
    item: Item | None,
    actor_id: int,
    action: EventAction,
    summary: str,
    before: dict[str, Any] | None,
) -> None:
    item_id = item.id if item else None
    after_snapshot = _snapshot(item)
    session.add(
        Event(
            item_id=item_id,
            actor_id=actor_id,
            action=action,
            summary=summary,
            before=before,
            after=after_snapshot,
            version=_next_version(session, item_id),
        )
    )
    enqueue_event(session, action, item_id, after_snapshot)


def _location(session: Session, name: str) -> Location:
    location = session.exec(select(Location).where(Location.name == name)).first()
    if location is None:
        location = Location(name=name)
        session.add(location)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            location = session.exec(select(Location).where(Location.name == name)).first()
            if location is None:
                raise
    assert location.id is not None
    return location


def _item(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HomeAtlasError(f"item {item_id} not found")
    return item


def _person_name(session: Session, actor_id: int) -> str:
    person = session.get(Person, actor_id)
    return person.name if person else f"person:{actor_id}"


def add_item(
    session: Session,
    *,
    actor_id: int,
    name: str,
    kind: ItemKind,
    location_name: str,
    quantity: float | None = None,
    unit: str | None = None,
    expiry_date: date | None = None,
    renewal_date: date | None = None,
    purchase_date: date | None = None,
    properties: dict[str, Any] | None = None,
    notes: str | None = None,
) -> Item:
    check_action_permission(session, actor_id, "AddItem")
    properties = properties or {}
    scan_sensitive_text(name, "name")
    scan_sensitive_text(notes, "notes")
    scan_sensitive_text(properties, "properties")
    if kind == ItemKind.PAYMENT_CARD:
        reject_payment_card_secrets(properties)
    properties = validate_item_properties(kind, properties)
    location = _location(session, location_name)
    item = Item(
        name=name,
        kind=kind,
        domain=domain_for_kind(kind),
        location_id=location.id,
        quantity=quantity,
        unit=unit,
        expiry_date=expiry_date,
        renewal_date=renewal_date,
        purchase_date=purchase_date,
        properties=properties,
        notes=notes,
        added_by_id=actor_id,
        updated_by_id=actor_id,
    )
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.ADD_ITEM,
        summary=f"Added {name} to {location_name}",
        before=None,
    )
    session.commit()
    session.refresh(item)
    return item


def move_item(session: Session, *, actor_id: int, item_id: int, location_name: str) -> Item:
    check_action_permission(session, actor_id, "MoveItem")
    item = _item(session, item_id)
    before = _snapshot(item)
    location = _location(session, location_name)
    item.location_id = location.id
    item.updated_by_id = actor_id
    item.updated_at = utc_now()
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.MOVE_ITEM,
        summary=f"Moved {item.name} to {location_name}",
        before=before,
    )
    session.commit()
    session.refresh(item)
    return item


def adjust_quantity(session: Session, *, actor_id: int, item_id: int, delta: float) -> Item:
    check_action_permission(session, actor_id, "AdjustQuantity")
    item = _item(session, item_id)
    before = _snapshot(item)
    item.quantity = (item.quantity or 0) + delta
    if item.quantity < 0:
        raise HomeAtlasError("quantity cannot go below zero")
    item.updated_by_id = actor_id
    item.updated_at = utc_now()
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.ADJUST_QUANTITY,
        summary=f"Adjusted {item.name} quantity by {delta}",
        before=before,
    )
    session.commit()
    session.refresh(item)
    return item


def set_quantity(session: Session, *, actor_id: int, item_id: int, quantity: float) -> Item:
    check_action_permission(session, actor_id, "SetQuantity")
    if quantity < 0:
        raise HomeAtlasError("quantity cannot be negative")
    item = _item(session, item_id)
    before = _snapshot(item)
    item.quantity = quantity
    item.updated_by_id = actor_id
    item.updated_at = utc_now()
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.SET_QUANTITY,
        summary=f"Set {item.name} quantity to {quantity}",
        before=before,
    )
    session.commit()
    session.refresh(item)
    return item


def update_item(session: Session, *, actor_id: int, item_id: int, confirm: bool = False, **changes: Any) -> Item:
    check_action_permission(session, actor_id, "UpdateItem")
    item = _item(session, item_id)
    for field_name in ("name", "notes", "properties"):
        if field_name in changes:
            scan_sensitive_text(changes[field_name], field_name)
    if changes.get("properties") and item.kind == ItemKind.PAYMENT_CARD:
        reject_payment_card_secrets(changes["properties"])
    if changes.get("properties"):
        changes["properties"] = validate_item_properties(item.kind, changes["properties"])
    if {"name", "properties"} & set(changes) and not confirm:
        raise HomeAtlasError("overwriting identifying fields requires confirm=true")
    before = _snapshot(item)
    for field_name, value in changes.items():
        if not hasattr(item, field_name):
            raise HomeAtlasError(f"unknown item field: {field_name}")
        setattr(item, field_name, value)
    item.domain = domain_for_kind(item.kind)
    item.updated_by_id = actor_id
    item.updated_at = utc_now()
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.UPDATE_ITEM,
        summary=f"Updated {item.name}",
        before=before,
    )
    session.commit()
    session.refresh(item)
    return item


def upsert_card_reference(
    session: Session,
    *,
    actor_id: int,
    name: str,
    location_name: str,
    card_type: ItemKind,
    properties: dict[str, Any],
) -> Item:
    check_action_permission(session, actor_id, "UpsertCardReference")
    scan_sensitive_text(name, "name")
    scan_sensitive_text(properties, "properties")
    if card_type == ItemKind.PAYMENT_CARD:
        reject_payment_card_secrets(properties)
    properties = validate_item_properties(card_type, properties)
    if card_type not in {ItemKind.PAYMENT_CARD, ItemKind.MEMBERSHIP_CARD, ItemKind.INSURANCE_POLICY, ItemKind.DOCUMENT}:
        raise HomeAtlasError("card reference kind must be payment, membership, insurance, or document")
    existing = session.exec(
        select(Item).where(Item.name == name, Item.kind == card_type, Item.archived == False)  # noqa: E712
    ).first()
    if existing is None:
        return add_item(
            session,
            actor_id=actor_id,
            name=name,
            kind=card_type,
            location_name=location_name,
            properties=properties,
        )
    before = _snapshot(existing)
    location = _location(session, location_name)
    existing.location_id = location.id
    existing.properties = properties
    existing.updated_by_id = actor_id
    existing.updated_at = utc_now()
    session.add(existing)
    session.flush()
    _event(
        session,
        item=existing,
        actor_id=actor_id,
        action=EventAction.UPSERT_CARD_REFERENCE,
        summary=f"Upserted reference for {name}",
        before=before,
    )
    session.commit()
    session.refresh(existing)
    return existing


def discard_item(session: Session, *, actor_id: int, item_id: int, confirm: bool = False) -> Item:
    check_action_permission(session, actor_id, "DiscardItem")
    if not confirm:
        raise HomeAtlasError("discard requires confirm=true")
    item = _item(session, item_id)
    before = _snapshot(item)
    item.archived = True
    item.updated_by_id = actor_id
    item.updated_at = utc_now()
    session.add(item)
    session.flush()
    _event(
        session,
        item=item,
        actor_id=actor_id,
        action=EventAction.DISCARD_ITEM,
        summary=f"Discarded {item.name}",
        before=before,
    )
    session.commit()
    session.refresh(item)
    return item


def set_person_role(session: Session, *, actor_id: int, person_name: str, role: str) -> Person:
    check_action_permission(session, actor_id, "SetPersonRole")
    if role not in {"viewer", "member", "admin"}:
        raise HomeAtlasError("role must be viewer, member, or admin")
    person = session.exec(select(Person).where(Person.name == person_name)).first()
    if person is None:
        person = Person(name=person_name)
        session.add(person)
        session.flush()
    before = {"id": person.id, "name": person.name, "roles": list(person.roles or [])}
    person.roles = [role]
    session.add(person)
    session.flush()
    session.add(
        Event(
            item_id=None,
            actor_id=actor_id,
            action=EventAction.SET_PERSON_ROLE,
            summary=f"Set {person.name} role to {role}",
            before=before,
            after={"id": person.id, "name": person.name, "roles": list(person.roles or [])},
            version=None,
        )
    )
    session.commit()
    session.refresh(person)
    return person


def search_items(
    session: Session,
    *,
    query: str | None = None,
    kind: ItemKind | None = None,
    domain: ItemDomain | None = None,
    location: str | None = None,
    expiring_within_days: int | None = None,
    include_archived: bool = False,
    property_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    statement = select(Item, Location).join(Location, Item.location_id == Location.id)
    if not include_archived:
        statement = statement.where(Item.archived == False)  # noqa: E712
    if query:
        statement = statement.where(col(Item.name).contains(query))
    if kind:
        statement = statement.where(Item.kind == kind)
    if domain:
        statement = statement.where(Item.domain == domain)
    if location:
        statement = statement.where(col(Location.name).contains(location))
    if expiring_within_days is not None:
        today = date.today()
        cutoff = date.fromordinal(today.toordinal() + expiring_within_days)
        statement = statement.where(
            or_(
                (Item.expiry_date >= today) & (Item.expiry_date <= cutoff),
                (Item.renewal_date >= today) & (Item.renewal_date <= cutoff),
            )
        )
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    if property_filter and dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy import cast, type_coerce
        import json as _json
        statement = statement.where(
            type_coerce(Item.properties, JSONB).op("@>")(cast(_json.dumps(property_filter), JSONB))
        )
    rows = session.exec(statement).all()
    results = [_item_dict(item, loc) for item, loc in rows]
    if property_filter and dialect != "postgresql":
        results = [
            r for r in results
            if all(r.get("properties", {}).get(k) == v for k, v in property_filter.items())
        ]
    return results


def get_item(session: Session, item_id: int) -> dict[str, Any]:
    row = session.exec(select(Item, Location).join(Location).where(Item.id == item_id)).first()
    if row is None:
        raise HomeAtlasError(f"item {item_id} not found")
    item, location = row
    return _item_dict(item, location)


def where_is(session: Session, name: str) -> dict[str, Any]:
    rows = search_items(session, query=name)
    exact = [row for row in rows if row["name"] == name]
    candidates = exact or rows
    if not candidates:
        raise HomeAtlasError(f"{name} not found")
    return candidates[0]


def list_expiring(session: Session, within_days: int = 30) -> list[dict[str, Any]]:
    return search_items(session, expiring_within_days=within_days)


def recent_activity(session: Session, limit: int = 10) -> list[dict[str, Any]]:
    statement = (
        select(Event, Person)
        .join(Person, Event.actor_id == Person.id)
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": event.id,
            "item_id": event.item_id,
            "actor": person.name,
            "action": event.action.value,
            "summary": event.summary,
            "before": event.before,
            "after": event.after,
            "version": event.version,
            "created_at": event.created_at.isoformat(),
        }
        for event, person in session.exec(statement).all()
    ]


def last_touched(session: Session, name: str) -> dict[str, Any]:
    item = where_is(session, name)
    statement = (
        select(Event, Person)
        .join(Person, Event.actor_id == Person.id)
        .where(Event.item_id == item["id"])
        .order_by(Event.created_at.desc())
        .limit(1)
    )
    row = session.exec(statement).first()
    if row is None:
        raise HomeAtlasError(f"{name} has no activity")
    event, person = row
    return {
        "item": item["name"],
        "actor": person.name,
        "action": event.action.value,
        "summary": event.summary,
        "created_at": event.created_at.isoformat(),
    }


def _item_dict(item: Item, location: Location) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind.value,
        "domain": item.domain.value,
        "location": location.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        "renewal_date": item.renewal_date.isoformat() if item.renewal_date else None,
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "properties": _masked_properties(item),
        "notes": item.notes,
        "archived": item.archived,
    }


def _masked_properties(item: Item) -> dict[str, Any]:
    registry = get_registry()
    ot = registry.object_type_for_kind(item.kind)
    if ot is None:
        return dict(item.properties or {})
    secret_names = {prop.name for prop in ot.typed_properties if prop.secret}
    return {
        key: _mask_secret(value) if key in secret_names else value
        for key, value in (item.properties or {}).items()
    }


def _mask_secret(value: Any) -> Any:
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"
