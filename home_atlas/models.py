from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ItemKind(StrEnum):
    FOOD = "food"
    MEDICINE = "medicine"
    INSURANCE_POLICY = "insurance_policy"
    PAYMENT_CARD = "payment_card"
    MEMBERSHIP_CARD = "membership_card"
    DOCUMENT = "document"
    TOOL = "tool"
    APPLIANCE = "appliance"
    OTHER = "other"


class ItemDomain(StrEnum):
    PERISHABLE = "perishable"
    CARDS_DOCS = "cards_docs"
    EQUIPMENT = "equipment"
    OTHER = "other"


class EventAction(StrEnum):
    ADD_ITEM = "AddItem"
    MOVE_ITEM = "MoveItem"
    ADJUST_QUANTITY = "AdjustQuantity"
    SET_QUANTITY = "SetQuantity"
    UPDATE_ITEM = "UpdateItem"
    UPSERT_CARD_REFERENCE = "UpsertCardReference"
    DISCARD_ITEM = "DiscardItem"


def domain_for_kind(kind: ItemKind) -> ItemDomain:
    if kind in {ItemKind.FOOD, ItemKind.MEDICINE}:
        return ItemDomain.PERISHABLE
    if kind in {
        ItemKind.INSURANCE_POLICY,
        ItemKind.PAYMENT_CARD,
        ItemKind.MEMBERSHIP_CARD,
        ItemKind.DOCUMENT,
    }:
        return ItemDomain.CARDS_DOCS
    if kind in {ItemKind.TOOL, ItemKind.APPLIANCE}:
        return ItemDomain.EQUIPMENT
    return ItemDomain.OTHER


class Person(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)


class Location(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    parent_id: int | None = Field(default=None, foreign_key="location.id")
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: ItemKind = Field(index=True)
    domain: ItemDomain = Field(index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    quantity: float | None = None
    unit: str | None = None
    expiry_date: date | None = Field(default=None, index=True)
    renewal_date: date | None = Field(default=None, index=True)
    purchase_date: date | None = None
    properties: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    notes: str | None = None
    added_by_id: int = Field(foreign_key="person.id")
    updated_by_id: int = Field(foreign_key="person.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived: bool = Field(default=False, index=True)


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int | None = Field(default=None, foreign_key="item.id", index=True)
    actor_id: int = Field(foreign_key="person.id", index=True)
    action: EventAction = Field(index=True)
    summary: str
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    version: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)

