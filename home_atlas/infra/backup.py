from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy.engine import URL, make_url

from home_atlas.core.config import Settings


def postgresql_cli_url(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("pg_dump backup requires a PostgreSQL database URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def backup_database(settings: Settings, output_path: Path) -> Path:
    database_url = postgresql_cli_url(settings.database_url)
    pg_dump = _require_binary("pg_dump")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [pg_dump, "--format=custom", "--file", str(output_path), database_url],
        check=True,
    )
    return output_path


def verify_backup(settings: Settings, backup_path: Path) -> dict[str, Any]:
    pg_restore = _require_binary("pg_restore")
    if not backup_path.exists():
        raise FileNotFoundError(f"backup file not found: {backup_path}")

    source_url = make_url(settings.database_url)
    if not source_url.drivername.startswith("postgresql") or not source_url.database:
        raise ValueError("restore verification requires a PostgreSQL database URL with a database name")

    verify_name = f"{source_url.database}_restore_verify_{uuid.uuid4().hex[:8]}"
    maintenance_url = source_url.set(database="postgres")
    verify_url = source_url.set(database=verify_name)

    with psycopg.connect(_psycopg_url(maintenance_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("create database %s" % _quote_identifier(verify_name))

    try:
        subprocess.run(
            [pg_restore, "--clean", "--if-exists", "--no-owner", "--dbname", _cli_url(verify_url), str(backup_path)],
            check=True,
        )
        with psycopg.connect(_psycopg_url(verify_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) from item")
                item_count = cursor.fetchone()[0]
                cursor.execute("select count(*) from event")
                event_count = cursor.fetchone()[0]
        return {"database": verify_name, "items": item_count, "events": event_count}
    finally:
        with psycopg.connect(_psycopg_url(maintenance_url), autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select pg_terminate_backend(pid) from pg_stat_activity where datname = %s",
                    (verify_name,),
                )
                cursor.execute("drop database if exists %s" % _quote_identifier(verify_name))


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"{name} not found on PATH")
    return path


def _cli_url(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _psycopg_url(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
