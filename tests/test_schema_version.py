from __future__ import annotations

from sqlmodel import Session

from home_atlas.schema_migration import (
    CURRENT_SCHEMA_VERSION,
    SchemaMetadata,
    check_schema_version,
    update_schema_version,
)


def test_check_schema_version_passes_when_matching(session: Session) -> None:
    session.add(SchemaMetadata(key="ontology_schema_version", value=str(CURRENT_SCHEMA_VERSION)))
    session.commit()

    result = check_schema_version(session)
    assert result["match"] is True
    assert result["db_version"] == CURRENT_SCHEMA_VERSION
    assert result["code_version"] == CURRENT_SCHEMA_VERSION


def test_check_schema_version_warns_on_mismatch(session: Session) -> None:
    session.add(SchemaMetadata(key="ontology_schema_version", value="0"))
    session.commit()

    result = check_schema_version(session)
    assert result["match"] is False
    assert result["db_version"] == 0
    assert result["code_version"] == CURRENT_SCHEMA_VERSION


def test_check_schema_version_warns_when_missing(session: Session) -> None:
    result = check_schema_version(session)
    assert result["match"] is False
    assert result["db_version"] == 0


def test_update_schema_version(session: Session) -> None:
    session.add(SchemaMetadata(key="ontology_schema_version", value="0"))
    session.commit()

    update_schema_version(session)
    result = check_schema_version(session)
    assert result["match"] is True
    assert result["db_version"] == CURRENT_SCHEMA_VERSION
