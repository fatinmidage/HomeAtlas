from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from home_atlas import actions
from home_atlas.models import ItemDomain, ItemKind


Tool = Callable[..., Any]


@dataclass(frozen=True)
class DomainToolset:
    name: str
    prefix: str
    tools: dict[str, Tool]

    def assert_isolated(self) -> None:
        bad = [name for name in self.tools if not name.startswith(self.prefix)]
        if bad:
            raise AssertionError(f"{self.name} has tools outside prefix {self.prefix}: {bad}")


def perishable_toolset() -> DomainToolset:
    return DomainToolset(
        name="perishables",
        prefix="perishable_",
        tools={
            "perishable_add_item": _add_perishable,
            "perishable_move_item": actions.move_item,
            "perishable_adjust_quantity": actions.adjust_quantity,
            "perishable_set_quantity": actions.set_quantity,
            "perishable_discard": actions.discard_item,
            "perishable_search": _search_perishable,
            "perishable_list_expiring": actions.list_expiring,
        },
    )


def cards_docs_toolset() -> DomainToolset:
    return DomainToolset(
        name="cards_docs",
        prefix="card_",
        tools={
            "card_add_item": _add_document,
            "card_upsert_reference": actions.upsert_card_reference,
            "card_move_item": actions.move_item,
            "card_update_item": actions.update_item,
            "card_discard": actions.discard_item,
            "card_search": _search_cards,
            "card_list_expiring": actions.list_expiring,
        },
    )


def equipment_toolset() -> DomainToolset:
    return DomainToolset(
        name="equipment",
        prefix="equipment_",
        tools={
            "equipment_add_item": _add_equipment,
            "equipment_move_item": actions.move_item,
            "equipment_update_item": actions.update_item,
            "equipment_discard": actions.discard_item,
            "equipment_search": _search_equipment,
        },
    )


def all_toolsets() -> list[DomainToolset]:
    return [perishable_toolset(), cards_docs_toolset(), equipment_toolset()]


def assert_tool_isolation() -> None:
    for toolset in all_toolsets():
        toolset.assert_isolated()


def _add_perishable(
    session: Session,
    *,
    actor_id: int,
    name: str,
    location_name: str,
    kind: ItemKind = ItemKind.FOOD,
    **kwargs: Any,
) -> Any:
    if kind not in {ItemKind.FOOD, ItemKind.MEDICINE}:
        raise ValueError("perishable toolset only accepts food or medicine")
    return actions.add_item(session, actor_id=actor_id, name=name, kind=kind, location_name=location_name, **kwargs)


def _add_document(
    session: Session,
    *,
    actor_id: int,
    name: str,
    location_name: str,
    kind: ItemKind = ItemKind.DOCUMENT,
    **kwargs: Any,
) -> Any:
    if kind not in {ItemKind.INSURANCE_POLICY, ItemKind.PAYMENT_CARD, ItemKind.MEMBERSHIP_CARD, ItemKind.DOCUMENT}:
        raise ValueError("card/doc toolset only accepts card, policy, membership, or document")
    return actions.add_item(session, actor_id=actor_id, name=name, kind=kind, location_name=location_name, **kwargs)


def _add_equipment(
    session: Session,
    *,
    actor_id: int,
    name: str,
    location_name: str,
    kind: ItemKind = ItemKind.TOOL,
    **kwargs: Any,
) -> Any:
    if kind not in {ItemKind.TOOL, ItemKind.APPLIANCE}:
        raise ValueError("equipment toolset only accepts tool or appliance")
    return actions.add_item(session, actor_id=actor_id, name=name, kind=kind, location_name=location_name, **kwargs)


def _search_perishable(session: Session, **kwargs: Any) -> list[dict[str, Any]]:
    return actions.search_items(session, domain=ItemDomain.PERISHABLE, **kwargs)


def _search_cards(session: Session, **kwargs: Any) -> list[dict[str, Any]]:
    return actions.search_items(session, domain=ItemDomain.CARDS_DOCS, **kwargs)


def _search_equipment(session: Session, **kwargs: Any) -> list[dict[str, Any]]:
    return actions.search_items(session, domain=ItemDomain.EQUIPMENT, **kwargs)

