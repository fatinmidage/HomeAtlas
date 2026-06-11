"""Ontology schema version tracking and startup mismatch detection."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Field, Session, SQLModel, select

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2


class SchemaMetadata(SQLModel, table=True):
    __tablename__ = "schema_metadata"
    key: str = Field(primary_key=True)
    value: str


def check_schema_version(session: Session) -> dict[str, int | bool]:
    try:
        row = session.exec(
            select(SchemaMetadata).where(SchemaMetadata.key == "ontology_schema_version")
        ).first()
    except SQLAlchemyError:
        logger.warning("Schema metadata table is missing or unreadable — run migrations")
        return {"db_version": 0, "code_version": CURRENT_SCHEMA_VERSION, "match": False}
    if row is None:
        logger.warning("No ontology_schema_version in DB — run migrations")
        return {"db_version": 0, "code_version": CURRENT_SCHEMA_VERSION, "match": False}
    db_version = int(row.value)
    match = db_version == CURRENT_SCHEMA_VERSION
    if not match:
        logger.warning(
            "Ontology schema mismatch: DB=%d, code=%d — run migrations",
            db_version,
            CURRENT_SCHEMA_VERSION,
        )
    return {"db_version": db_version, "code_version": CURRENT_SCHEMA_VERSION, "match": match}


def require_schema_version(session: Session) -> None:
    result = check_schema_version(session)
    if not result["match"]:
        raise RuntimeError(
            "HomeAtlas database schema is not initialized or is out of date. "
            "Run `python -m home_atlas.cli init-db` before starting the service."
        )


def update_schema_version(session: Session) -> None:
    row = session.exec(
        select(SchemaMetadata).where(SchemaMetadata.key == "ontology_schema_version")
    ).first()
    if row is None:
        session.add(SchemaMetadata(key="ontology_schema_version", value=str(CURRENT_SCHEMA_VERSION)))
    else:
        row.value = str(CURRENT_SCHEMA_VERSION)
    session.commit()
