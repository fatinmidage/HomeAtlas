"""Auto-generated REST API from OntologyRegistry."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from home_atlas import actions
from home_atlas.config import Settings, get_settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.models import ItemDomain, ItemKind
from home_atlas.ontology import ObjectTypeDef, get_registry
from home_atlas.security import HomeAtlasError


class ActionRequest(BaseModel):
    actor_id: int
    params: dict[str, Any] = {}


def build_rest_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_db_engine(settings)
    create_tables(engine)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)

    app = FastAPI(title="HomeAtlas REST API")
    registry = get_registry()

    def _make_list_handler(ot: ObjectTypeDef):
        def handler(query: str | None = Query(None)) -> list[dict[str, Any]]:
            with session_scope(engine) as session:
                return actions.search_items(
                    session,
                    query=query,
                    kind=ot.item_kind,
                )
        handler.__name__ = f"list_{ot.api_name}"
        handler.__doc__ = f"List all {ot.api_name} items."
        return handler

    def _make_action_handler(action_name: str):
        def handler(body: ActionRequest) -> dict[str, Any]:
            with session_scope(engine) as session:
                try:
                    result = _dispatch_action(session, action_name, body.actor_id, body.params)
                    return {"status": "ok", "result": result}
                except HomeAtlasError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
        handler.__name__ = f"invoke_{action_name}"
        handler.__doc__ = f"Invoke the {action_name} action."
        return handler

    for ot in registry.object_types.values():
        app.add_api_route(
            f"/api/objects/{ot.api_name}",
            _make_list_handler(ot),
            methods=["GET"],
        )

    for at in registry.action_types.values():
        app.add_api_route(
            f"/api/actions/{at.api_name}",
            _make_action_handler(at.api_name),
            methods=["POST"],
        )

    @app.get("/api/ontology")
    def get_ontology() -> dict[str, Any]:
        return registry.to_dict()

    return app


_ACTION_DISPATCH = {
    "AddItem": lambda s, aid, p: _item_to_dict(
        actions.add_item(s, actor_id=aid, name=p["name"], kind=ItemKind(p.get("kind", "other")), location_name=p["location_name"])
    ),
    "MoveItem": lambda s, aid, p: _item_to_dict(
        actions.move_item(s, actor_id=aid, item_id=p["item_id"], location_name=p["location_name"])
    ),
    "DiscardItem": lambda s, aid, p: _item_to_dict(
        actions.discard_item(s, actor_id=aid, item_id=p["item_id"], confirm=p.get("confirm", False))
    ),
}


def _dispatch_action(session: Session, action_name: str, actor_id: int, params: dict[str, Any]) -> Any:
    handler = _ACTION_DISPATCH.get(action_name)
    if handler:
        return handler(session, actor_id, params)
    return {"message": f"action {action_name} is registered but has no REST dispatch yet"}


def _item_to_dict(item) -> dict[str, Any]:
    return {"id": item.id, "name": item.name, "kind": item.kind.value}
