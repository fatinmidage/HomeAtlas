"""Link traversal — navigate named relationships via the Ontology Registry."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from home_atlas.ontology import get_registry
from home_atlas.security import HomeAtlasError

_TABLE_FOR_TYPE = {
    "Item": "item",
    "Location": "location",
    "Person": "person",
    "Event": "event",
}


def traverse_link(
    session: Session,
    source_type: str,
    source_id: int,
    link_name: str,
) -> list[dict[str, Any]]:
    registry = get_registry()
    lt = registry.link_types.get(link_name)
    if lt is None:
        raise HomeAtlasError(f"unknown link type: {link_name}")
    if lt.source_type != source_type:
        raise HomeAtlasError(
            f"link {link_name} expects source {lt.source_type}, got {source_type}"
        )

    target_table = _TABLE_FOR_TYPE.get(lt.target_type)
    if target_table is None:
        raise HomeAtlasError(f"unmapped target type: {lt.target_type}")

    if lt.cardinality == "one-to-many":
        query = text(f"SELECT * FROM {target_table} WHERE {lt.fk_column} = :sid")
    else:
        source_table = _TABLE_FOR_TYPE.get(lt.source_type)
        if source_table is None:
            raise HomeAtlasError(f"unmapped source type: {lt.source_type}")
        query = text(
            f"SELECT t.* FROM {target_table} t "
            f"JOIN {source_table} s ON s.{lt.fk_column} = t.id "
            f"WHERE s.id = :sid"
        )

    rows = session.execute(query, {"sid": source_id}).mappings().all()
    return [dict(row) for row in rows]


def traverse_chain(
    session: Session,
    source_type: str,
    source_id: int,
    link_names: list[str],
) -> list[dict[str, Any]]:
    registry = get_registry()
    current_type = source_type
    current_results = [{"id": source_id}]

    for link_name in link_names:
        lt = registry.link_types.get(link_name)
        if lt is None:
            raise HomeAtlasError(f"unknown link type: {link_name}")
        next_results: list[dict[str, Any]] = []
        for item in current_results:
            next_results.extend(
                traverse_link(session, current_type, item["id"], link_name)
            )
        current_type = lt.target_type
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
        return traverse_link(session, source_type, source_id, target_type)
    return traverse_chain(session, source_type, source_id, path)
