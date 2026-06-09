"""Database isolation verification.

Ensures the readonly database role cannot perform writes, protecting
Home Atlas data from external agents that bypass the MCP tool layer.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine

from home_atlas.config import Settings

logger = logging.getLogger(__name__)

_WRITE_PROBES = [
    "INSERT INTO location (name) VALUES ('__isolation_probe__')",
    "UPDATE location SET name = '__isolation_probe__' WHERE id = -1",
    "DELETE FROM location WHERE id = -1",
]


def verify_readonly_isolation(settings: Settings) -> dict[str, Any]:
    """Verify that readonly_database_url cannot perform writes.

    Returns a summary dict.  Raises ``RuntimeError`` if any write succeeds.
    """
    if not settings.readonly_database_url:
        return {"status": "skipped", "reason": "readonly_database_url not configured"}

    if not settings.readonly_database_url.startswith("postgresql"):
        return {"status": "skipped", "reason": "isolation check only applies to PostgreSQL"}

    engine = create_engine(settings.readonly_database_url)
    blocked: list[str] = []
    leaked: list[str] = []

    for probe in _WRITE_PROBES:
        try:
            with engine.connect() as conn:
                conn.execute(text(probe))
                conn.rollback()
            leaked.append(probe)
        except Exception:
            blocked.append(probe)
        finally:
            engine.dispose()

    if leaked:
        msg = (
            "SECURITY: readonly database role can execute writes! "
            f"Leaked probes: {leaked}"
        )
        logger.critical(msg)
        raise RuntimeError(msg)

    logger.info(
        "Database isolation verified: readonly role blocked %d write probes",
        len(blocked),
    )
    return {"status": "ok", "blocked": len(blocked)}


def grant_select_on_new_tables(settings: Settings) -> None:
    """Re-grant SELECT to the readonly role after table creation.

    SQLAlchemy's ``create_all`` may create tables as the owner role.
    ``ALTER DEFAULT PRIVILEGES`` covers future tables created by the owner,
    but this function is a belt-and-suspenders call to ensure coverage.
    """
    if not settings.database_url.startswith("postgresql"):
        return
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "GRANT SELECT ON ALL TABLES IN SCHEMA public TO home_atlas_readonly"
            ))
            conn.commit()
    except Exception as exc:
        logger.warning("Could not grant SELECT to readonly role: %s", exc)
    finally:
        engine.dispose()
