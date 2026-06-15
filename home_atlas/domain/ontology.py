"""Ontology Schema Registry — central declaration of Object Types, Link Types, and Action Types.

All consumers (AI Agent, Toolset, validation logic) derive from this registry
rather than hard-coding domain knowledge.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from home_atlas.core.security import HomeAtlasError
from home_atlas.domain.models import Event, EventAction, Item, ItemDomain, ItemKind, Location, Person, domain_for_kind


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
    item_kind: ItemKind | None = None
    domain: ItemDomain | None = None
    table: str = ""
    primary_key: str = "id"
    title_property: str = "name"
    parent: str | None = None
    typed_properties: tuple[PropertyDef, ...] = ()
    keywords: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "item_kind": self.item_kind.value if self.item_kind else None,
            "domain": self.domain.value if self.domain else None,
            "table": self.table,
            "primary_key": self.primary_key,
            "title_property": self.title_property,
            "parent": self.parent,
            "typed_properties": [p.to_dict() for p in self.typed_properties],
            "keywords": list(self.keywords),
            "description": self.description,
        }


@dataclass(frozen=True)
class LinkTypeDef:
    api_name: str
    source_type: str
    target_type: str
    fk_column: str
    cardinality: str = "many-to-one"
    inverse_name: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "fk_column": self.fk_column,
            "cardinality": self.cardinality,
            "inverse_name": self.inverse_name,
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
class AIToolDef:
    domain: ItemDomain
    name: str
    parameter_names: tuple[str, ...] = ()
    parameters: tuple[ActionParameterDef, ...] = ()
    defaults: dict[str, Any] = field(default_factory=dict)
    constants: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    adapter: str = ""


@dataclass(frozen=True)
class ActionTypeDef:
    api_name: str
    event_action: EventAction
    applicable_to: frozenset[ItemKind] = field(default_factory=lambda: frozenset(ItemKind))
    parameters: tuple[ActionParameterDef, ...] = ()
    requires_confirm: bool = False
    description: str = ""
    implementation: str = ""
    required_role: str = "member"
    ai_tools: tuple[AIToolDef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "event_action": self.event_action.value,
            "applicable_to": sorted(k.value for k in self.applicable_to),
            "parameters": [p.to_dict() for p in self.parameters],
            "requires_confirm": self.requires_confirm,
            "description": self.description,
        }


@dataclass(frozen=True)
class FunctionDef:
    api_name: str
    parameters: tuple[ActionParameterDef, ...] = ()
    implementation: str = ""
    description: str = ""
    required_role: str = "viewer"
    ai_tools: tuple[AIToolDef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "parameters": [p.to_dict() for p in self.parameters],
            "description": self.description,
            "required_role": self.required_role,
        }


@dataclass
class OntologyRegistry:
    schema_version: int = 2
    object_types: dict[str, ObjectTypeDef] = field(default_factory=dict)
    link_types: dict[str, LinkTypeDef] = field(default_factory=dict)
    action_types: dict[str, ActionTypeDef] = field(default_factory=dict)
    function_defs: dict[str, FunctionDef] = field(default_factory=dict)

    def register_object_type(self, obj: ObjectTypeDef) -> None:
        self.object_types[obj.api_name] = obj

    def register_link_type(self, link: LinkTypeDef) -> None:
        self.link_types[link.api_name] = link

    def register_action_type(self, action: ActionTypeDef) -> None:
        self.action_types[action.api_name] = action

    def register_function(self, function: FunctionDef) -> None:
        self.function_defs[function.api_name] = function

    def object_types_for_domain(self, domain: ItemDomain) -> list[ObjectTypeDef]:
        return [ot for ot in self.object_types.values() if ot.domain == domain]

    def object_type_for_kind(self, kind: ItemKind) -> ObjectTypeDef | None:
        for ot in self.object_types.values():
            if ot.item_kind == kind:
                return ot
        return None

    def keywords_for_domain(self, domain: ItemDomain) -> set[str]:
        result: set[str] = set()
        for ot in self.object_types.values():
            if ot.domain == domain:
                result.update(ot.keywords)
        return result

    def actions_for_object_type(self, api_name: str) -> list[ActionTypeDef]:
        ot = self.object_types.get(api_name)
        if ot is None:
            return []
        return [
            at for at in self.action_types.values()
            if ot.item_kind is not None and ot.item_kind in at.applicable_to
        ]

    def validate_properties(self, api_name: str, properties: dict[str, Any]) -> dict[str, Any]:
        ot = self.object_types.get(api_name)
        if ot is None or ot.item_kind is None:
            raise HomeAtlasError(f"unknown object type: {api_name}")
        from home_atlas.domain.property_schemas import validate_item_properties
        return validate_item_properties(ot.item_kind, properties)

    def resolve_action(self, api_name: str) -> Any:
        at = self.action_types.get(api_name)
        if at is None or not at.implementation:
            raise HomeAtlasError(f"no implementation for action: {api_name}")
        module_path, _, attr = at.implementation.rpartition(".")
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    def resolve_function(self, api_name: str) -> Any:
        fn = self.function_defs.get(api_name)
        if fn is None or not fn.implementation:
            raise HomeAtlasError(f"no implementation for function: {api_name}")
        module_path, _, attr = fn.implementation.rpartition(".")
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    _ROLE_HIERARCHY = {"admin": 2, "member": 1, "viewer": 0}

    def check_permission(self, action_api_name: str, person_roles: list[str]) -> bool:
        at = self.action_types.get(action_api_name)
        if at is None:
            return False
        required_level = self._ROLE_HIERARCHY.get(at.required_role, 1)
        person_level = max(
            (self._ROLE_HIERARCHY.get(r, 0) for r in person_roles),
            default=0,
        )
        return person_level >= required_level

    def check_function_permission(self, function_api_name: str, person_roles: list[str]) -> bool:
        fn = self.function_defs.get(function_api_name)
        if fn is None:
            return False
        required_level = self._ROLE_HIERARCHY.get(fn.required_role, 0)
        person_level = max(
            (self._ROLE_HIERARCHY.get(r, 0) for r in person_roles),
            default=0,
        )
        return person_level >= required_level

    def shortest_path(self, source_type: str, target_type: str) -> list[str]:
        from collections import deque
        if source_type == target_type:
            return []
        adj: dict[str, list[tuple[str, str]]] = {}
        for lt in self.link_types.values():
            adj.setdefault(lt.source_type, []).append((lt.target_type, lt.api_name))
            if lt.inverse_name:
                adj.setdefault(lt.target_type, []).append((lt.source_type, lt.inverse_name))
        queue: deque[tuple[str, list[str]]] = deque([(source_type, [])])
        visited: set[str] = {source_type}
        while queue:
            current, path = queue.popleft()
            for neighbor, link_name in adj.get(current, []):
                if neighbor == target_type:
                    return path + [link_name]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [link_name]))
        raise HomeAtlasError(f"no link path from {source_type} to {target_type}")

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
                f"{p.name}({'required' if p.required else 'optional'}, {p.python_type.__name__}{', secret' if p.secret else ''})"
                for p in ot.typed_properties
            )
            actions = self.actions_for_object_type(ot.api_name)
            actions_desc = ", ".join(a.api_name for a in actions)
            parts.append(
                f"## {ot.api_name}\n"
                f"Kind: {ot.item_kind.value if ot.item_kind else '(none)'}, "
                f"Domain: {ot.domain.value if ot.domain else '(none)'}, "
                f"Table: {ot.table or '(none)'}\n"
                f"{ot.description}\n"
                f"Properties: {props_desc or '(none)'}\n"
                f"Actions: {actions_desc or '(none)'}"
            )
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "object_types": [ot.to_dict() for ot in self.object_types.values()],
            "link_types": [lt.to_dict() for lt in self.link_types.values()],
            "action_types": [at.to_dict() for at in self.action_types.values()],
            "function_defs": [fn.to_dict() for fn in self.function_defs.values()],
        }

    def describe_links_for_llm(self) -> str:
        lines: list[str] = []
        for lt in self.link_types.values():
            lines.append(
                f"- {lt.api_name}: {lt.source_type} —[{lt.fk_column}]→ {lt.target_type} "
                f"({lt.cardinality}) — {lt.description}"
            )
        return "\n".join(lines)

    def validate_links(self) -> None:
        model_map = {"Item": Item, "Location": Location, "Person": Person, "Event": Event}
        for link in self.link_types.values():
            if link.source_type not in self.object_types:
                raise HomeAtlasError(f"link {link.api_name} source type is not registered: {link.source_type}")
            if link.target_type not in self.object_types:
                raise HomeAtlasError(f"link {link.api_name} target type is not registered: {link.target_type}")
            owner_type = link.target_type if link.cardinality == "one-to-many" else link.source_type
            owner = model_map.get(owner_type)
            if owner is None or not hasattr(owner, link.fk_column):
                raise HomeAtlasError(f"link {link.api_name} fk column not found: {owner_type}.{link.fk_column}")


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

_OBJECT_TYPES: list[ObjectTypeDef] = [
    ObjectTypeDef(
        api_name="Item",
        table="item",
        description="所有库存物品的基类型",
    ),
    ObjectTypeDef(
        api_name="Person",
        table="person",
        description="家庭成员 / 操作 actor",
    ),
    ObjectTypeDef(
        api_name="Location",
        table="location",
        description="家庭中的存放位置",
    ),
    ObjectTypeDef(
        api_name="Event",
        table="event",
        description="审计事件",
    ),
    ObjectTypeDef(
        api_name="Food",
        item_kind=ItemKind.FOOD,
        domain=ItemDomain.PERISHABLE,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("weight", str, description="重量/容量"),
        ),
        keywords=("食物", "食品", "牛奶", "鸡蛋"),
        description="食品 — 有保质期的消耗品",
    ),
    ObjectTypeDef(
        api_name="Medicine",
        item_kind=ItemKind.MEDICINE,
        domain=ItemDomain.PERISHABLE,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("dosage", str, description="剂量"),
            PropertyDef("prescription", bool, description="是否处方药"),
        ),
        keywords=("药", "药品"),
        description="药品 — 有保质期的医药用品",
    ),
    ObjectTypeDef(
        api_name="InsurancePolicy",
        item_kind=ItemKind.INSURANCE_POLICY,
        domain=ItemDomain.CARDS_DOCS,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("policy_number", str, secret=True, description="保单号"),
            PropertyDef("provider", str, description="保险公司"),
        ),
        keywords=("保险", "保单"),
        description="保险保单",
    ),
    ObjectTypeDef(
        api_name="PaymentCard",
        item_kind=ItemKind.PAYMENT_CARD,
        domain=ItemDomain.CARDS_DOCS,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("issuer", str, description="发卡行"),
            PropertyDef("card_type", str, description="卡类型 (credit/debit)"),
            PropertyDef("last4", str, description="卡号后四位"),
            PropertyDef("expiry_my", str, description="有效期 MM/YY"),
            PropertyDef("physical_location", str, description="实体卡存放位置"),
        ),
        keywords=("信用卡",),
        description="银行卡/信用卡（仅存引用信息，禁止存储完整卡号和CVV）",
    ),
    ObjectTypeDef(
        api_name="MembershipCard",
        item_kind=ItemKind.MEMBERSHIP_CARD,
        domain=ItemDomain.CARDS_DOCS,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("member_id", str, secret=True, description="会员号"),
            PropertyDef("issuer", str, description="发行方"),
        ),
        keywords=("会员卡",),
        description="会员卡",
    ),
    ObjectTypeDef(
        api_name="Document",
        item_kind=ItemKind.DOCUMENT,
        domain=ItemDomain.CARDS_DOCS,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("document_number", str, secret=True, description="证件号"),
            PropertyDef("issuing_authority", str, description="签发机关"),
        ),
        keywords=("护照", "证件", "卡"),
        description="证件/文书",
    ),
    ObjectTypeDef(
        api_name="Tool",
        item_kind=ItemKind.TOOL,
        domain=ItemDomain.EQUIPMENT,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("model", str, description="型号"),
        ),
        keywords=("工具", "螺丝刀"),
        description="工具",
    ),
    ObjectTypeDef(
        api_name="Appliance",
        item_kind=ItemKind.APPLIANCE,
        domain=ItemDomain.EQUIPMENT,
        table="item",
        parent="Item",
        typed_properties=(
            PropertyDef("brand", str, description="品牌"),
            PropertyDef("model", str, description="型号"),
            PropertyDef("warranty_expiry", date, description="保修到期日"),
        ),
        keywords=("电器", "冰箱", "洗衣机", "设备"),
        description="家电",
    ),
    ObjectTypeDef(
        api_name="Other",
        item_kind=ItemKind.OTHER,
        domain=ItemDomain.OTHER,
        table="item",
        parent="Item",
        description="其他物品",
    ),
]

_LINK_TYPES: list[LinkTypeDef] = [
    LinkTypeDef("storedAt", "Item", "Location", "location_id", "many-to-one", "itemsStored", "物品存放在哪个位置"),
    LinkTypeDef("addedBy", "Item", "Person", "added_by_id", "many-to-one", "itemsAdded", "谁添加了这个物品"),
    LinkTypeDef("updatedBy", "Item", "Person", "updated_by_id", "many-to-one", "itemsUpdated", "谁最后更新了这个物品"),
    LinkTypeDef("parentLocation", "Location", "Location", "parent_id", "many-to-one", "childLocations", "位置的父级位置"),
    LinkTypeDef("itemEvents", "Item", "Event", "item_id", "one-to-many", "eventItem", "物品的事件历史"),
    LinkTypeDef("actorEvents", "Person", "Event", "actor_id", "one-to-many", "eventActor", "某人的操作历史"),
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
            ActionParameterDef("expiry_date", date, False, "过期日期"),
            ActionParameterDef("renewal_date", date, False, "续费日期"),
            ActionParameterDef("purchase_date", date, False, "购买日期"),
            ActionParameterDef("properties", dict, False, "类型属性"),
            ActionParameterDef("notes", str, False, "备注"),
        ),
        description="添加新物品",
        implementation="home_atlas.app.actions.add_item",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.PERISHABLE,
                name="perishable_add_item",
                parameter_names=("name", "location_name", "kind", "quantity", "unit", "expiry_date", "purchase_date"),
                defaults={"kind": ItemKind.FOOD},
                description="Add or update food or medicine in a household location, including optional expiry and purchase dates.",
            ),
            AIToolDef(
                domain=ItemDomain.CARDS_DOCS,
                name="card_add_document",
                parameter_names=("name", "location_name"),
                constants={"kind": ItemKind.DOCUMENT},
                description="Add a document such as a passport, certificate, or policy reference.",
            ),
            AIToolDef(
                domain=ItemDomain.EQUIPMENT,
                name="equipment_add_item",
                parameter_names=("name", "location_name", "kind"),
                defaults={"kind": ItemKind.TOOL},
                description="Add a tool or appliance to a household location.",
            ),
        ),
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
        implementation="home_atlas.app.actions.move_item",
    ),
    ActionTypeDef(
        api_name="CreateLocation",
        event_action=EventAction.CREATE_LOCATION,
        applicable_to=frozenset(),
        parameters=(
            ActionParameterDef("name", str, True, "位置名称"),
            ActionParameterDef("parent_name", str, False, "父级位置名称"),
            ActionParameterDef("notes", str, False, "备注"),
        ),
        description="创建家庭位置",
        implementation="home_atlas.app.actions.create_location",
    ),
    ActionTypeDef(
        api_name="RenameLocation",
        event_action=EventAction.RENAME_LOCATION,
        applicable_to=frozenset(),
        parameters=(
            ActionParameterDef("name", str, True, "原位置名称"),
            ActionParameterDef("new_name", str, True, "新位置名称"),
        ),
        description="重命名家庭位置",
        implementation="home_atlas.app.actions.rename_location",
    ),
    ActionTypeDef(
        api_name="UpdateLocation",
        event_action=EventAction.UPDATE_LOCATION,
        applicable_to=frozenset(),
        parameters=(
            ActionParameterDef("name", str, True, "位置名称"),
            ActionParameterDef("parent_name", str, False, "父级位置名称"),
            ActionParameterDef("notes", str, False, "备注"),
        ),
        description="更新家庭位置的父级或备注",
        implementation="home_atlas.app.actions.update_location",
    ),
    ActionTypeDef(
        api_name="DeleteLocation",
        event_action=EventAction.DELETE_LOCATION,
        applicable_to=frozenset(),
        requires_confirm=True,
        parameters=(
            ActionParameterDef("name", str, True, "位置名称"),
        ),
        description="删除没有物品和子位置的家庭位置",
        implementation="home_atlas.app.actions.delete_location",
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
        implementation="home_atlas.app.actions.adjust_quantity",
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
        implementation="home_atlas.app.actions.set_quantity",
    ),
    ActionTypeDef(
        api_name="UpdateItem",
        event_action=EventAction.UPDATE_ITEM,
        applicable_to=_ALL_KINDS,
        parameters=(
            ActionParameterDef("item_id", int, True, "物品 ID"),
            ActionParameterDef("name", str, False, "物品名称"),
            ActionParameterDef("kind", ItemKind, False, "物品类型"),
            ActionParameterDef("location_id", int, False, "位置 ID"),
            ActionParameterDef("quantity", float, False, "数量"),
            ActionParameterDef("unit", str, False, "单位"),
            ActionParameterDef("expiry_date", date, False, "过期日期"),
            ActionParameterDef("renewal_date", date, False, "续费日期"),
            ActionParameterDef("purchase_date", date, False, "购买日期"),
            ActionParameterDef("properties", dict, False, "类型属性"),
            ActionParameterDef("notes", str, False, "备注"),
            ActionParameterDef("archived", bool, False, "是否归档"),
            ActionParameterDef("confirm", bool, False, "确认覆盖名称/属性等标识字段"),
        ),
        description="更新物品属性",
        implementation="home_atlas.app.actions.update_item",
        required_role="member",
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
        implementation="home_atlas.app.actions.upsert_card_reference",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.CARDS_DOCS,
                name="card_upsert_payment_reference",
                parameter_names=("name", "location_name", "issuer", "card_type", "last4", "expiry_my"),
                parameters=(
                    ActionParameterDef("name", str, True, "卡名称"),
                    ActionParameterDef("location_name", str, True, "存放位置"),
                    ActionParameterDef("issuer", str, True, "发卡机构"),
                    ActionParameterDef("card_type", str, True, "卡类型"),
                    ActionParameterDef("last4", str, True, "末四位"),
                    ActionParameterDef("expiry_my", str, False, "到期月/年"),
                ),
                description="Store a payment card reference using issuer, card type, last4, and optional expiry only.",
                adapter="home_atlas.app.agents._payment_card_reference_params",
            ),
        ),
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
        implementation="home_atlas.app.actions.discard_item",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.PERISHABLE,
                name="perishable_discard",
                parameter_names=("item_id",),
                description="Archive or discard a food or medicine item after the user says it is gone, used, eaten, or should be removed.",
            ),
            AIToolDef(
                domain=ItemDomain.CARDS_DOCS,
                name="card_discard",
                parameter_names=("item_id",),
                description="Archive or discard a card, document, policy, or certificate reference.",
            ),
            AIToolDef(
                domain=ItemDomain.EQUIPMENT,
                name="equipment_discard",
                parameter_names=("item_id",),
                description="Archive or discard a tool or appliance item.",
            ),
        ),
    ),
    ActionTypeDef(
        api_name="SetPersonRole",
        event_action=EventAction.SET_PERSON_ROLE,
        applicable_to=frozenset(),
        parameters=(
            ActionParameterDef("person_name", str, True, "成员姓名"),
            ActionParameterDef("role", str, True, "viewer/member/admin"),
        ),
        description="设置家庭成员角色",
        implementation="home_atlas.app.actions.set_person_role",
        required_role="admin",
    ),
]

_FUNCTION_DEFS: list[FunctionDef] = [
    FunctionDef(
        api_name="list_locations",
        parameters=(),
        implementation="home_atlas.app.actions.list_locations",
        description="列出家庭位置和树形层级",
    ),
    FunctionDef(
        api_name="search_items",
        parameters=(
            ActionParameterDef("query", str, False, "搜索关键词"),
            ActionParameterDef("kind", ItemKind, False, "物品类型"),
            ActionParameterDef("domain", ItemDomain, False, "领域"),
            ActionParameterDef("location", str, False, "位置关键词"),
            ActionParameterDef("expiring_within_days", int, False, "临期天数"),
            ActionParameterDef("include_archived", bool, False, "是否包含归档"),
            ActionParameterDef("property_filter", dict, False, "属性过滤"),
        ),
        implementation="home_atlas.app.actions.search_items",
        description="搜索库存物品",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.PERISHABLE,
                name="perishable_search",
                parameter_names=("query",),
                constants={"domain": ItemDomain.PERISHABLE},
                description="Search food and medicine inventory.",
            ),
            AIToolDef(
                domain=ItemDomain.CARDS_DOCS,
                name="card_search",
                parameter_names=("query",),
                constants={"domain": ItemDomain.CARDS_DOCS},
                description="Search documents, policies, payment cards, and membership cards.",
            ),
            AIToolDef(
                domain=ItemDomain.EQUIPMENT,
                name="equipment_search",
                parameter_names=("query",),
                constants={"domain": ItemDomain.EQUIPMENT},
                description="Search tools and appliances.",
            ),
        ),
    ),
    FunctionDef(
        api_name="where_is",
        parameters=(ActionParameterDef("name", str, True, "物品名称"),),
        implementation="home_atlas.app.actions.where_is",
        description="查询物品位置",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.CARDS_DOCS,
                name="card_where_is",
                parameter_names=("name",),
                description="Find where a document or card is stored.",
            ),
        ),
    ),
    FunctionDef(
        api_name="list_expiring",
        parameters=(ActionParameterDef("within_days", int, False, "临期天数"),),
        implementation="home_atlas.app.actions.list_expiring",
        description="列出即将过期或续费的物品",
        ai_tools=(
            AIToolDef(
                domain=ItemDomain.PERISHABLE,
                name="perishable_list_expiring",
                parameter_names=("within_days",),
                defaults={"within_days": 30},
                description="List food and medicine expiring within the given number of days.",
            ),
        ),
    ),
    FunctionDef(
        api_name="recent_activity",
        parameters=(ActionParameterDef("limit", int, False, "返回条数"),),
        implementation="home_atlas.app.actions.recent_activity",
        description="查看最近审计事件",
    ),
    FunctionDef(
        api_name="last_touched",
        parameters=(ActionParameterDef("name", str, True, "物品名称"),),
        implementation="home_atlas.app.actions.last_touched",
        description="查看物品最后一次操作",
    ),
]


def build_registry() -> OntologyRegistry:
    registry = OntologyRegistry()
    for ot in _OBJECT_TYPES:
        if ot.item_kind is not None:
            assert ot.domain == domain_for_kind(ot.item_kind)
        registry.register_object_type(ot)
    for lt in _LINK_TYPES:
        registry.register_link_type(lt)
    for at in _ACTION_TYPES:
        registry.register_action_type(at)
    for fn in _FUNCTION_DEFS:
        registry.register_function(fn)
    registry.validate_links()
    return registry


@functools.lru_cache(maxsize=1)
def get_registry() -> OntologyRegistry:
    return build_registry()
