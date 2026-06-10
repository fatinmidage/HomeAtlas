"""Auto-generated REST API from OntologyRegistry."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from home_atlas import actions
from home_atlas.config import Settings, get_settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.dispatcher import dispatch_action
from home_atlas.ontology import ObjectTypeDef, get_registry
from home_atlas.security import HomeAtlasError, UnauthorizedError, resolve_actor_id


class ActionRequest(BaseModel):
    params: dict[str, Any] = {}
    confirm: bool = False


def build_rest_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_db_engine(settings)
    create_tables(engine)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map, settings.admins)

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

    def _actor_id(authorization: str | None = Header(default=None)) -> int:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        with session_scope(engine) as session:
            try:
                return resolve_actor_id(session, token, settings.token_map)
            except UnauthorizedError as exc:
                raise HTTPException(status_code=401, detail=str(exc))

    def _make_action_handler(action_name: str):
        def handler(body: ActionRequest, actor_id: int = Depends(_actor_id)) -> dict[str, Any]:
            with session_scope(engine) as session:
                try:
                    result = dispatch_action(session, actor_id, action_name, body.params, confirm=body.confirm)
                    return {"status": "ok", "result": _result_to_dict(result)}
                except HomeAtlasError as exc:
                    status_code = 404 if str(exc).startswith("unknown action type") else 400
                    raise HTTPException(status_code=status_code, detail=str(exc))
                except UnauthorizedError as exc:
                    raise HTTPException(status_code=403, detail=str(exc))
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

def _result_to_dict(result: Any) -> Any:
    if hasattr(result, "kind") and hasattr(result, "name"):
        return {"id": result.id, "name": result.name, "kind": result.kind.value}
    if hasattr(result, "roles") and hasattr(result, "name"):
        return _person_to_dict(result)
    return result


def _person_to_dict(person) -> dict[str, Any]:
    return {"id": person.id, "name": person.name, "roles": person.roles}
