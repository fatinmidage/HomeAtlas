"""Link traversal — navigate named relationships via the Ontology Registry."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from home_atlas.ontology import LinkTypeDef, get_registry
from home_atlas.security import HomeAtlasError


def traverse_link(
    session: Session,
    source_type: str,
    source_id: int,
    link_name: str,
) -> list[dict[str, Any]]:
    registry = get_registry()
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

    if reverse:
        query = _reverse_query(lt, target_table)
    elif lt.cardinality == "one-to-many":
        query = text(f"SELECT * FROM {target_table} WHERE {lt.fk_column} = :sid")
    else:
        source_table = _table_for_type(lt.source_type)
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
        table = _table_for_type(source_type)
        if table is None:
            raise HomeAtlasError(f"unmapped source type: {source_type}")
        rows = session.execute(text(f"SELECT * FROM {table} WHERE id = :sid"), {"sid": source_id}).mappings().all()
        return [dict(row) for row in rows]
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


def _reverse_query(lt: LinkTypeDef, target_table: str):
    if lt.cardinality == "one-to-many":
        source_table = _table_for_type(lt.target_type)
        return text(
            f"SELECT t.* FROM {target_table} t "
            f"JOIN {source_table} s ON s.{lt.fk_column} = t.id "
            f"WHERE s.id = :sid"
        )
    return text(f"SELECT * FROM {target_table} WHERE {lt.fk_column} = :sid")
