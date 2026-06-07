from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from home_atlas import actions
from home_atlas.models import ItemKind
from home_atlas.toolsets import cards_docs_toolset, equipment_toolset, perishable_toolset


@dataclass(frozen=True)
class RoutedRequest:
    domain: str
    intent: str
    args: dict[str, Any]


PERISHABLE_WORDS = {"食物", "食品", "药", "药品", "过期", "临期", "牛奶", "鸡蛋"}
CARD_WORDS = {"护照", "保险", "信用卡", "会员卡", "卡", "保单", "证件"}
EQUIPMENT_WORDS = {"工具", "电器", "螺丝刀", "冰箱", "洗衣机", "设备"}


def route_request(request: str) -> RoutedRequest:
    request = request.strip()
    if not request:
        raise ValueError("request cannot be empty")

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


def home_atlas(request: str, session: Session, actor_id: int) -> dict[str, Any]:
    routed = route_request(request)
    if routed.intent == "where_is":
        item = actions.where_is(session, routed.args["name"])
        return {"intent": routed.intent, "answer": f"{item['name']} 在 {item['location']}", "item": item}
    if routed.intent == "last_touched":
        event = actions.last_touched(session, routed.args["name"])
        return {
            "intent": routed.intent,
            "answer": f"{event['item']} 上次由 {event['actor']} 执行 {event['action']}",
            "event": event,
        }
    if routed.intent == "list_expiring":
        items = actions.list_expiring(session, routed.args["within_days"])
        return {"intent": routed.intent, "items": items}
    if routed.intent == "put_item":
        return _put_item(session, actor_id, routed)
    if routed.intent == "search":
        return {"intent": routed.intent, "items": actions.search_items(session, query=routed.args["query"])}
    raise ValueError(f"unsupported intent: {routed.intent}")


def _put_item(session: Session, actor_id: int, routed: RoutedRequest) -> dict[str, Any]:
    existing = actions.search_items(session, query=routed.args["name"])
    exact = [item for item in existing if item["name"] == routed.args["name"]]
    if exact:
        item = actions.move_item(
            session,
            actor_id=actor_id,
            item_id=exact[0]["id"],
            location_name=routed.args["location_name"],
        )
        return {"intent": "move_item", "domain": routed.domain, "item_id": item.id}

    if routed.domain == "perishables":
        tool = perishable_toolset().tools["perishable_add_item"]
        item = tool(session, actor_id=actor_id, name=routed.args["name"], location_name=routed.args["location_name"])
    elif routed.domain == "equipment":
        tool = equipment_toolset().tools["equipment_add_item"]
        item = tool(session, actor_id=actor_id, name=routed.args["name"], location_name=routed.args["location_name"])
    else:
        tool = cards_docs_toolset().tools["card_add_item"]
        item = tool(
            session,
            actor_id=actor_id,
            name=routed.args["name"],
            location_name=routed.args["location_name"],
            kind=ItemKind.DOCUMENT,
        )
    return {"intent": "add_item", "domain": routed.domain, "item_id": item.id}


def _classify_domain(text: str) -> str:
    if any(word in text for word in PERISHABLE_WORDS):
        return "perishables"
    if any(word in text for word in EQUIPMENT_WORDS):
        return "equipment"
    if any(word in text for word in CARD_WORDS):
        return "cards_docs"
    return "cards_docs"


def _extract_object_name(request: str) -> str:
    cleaned = request.strip(" ?？。.")
    cleaned = cleaned.replace("上次谁动了", "").replace("上次谁动", "")
    cleaned = cleaned.replace("谁动了", "").replace("在哪", "").replace("在哪里", "").replace("哪里", "")
    return cleaned.strip() or request.strip()


def _extract_days(request: str) -> int | None:
    match = re.search(r"(\d+)\s*天", request)
    return int(match.group(1)) if match else None

