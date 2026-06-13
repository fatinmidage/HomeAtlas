from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from home_atlas.app.dispatcher import dispatch_action, dispatch_function
from home_atlas.domain.models import ItemDomain, ItemKind
from home_atlas.ontology import get_registry


Tool = Callable[..., Any]

_DOMAIN_PREFIX = {
    ItemDomain.PERISHABLE: "perishable_",
    ItemDomain.CARDS_DOCS: "card_",
    ItemDomain.EQUIPMENT: "equipment_",
    ItemDomain.OTHER: "other_",
}

_DOMAIN_ALLOWED_KINDS: dict[ItemDomain, set[ItemKind]] = {
    ItemDomain.PERISHABLE: {ItemKind.FOOD, ItemKind.MEDICINE},
    ItemDomain.CARDS_DOCS: {ItemKind.INSURANCE_POLICY, ItemKind.PAYMENT_CARD, ItemKind.MEMBERSHIP_CARD, ItemKind.DOCUMENT},
    ItemDomain.EQUIPMENT: {ItemKind.TOOL, ItemKind.APPLIANCE},
}


@dataclass(frozen=True)
class DomainToolset:
    name: str
    prefix: str
    tools: dict[str, Tool]

    def assert_isolated(self) -> None:
        bad = [name for name in self.tools if not name.startswith(self.prefix)]
        if bad:
            raise AssertionError(f"{self.name} has tools outside prefix {self.prefix}: {bad}")


def _make_guarded_add(domain: ItemDomain, allowed_kinds: set[ItemKind]) -> Tool:
    default_kind = next(iter(allowed_kinds))

    def guarded_add(
        session: Session,
        *,
        actor_id: int,
        name: str,
        location_name: str,
        kind: ItemKind = default_kind,
        **kwargs: Any,
    ) -> Any:
        if kind not in allowed_kinds:
            raise ValueError(f"{domain.value} toolset only accepts {sorted(k.value for k in allowed_kinds)}")
        return dispatch_action(
            session,
            actor_id,
            "AddItem",
            {"name": name, "kind": kind, "location_name": location_name, **kwargs},
        )

    return guarded_add


def _make_domain_search(domain: ItemDomain) -> Tool:
    def domain_search(session: Session, *, actor_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        return dispatch_function(session, actor_id, "search_items", {"domain": domain, **kwargs})
    return domain_search


_ACTION_TOOL_SUFFIX: dict[str, str] = {
    "AddItem": "add_item",
    "MoveItem": "move_item",
    "AdjustQuantity": "adjust_quantity",
    "SetQuantity": "set_quantity",
    "UpdateItem": "update_item",
    "UpsertCardReference": "upsert_reference",
    "DiscardItem": "discard",
}


def toolset_for_domain(domain: ItemDomain) -> DomainToolset:
    registry = get_registry()
    prefix = _DOMAIN_PREFIX[domain]
    allowed_kinds = _DOMAIN_ALLOWED_KINDS.get(domain, set())
    tools: dict[str, Tool] = {}

    ots = registry.object_types_for_domain(domain)
    applicable_actions = set()
    for ot in ots:
        for at in registry.actions_for_object_type(ot.api_name):
            applicable_actions.add(at.api_name)

    for action_name in applicable_actions:
        suffix = _ACTION_TOOL_SUFFIX.get(action_name)
        if suffix is None:
            continue
        tool_name = f"{prefix}{suffix}"
        if action_name == "AddItem":
            tools[tool_name] = _make_guarded_add(domain, allowed_kinds)
        else:
            tools[tool_name] = _make_dispatch_tool(action_name)

    tools[f"{prefix}search"] = _make_domain_search(domain)
    if domain == ItemDomain.PERISHABLE:
        tools[f"{prefix}list_expiring"] = _make_list_expiring()

    return DomainToolset(name=domain.value, prefix=prefix, tools=tools)


def _make_dispatch_tool(action_name: str) -> Tool:
    def dispatch_tool(session: Session, *, actor_id: int, confirm: bool = False, **params: Any) -> Any:
        return dispatch_action(session, actor_id, action_name, params, confirm=confirm)
    return dispatch_tool


def _make_list_expiring() -> Tool:
    def list_expiring(session: Session, *, actor_id: int, within_days: int = 30) -> list[dict[str, Any]]:
        return dispatch_function(session, actor_id, "list_expiring", {"within_days": within_days})
    return list_expiring


def perishable_toolset() -> DomainToolset:
    return toolset_for_domain(ItemDomain.PERISHABLE)


def cards_docs_toolset() -> DomainToolset:
    return toolset_for_domain(ItemDomain.CARDS_DOCS)


def equipment_toolset() -> DomainToolset:
    return toolset_for_domain(ItemDomain.EQUIPMENT)


def all_toolsets() -> list[DomainToolset]:
    return [perishable_toolset(), cards_docs_toolset(), equipment_toolset()]


def assert_tool_isolation() -> None:
    for toolset in all_toolsets():
        toolset.assert_isolated()
