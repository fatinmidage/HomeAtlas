"""Ontology Schema Registry — central declaration of Object Types, Link Types, and Action Types.

All consumers (AI Agent, Toolset, validation logic) derive from this registry
rather than hard-coding domain knowledge.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from home_atlas.models import EventAction, ItemDomain, ItemKind, domain_for_kind
from home_atlas.property_schemas import validate_item_properties
from home_atlas.security import HomeAtlasError


@dataclass(frozen=True)
class PropertyDef:
    name: str
    python_type: type
    required: bool = False
    secret: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.python_type.__name__,
            "required": self.required,
            "secret": self.secret,
            "description": self.description,
        }


@dataclass(frozen=True)
class ObjectTypeDef:
    api_name: str
    item_kind: ItemKind
    domain: ItemDomain
    typed_properties: tuple[PropertyDef, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "item_kind": self.item_kind.value,
            "domain": self.domain.value,
            "typed_properties": [p.to_dict() for p in self.typed_properties],
            "description": self.description,
        }


@dataclass(frozen=True)
class LinkTypeDef:
    api_name: str
    source_type: str
    target_type: str
    fk_column: str
    cardinality: str = "many-to-one"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "fk_column": self.fk_column,
            "cardinality": self.cardinality,
            "description": self.description,
        }


@dataclass(frozen=True)
class ActionParameterDef:
    name: str
    python_type: type
    required: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.python_type.__name__,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class ActionTypeDef:
    api_name: str
    event_action: EventAction
    applicable_to: frozenset[ItemKind] = field(default_factory=lambda: frozenset(ItemKind))
    parameters: tuple[ActionParameterDef, ...] = ()
    requires_confirm: bool = False
    description: str = ""
    implementation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "event_action": self.event_action.value,
            "applicable_to": sorted(k.value for k in self.applicable_to),
            "parameters": [p.to_dict() for p in self.parameters],
            "requires_confirm": self.requires_confirm,
            "description": self.description,
        }


@dataclass
class OntologyRegistry:
    object_types: dict[str, ObjectTypeDef] = field(default_factory=dict)
    link_types: dict[str, LinkTypeDef] = field(default_factory=dict)
    action_types: dict[str, ActionTypeDef] = field(default_factory=dict)

    def register_object_type(self, obj: ObjectTypeDef) -> None:
        self.object_types[obj.api_name] = obj

    def register_link_type(self, link: LinkTypeDef) -> None:
        self.link_types[link.api_name] = link

    def register_action_type(self, action: ActionTypeDef) -> None:
        self.action_types[action.api_name] = action

    def object_types_for_domain(self, domain: ItemDomain) -> list[ObjectTypeDef]:
        return [ot for ot in self.object_types.values() if ot.domain == domain]

    def object_type_for_kind(self, kind: ItemKind) -> ObjectTypeDef | None:
        for ot in self.object_types.values():
            if ot.item_kind == kind:
                return ot
        return None

    def actions_for_object_type(self, api_name: str) -> list[ActionTypeDef]:
        ot = self.object_types.get(api_name)
        if ot is None:
            return []
        return [
            at for at in self.action_types.values()
            if ot.item_kind in at.applicable_to
        ]

    def validate_properties(self, api_name: str, properties: dict[str, Any]) -> dict[str, Any]:
        ot = self.object_types.get(api_name)
        if ot is None:
            raise HomeAtlasError(f"unknown object type: {api_name}")
        return validate_item_properties(ot.item_kind, properties)

    def resolve_action(self, api_name: str) -> Any:
        at = self.action_types.get(api_name)
        if at is None or not at.implementation:
            raise HomeAtlasError(f"no implementation for action: {api_name}")
        module_path, _, attr = at.implementation.rpartition(".")
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    def action_parameter_schema(self, api_name: str) -> dict[str, Any]:
        at = self.action_types.get(api_name)
        if at is None:
            raise HomeAtlasError(f"unknown action type: {api_name}")
        return {
            p.name: {"type": p.python_type.__name__, "required": p.required, "description": p.description}
            for p in at.parameters
        }

    def describe_for_llm(self, domain: ItemDomain | None = None) -> str:
        parts: list[str] = []
        ots = (
            self.object_types_for_domain(domain)
            if domain
            else list(self.object_types.values())
        )
        for ot in ots:
            props_desc = ", ".join(
                f"{p.name}({'required' if p.required else 'optional'}, {p.python_type.__name__})"
                for p in ot.typed_properties
            )
            actions = self.actions_for_object_type(ot.api_name)
            actions_desc = ", ".join(a.api_name for a in actions)
            parts.append(
                f"## {ot.api_name}\n"
                f"Kind: {ot.item_kind.value}, Domain: {ot.domain.value}\n"
                f"{ot.description}\n"
                f"Properties: {props_desc or '(none)'}\n"
                f"Actions: {actions_desc or '(none)'}"
            )
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "object_types": [ot.to_dict() for ot in self.object_types.values()],
            "link_types": [lt.to_dict() for lt in self.link_types.values()],
            "action_types": [at.to_dict() for at in self.action_types.values()],
        }

    def describe_links_for_llm(self) -> str:
        lines: list[str] = []
        for lt in self.link_types.values():
            lines.append(
                f"- {lt.api_name}: {lt.source_type} —[{lt.fk_column}]→ {lt.target_type} "
                f"({lt.cardinality}) — {lt.description}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

_OBJECT_TYPES: list[ObjectTypeDef] = [
    ObjectTypeDef(
        api_name="Food",
        item_kind=ItemKind.FOOD,
        domain=ItemDomain.PERISHABLE,
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("weight", str, description="重量/容量"),
        ),
        description="食品 — 有保质期的消耗品",
    ),
    ObjectTypeDef(
        api_name="Medicine",
        item_kind=ItemKind.MEDICINE,
        domain=ItemDomain.PERISHABLE,
        typed_properties=(
            PropertyDef("dosage", str, description="剂量"),
            PropertyDef("prescription", bool, description="是否处方药"),
        ),
        description="药品 — 有保质期的医药用品",
    ),
    ObjectTypeDef(
        api_name="InsurancePolicy",
        item_kind=ItemKind.INSURANCE_POLICY,
        domain=ItemDomain.CARDS_DOCS,
        typed_properties=(
            PropertyDef("policy_number", str, description="保单号"),
            PropertyDef("provider", str, description="保险公司"),
        ),
        description="保险保单",
    ),
    ObjectTypeDef(
        api_name="PaymentCard",
        item_kind=ItemKind.PAYMENT_CARD,
        domain=ItemDomain.CARDS_DOCS,
        typed_properties=(
            PropertyDef("issuer", str, description="发卡行"),
            PropertyDef("card_type", str, description="卡类型 (credit/debit)"),
            PropertyDef("last4", str, description="卡号后四位"),
            PropertyDef("expiry_my", str, description="有效期 MM/YY"),
            PropertyDef("physical_location", str, description="实体卡存放位置"),
        ),
        description="银行卡/信用卡（仅存引用信息，禁止存储完整卡号和CVV）",
    ),
    ObjectTypeDef(
        api_name="MembershipCard",
        item_kind=ItemKind.MEMBERSHIP_CARD,
        domain=ItemDomain.CARDS_DOCS,
        typed_properties=(
            PropertyDef("member_id", str, description="会员号"),
            PropertyDef("issuer", str, description="发行方"),
        ),
        description="会员卡",
    ),
    ObjectTypeDef(
        api_name="Document",
        item_kind=ItemKind.DOCUMENT,
        domain=ItemDomain.CARDS_DOCS,
        typed_properties=(
            PropertyDef("document_number", str, description="证件号"),
            PropertyDef("issuing_authority", str, description="签发机关"),
        ),
        description="证件/文书",
    ),
    ObjectTypeDef(
        api_name="Tool",
        item_kind=ItemKind.TOOL,
        domain=ItemDomain.EQUIPMENT,
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("model", str, description="型号"),
        ),
        description="工具",
    ),
    ObjectTypeDef(
        api_name="Appliance",
        item_kind=ItemKind.APPLIANCE,
        domain=ItemDomain.EQUIPMENT,
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("model", str, description="型号"),
            PropertyDef("warranty_expiry", date, description="保修到期日"),
        ),
        description="家电",
    ),
    ObjectTypeDef(
        api_name="Other",
        item_kind=ItemKind.OTHER,
        domain=ItemDomain.OTHER,
        description="其他物品",
    ),
]

_LINK_TYPES: list[LinkTypeDef] = [
    LinkTypeDef("storedAt", "Item", "Location", "location_id", "many-to-one", "物品存放在哪个位置"),
    LinkTypeDef("addedBy", "Item", "Person", "added_by_id", "many-to-one", "谁添加了这个物品"),
    LinkTypeDef("updatedBy", "Item", "Person", "updated_by_id", "many-to-one", "谁最后更新了这个物品"),
    LinkTypeDef("parentLocation", "Location", "Location", "parent_id", "many-to-one", "位置的父级位置"),
    LinkTypeDef("itemEvents", "Item", "Event", "item_id", "one-to-many", "物品的事件历史"),
    LinkTypeDef("actorEvents", "Person", "Event", "actor_id", "one-to-many", "某人的操作历史"),
]

_ALL_KINDS = frozenset(ItemKind)
_PERISHABLE_KINDS = frozenset({ItemKind.FOOD, ItemKind.MEDICINE})
_CARDS_DOCS_KINDS = frozenset({ItemKind.INSURANCE_POLICY, ItemKind.PAYMENT_CARD, ItemKind.MEMBERSHIP_CARD, ItemKind.DOCUMENT})
_EQUIPMENT_KINDS = frozenset({ItemKind.TOOL, ItemKind.APPLIANCE})

_ACTION_TYPES: list[ActionTypeDef] = [
    ActionTypeDef(
        api_name="AddItem",
        event_action=EventAction.ADD_ITEM,
        applicable_to=_ALL_KINDS,
        parameters=(
            ActionParameterDef("name", str, True, "物品名称"),
            ActionParameterDef("kind", ItemKind, True, "物品类型"),
            ActionParameterDef("location_name", str, True, "存放位置"),
            ActionParameterDef("quantity", float, False, "数量"),
            ActionParameterDef("unit", str, False, "单位"),
        ),
        description="添加新物品",
        implementation="home_atlas.actions.add_item",
    ),
    ActionTypeDef(
        api_name="MoveItem",
        event_action=EventAction.MOVE_ITEM,
        applicable_to=_ALL_KINDS,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
            ActionParameterDef("location_name", str, True, "目标位置"),
        ),
        description="移动物品到新位置",
        implementation="home_atlas.actions.move_item",
    ),
    ActionTypeDef(
        api_name="AdjustQuantity",
        event_action=EventAction.ADJUST_QUANTITY,
        applicable_to=_PERISHABLE_KINDS,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
            ActionParameterDef("delta", float, True, "数量变化量"),
        ),
        description="调整物品数量（增减）",
        implementation="home_atlas.actions.adjust_quantity",
    ),
    ActionTypeDef(
        api_name="SetQuantity",
        event_action=EventAction.SET_QUANTITY,
        applicable_to=_PERISHABLE_KINDS,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
            ActionParameterDef("quantity", float, True, "目标数量"),
        ),
        description="设置物品绝对数量",
        implementation="home_atlas.actions.set_quantity",
    ),
    ActionTypeDef(
        api_name="UpdateItem",
        event_action=EventAction.UPDATE_ITEM,
        applicable_to=_ALL_KINDS,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
        ),
        requires_confirm=True,
        description="更新物品属性",
        implementation="home_atlas.actions.update_item",
    ),
    ActionTypeDef(
        api_name="UpsertCardReference",
        event_action=EventAction.UPSERT_CARD_REFERENCE,
        applicable_to=_CARDS_DOCS_KINDS,
        parameters=(
            ActionParameterDef("name", str, True, "卡/证件名称"),
            ActionParameterDef("location_name", str, True, "存放位置"),
            ActionParameterDef("card_type", ItemKind, True, "卡/证件类型"),
            ActionParameterDef("properties", dict, True, "引用属性"),
        ),
        description="新增或更新卡/证件引用",
        implementation="home_atlas.actions.upsert_card_reference",
    ),
    ActionTypeDef(
        api_name="DiscardItem",
        event_action=EventAction.DISCARD_ITEM,
        applicable_to=_ALL_KINDS,
        requires_confirm=True,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
        ),
        description="归档/丢弃物品",
        implementation="home_atlas.actions.discard_item",
    ),
]


def build_registry() -> OntologyRegistry:
    registry = OntologyRegistry()
    for ot in _OBJECT_TYPES:
        assert ot.domain == domain_for_kind(ot.item_kind)
        registry.register_object_type(ot)
    for lt in _LINK_TYPES:
        registry.register_link_type(lt)
    for at in _ACTION_TYPES:
        registry.register_action_type(at)
    return registry


@functools.lru_cache(maxsize=1)
def get_registry() -> OntologyRegistry:
    return build_registry()
