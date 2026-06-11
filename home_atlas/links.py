"""Link traversal — navigate named relationships via the Ontology Registry."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from home_atlas.actions import _item_dict, _masked_snapshot
from home_atlas.models import Event, Item, Location, Person
from home_atlas.ontology import LinkTypeDef, get_registry
from home_atlas.security import HomeAtlasError


def traverse_link(
    session: Session,
    source_type: str,
    source_id: int,
    link_name: str,
) -> list[dict[str, Any]]:
    lt, reverse = _resolve_link(link_name)
    if lt is None:
        raise HomeAtlasError(f"unknown link type: {link_name}")
    expected_source = lt.target_type if reverse else lt.source_type
    if expected_source != source_type:
        raise HomeAtlasError(
            f"link {link_name} expects source {expected_source}, got {source_type}"
        )

    target_type = lt.source_type if reverse else lt.target_type
    target_table = _table_for_type(target_type)
    if target_table is None:
        raise HomeAtlasError(f"unmapped target type: {target_type}")

    rows = _linked_rows(session, lt, reverse, source_id)
    return [_serialize_object(session, target_type, row) for row in rows]


def traverse_chain(
    session: Session,
    source_type: str,
    source_id: int,
    link_names: list[str],
) -> list[dict[str, Any]]:
    current_type = source_type
    current_results = [{"id": source_id}]

    for link_name in link_names:
        lt, reverse = _resolve_link(link_name)
        if lt is None:
            raise HomeAtlasError(f"unknown link type: {link_name}")
        next_results: list[dict[str, Any]] = []
        for item in current_results:
            next_results.extend(
                traverse_link(session, current_type, item["id"], link_name)
            )
        current_type = lt.source_type if reverse else lt.target_type
        current_results = next_results
        if not current_results:
            break

    return current_results


def auto_traverse(
    session: Session,
    source_type: str,
    source_id: int,
    target_type: str,
) -> list[dict[str, Any]]:
    registry = get_registry()
    path = registry.shortest_path(source_type, target_type)
    if not path:
        row = _get_row(session, source_type, source_id)
        return [_serialize_object(session, source_type, row)] if row is not None else []
    return traverse_chain(session, source_type, source_id, path)


def _resolve_link(link_name: str) -> tuple[LinkTypeDef | None, bool]:
    registry = get_registry()
    lt = registry.link_types.get(link_name)
    if lt is not None:
        return lt, False
    for candidate in registry.link_types.values():
        if candidate.inverse_name == link_name:
            return candidate, True
    return None, False


def _table_for_type(type_name: str) -> str | None:
    ot = get_registry().object_types.get(type_name)
    return ot.table if ot else None


def _model_for_type(type_name: str) -> type[Item] | type[Location] | type[Person] | type[Event] | None:
    return {
        "Item": Item,
        "Location": Location,
        "Person": Person,
        "Event": Event,
    }.get(type_name)


def _linked_rows(session: Session, lt: LinkTypeDef, reverse: bool, source_id: int) -> list[Any]:
    target_type = lt.source_type if reverse else lt.target_type
    target_model = _model_for_type(target_type)
    if target_model is None:
        raise HomeAtlasError(f"unmapped target type: {target_type}")

    if reverse:
        if lt.cardinality == "one-to-many":
            source = _get_row(session, lt.target_type, source_id)
            if source is None:
                return []
            target_id = getattr(source, lt.fk_column)
            row = session.get(target_model, target_id) if target_id is not None else None
            return [row] if row is not None else []
        return list(session.exec(select(target_model).where(getattr(target_model, lt.fk_column) == source_id)).all())

    if lt.cardinality == "one-to-many":
        return list(session.exec(select(target_model).where(getattr(target_model, lt.fk_column) == source_id)).all())

    source = _get_row(session, lt.source_type, source_id)
    if source is None:
        return []
    target_id = getattr(source, lt.fk_column)
    row = session.get(target_model, target_id) if target_id is not None else None
    return [row] if row is not None else []


def _get_row(session: Session, type_name: str, row_id: int) -> Any | None:
    model = _model_for_type(type_name)
    if model is None:
        raise HomeAtlasError(f"unmapped source type: {type_name}")
    return session.get(model, row_id)


def _serialize_object(session: Session, type_name: str, row: Any) -> dict[str, Any]:
    if type_name == "Item":
        location = session.get(Location, row.location_id)
        if location is None:
            raise HomeAtlasError(f"location {row.location_id} not found")
        return _item_dict(row, location)
    if type_name == "Event":
        return {
            "id": row.id,
            "item_id": row.item_id,
            "actor_id": row.actor_id,
            "action": row.action.value,
            "summary": row.summary,
            "before": _masked_snapshot(row.before),
            "after": _masked_snapshot(row.after),
            "version": row.version,
            "created_at": row.created_at,
        }
    if type_name == "Person":
        return {"id": row.id, "name": row.name, "roles": row.roles, "created_at": row.created_at}
    if type_name == "Location":
        return {
            "id": row.id,
            "name": row.name,
            "parent_id": row.parent_id,
            "notes": row.notes,
            "created_at": row.created_at,
        }
    raise HomeAtlasError(f"unmapped target type: {type_name}")
