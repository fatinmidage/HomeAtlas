from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from home_atlas.agents import run_ai_home_atlas, should_use_ai
from home_atlas.config import Settings
from home_atlas.dispatcher import dispatch_action, dispatch_function
from home_atlas.llm_config import ACTIVE_LLM, has_configured_api_key
from home_atlas.models import ItemDomain, ItemKind
from home_atlas.ontology import get_registry
from home_atlas.toolsets import cards_docs_toolset, equipment_toolset, perishable_toolset


@dataclass(frozen=True)
class RoutedRequest:
    domain: str
    intent: str
    args: dict[str, Any]


INTENT_WORDS = {"过期", "临期"}


def route_request(request: str) -> RoutedRequest:
    request = request.strip()
    if not request:
        raise ValueError("request cannot be empty")

    if _is_list_items_request(request):
        return RoutedRequest(domain="global", intent="list_items", args={})
    if "上次谁动" in request or "谁动了" in request:
        return RoutedRequest(domain="global", intent="last_touched", args={"name": _extract_object_name(request)})
    if "在哪" in request or "哪里" in request:
        return RoutedRequest(domain="global", intent="where_is", args={"name": _extract_object_name(request)})
    if "临期" in request or "过期" in request or "待续费" in request:
        return RoutedRequest(domain="global", intent="list_expiring", args={"within_days": _extract_days(request) or 30})
    move = re.search(r"把(.+?)放(?:进|到|在)(.+)", request)
    if move:
        item_name = move.group(1).strip()
        location_name = move.group(2).strip(" 。.").strip()
        return RoutedRequest(
            domain=_classify_domain(item_name),
            intent="put_item",
            args={"name": item_name, "location_name": location_name},
        )
    return RoutedRequest(domain=_classify_domain(request), intent="search", args={"query": request})


def home_atlas(request: str, session: Session, actor_id: int, settings: Settings | None = None) -> dict[str, Any]:
    if settings is not None and _needs_llm_configuration_notice(settings):
        return _llm_configuration_notice(settings)
    if settings is not None and should_use_ai(settings):
        return run_ai_home_atlas(request, session, actor_id, settings)
    routed = route_request(request)
    if routed.intent == "where_is":
        item = dispatch_function(session, actor_id, "where_is", {"name": routed.args["name"]})
        answer = f"{item['name']} 在 {item['location']}"
        if item.get("match_note"):
            answer = f"{answer}（{item['match_note']}）"
        return {"intent": routed.intent, "answer": answer, "item": item}
    if routed.intent == "last_touched":
        event = dispatch_function(session, actor_id, "last_touched", {"name": routed.args["name"]})
        return {
            "intent": routed.intent,
            "answer": f"{event['item']} 上次由 {event['actor']} 执行 {event['action']}",
            "event": event,
        }
    if routed.intent == "list_expiring":
        items = dispatch_function(session, actor_id, "list_expiring", {"within_days": routed.args["within_days"]})
        return {"intent": routed.intent, "items": items}
    if routed.intent == "list_items":
        return {"intent": routed.intent, "items": dispatch_function(session, actor_id, "search_items", {})}
    if routed.intent == "put_item":
        return _put_item(session, actor_id, routed)
    if routed.intent == "search":
        return {
            "intent": routed.intent,
            "items": dispatch_function(session, actor_id, "search_items", {"query": routed.args["query"]}),
        }
    raise ValueError(f"unsupported intent: {routed.intent}")


def _needs_llm_configuration_notice(settings: Settings) -> bool:
    if settings.agent_mode == "rules":
        return False
    return not has_configured_api_key(settings.llm_api_key)


def _llm_configuration_notice(settings: Settings) -> dict[str, Any]:
    return {
        "intent": "configuration_required",
        "agent_mode": settings.agent_mode,
        "answer": (
            "HomeAtlas 还没有配置 LLM API key，所以无法使用 AI 来理解和分流你的库存请求。"
            f"请在 .env 里设置 {ACTIVE_LLM.app_api_key_env} 或 {ACTIVE_LLM.provider_api_key_env}，"
            "然后重启 HomeAtlas 服务。"
            "如果你只是想临时使用规则引擎，请把 HOME_ATLAS_AGENT_MODE 设置为 rules。"
        ),
        "missing": [ACTIVE_LLM.app_api_key_env],
    }


def _put_item(session: Session, actor_id: int, routed: RoutedRequest) -> dict[str, Any]:
    existing = dispatch_function(session, actor_id, "search_items", {"query": routed.args["name"]})
    exact = [item for item in existing if item["name"] == routed.args["name"]]
    if exact:
        item = dispatch_action(
            session,
            actor_id,
            "MoveItem",
            {"item_id": exact[0]["id"], "location_name": routed.args["location_name"]},
        )
        return {"intent": "move_item", "domain": routed.domain, "item_id": item.id}

    if routed.domain == "perishables":
        tool = perishable_toolset().tools["perishable_add_item"]
        item = tool(session, actor_id=actor_id, name=routed.args["name"], location_name=routed.args["location_name"])
    elif routed.domain == "equipment":
        tool = equipment_toolset().tools["equipment_add_item"]
        item = tool(session, actor_id=actor_id, name=routed.args["name"], location_name=routed.args["location_name"])
    elif routed.domain == "cards_docs":
        tool = cards_docs_toolset().tools["card_add_item"]
        item = tool(
            session,
            actor_id=actor_id,
            name=routed.args["name"],
            location_name=routed.args["location_name"],
            kind=ItemKind.DOCUMENT,
        )
    else:
        item = dispatch_action(
            session,
            actor_id,
            "AddItem",
            {"name": routed.args["name"], "location_name": routed.args["location_name"], "kind": ItemKind.OTHER},
        )
    return {"intent": "add_item", "domain": routed.domain, "item_id": item.id}


def _classify_domain(text: str) -> str:
    registry = get_registry()
    domain_mapping = {
        ItemDomain.PERISHABLE: "perishables",
        ItemDomain.CARDS_DOCS: "cards_docs",
        ItemDomain.EQUIPMENT: "equipment",
        ItemDomain.OTHER: "other",
    }
    for domain, label in domain_mapping.items():
        keywords = registry.keywords_for_domain(domain)
        if any(word in text for word in keywords):
            return label
    return "other"


def _extract_object_name(request: str) -> str:
    cleaned = request.strip(" ?？。.")
    cleaned = cleaned.replace("上次谁动了", "").replace("上次谁动", "")
    cleaned = cleaned.replace("谁动了", "").replace("在哪", "").replace("在哪里", "").replace("哪里", "")
    return cleaned.strip() or request.strip()


def _extract_days(request: str) -> int | None:
    match = re.search(r"(\d+)\s*天", request)
    return int(match.group(1)) if match else None


def _is_list_items_request(request: str) -> bool:
    cleaned = request.strip(" ?？。.")
    list_words = ("有什么", "有哪些", "列出", "清单", "库存", "盘点", "所有物品", "全部物品")
    inventory_words = ("物品", "东西", "库存", "清单")
    return any(word in cleaned for word in list_words) and any(word in cleaned for word in inventory_words)
