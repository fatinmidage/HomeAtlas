from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from home_atlas.config import Settings, get_settings
from home_atlas.db import create_db_engine, seed_people_from_tokens, session_scope
from home_atlas.orchestrator import home_atlas
from home_atlas.security import resolve_actor_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="home-atlas", description="HomeAtlas local operations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check database configuration and connectivity")

    init_parser = subparsers.add_parser("init-db", help="Run migrations and seed token-mapped people")
    init_parser.add_argument(
        "--create-database",
        action="store_true",
        help="Create the configured PostgreSQL database first if it does not exist",
    )

    smoke_parser = subparsers.add_parser("smoke", help="Run a write/read smoke test through home_atlas(request)")
    smoke_parser.add_argument("--token", help="Bearer token to resolve from HOME_ATLAS_TOKEN_MAP")
    smoke_parser.add_argument("--item", default="护照")
    smoke_parser.add_argument("--location", default="保险柜抽屉")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "doctor":
        return doctor(settings)
    if args.command == "init-db":
        return init_db(settings, create_database=args.create_database)
    if args.command == "smoke":
        return smoke(settings, token=args.token, item=args.item, location=args.location)
    parser.error(f"unknown command: {args.command}")
    return 2


def doctor(settings: Settings) -> int:
    url = make_url(settings.database_url)
    print(f"database_url={url.render_as_string(hide_password=True)}")
    print(f"token_actors={sorted(set(settings.token_map.values()))}")
    if url.drivername.startswith("postgresql"):
        host = url.host or "localhost"
        port = url.port or 5432
        socket_result = _tcp_probe(host, port)
        print(f"tcp={host}:{port} result={socket_result}")
    try:
        engine = create_db_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        print("database=ok")
        return 0
    except Exception as exc:
        print(f"database=failed error={exc}", file=sys.stderr)
        return 1


def init_db(settings: Settings, *, create_database: bool = False) -> int:
    if create_database:
        ensure_postgres_database(settings.database_url)
    _run_alembic_upgrade(settings)
    engine = create_db_engine(settings)
    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)
    print("database initialized")
    return 0


def smoke(settings: Settings, *, token: str | None, item: str, location: str) -> int:
    if not settings.token_map:
        print("HOME_ATLAS_TOKEN_MAP is required for smoke tests", file=sys.stderr)
        return 2
    token = token or next(iter(settings.token_map))
    engine = create_db_engine(settings)
    with session_scope(engine) as session:
        actor_id = resolve_actor_id(session, token, settings.token_map)
        write_result = home_atlas(f"把{item}放进{location}", session, actor_id)
        where_result = home_atlas(f"{item}在哪？", session, actor_id)
        audit_result = home_atlas(f"上次谁动了{item}？", session, actor_id)
    print(
        json.dumps(
            {"write": write_result, "where": where_result, "audit": audit_result},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


def ensure_postgres_database(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        return
    if not url.database:
        raise ValueError("PostgreSQL database URL must include a database name")
    database_name = url.database
    maintenance_url = url.set(database="postgres")
    with psycopg.connect(maintenance_url.render_as_string(hide_password=False), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select 1 from pg_database where datname = %s", (database_name,))
            if cursor.fetchone():
                print(f"database exists: {database_name}")
                return
            cursor.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))
            print(f"database created: {database_name}")


def _run_alembic_upgrade(settings: Settings) -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def _tcp_probe(host: str, port: int) -> int:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port))


if __name__ == "__main__":
    raise SystemExit(main())
