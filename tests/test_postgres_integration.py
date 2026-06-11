from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url
from sqlmodel import select

from home_atlas.actions import add_item, move_item, search_items, set_person_role
from home_atlas.cli import init_db
from home_atlas.config import Settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.models import Event, Item, ItemKind, Person
from home_atlas.security import resolve_actor_id


def _temporary_database_url(base_url: str) -> str:
    url = make_url(base_url)
    database_name = f"home_atlas_test_{uuid4().hex}"
    maintenance_url = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(maintenance_url.render_as_string(hide_password=False), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'create database "{database_name}"')
    return url.set(database=database_name).render_as_string(hide_password=False)


def _drop_database(database_url: str) -> None:
    url = make_url(database_url)
    if not url.database:
        return
    maintenance_url = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(maintenance_url.render_as_string(hide_password=False), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity where datname = %s",
                (url.database,),
            )
            cursor.execute(f'drop database if exists "{url.database}"')


@pytest.mark.skipif(
    not os.getenv("HOME_ATLAS_INTEGRATION_DATABASE_URL"),
    reason="set HOME_ATLAS_INTEGRATION_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_concurrent_writes_to_same_new_location() -> None:
    settings = Settings(
        _env_file=None,
        database_url=os.environ["HOME_ATLAS_INTEGRATION_DATABASE_URL"],
        token_map={"you-token": "你", "spouse-token": "配偶"},
    )
    engine = create_db_engine(settings)
    create_tables(engine)
    suffix = uuid4().hex[:8]
    location_name = f"并发测试位置-{suffix}"
    item_names = [f"并发测试物品-{suffix}-{index}" for index in range(12)]

    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)

    def write_item(name: str) -> int:
        with session_scope(engine) as session:
            actor_id = resolve_actor_id(session, "you-token", settings.token_map)
            item = add_item(
                session,
                actor_id=actor_id,
                name=name,
                kind=ItemKind.TOOL,
                location_name=location_name,
            )
            assert item.id is not None
            return item.id

    with ThreadPoolExecutor(max_workers=6) as executor:
        item_ids = list(executor.map(write_item, item_names))

    with session_scope(engine) as session:
        stored_items = session.exec(select(Item).where(Item.id.in_(item_ids))).all()
        event_count = len(session.exec(select(Event).where(Event.item_id.in_(item_ids))).all())

    assert {item.name for item in stored_items} == set(item_names)
    assert {item.location_id for item in stored_items}
    assert event_count == len(item_names)


@pytest.mark.skipif(
    not os.getenv("HOME_ATLAS_INTEGRATION_DATABASE_URL"),
    reason="set HOME_ATLAS_INTEGRATION_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_concurrent_writes_to_same_item_have_unique_versions() -> None:
    settings = Settings(
        _env_file=None,
        database_url=os.environ["HOME_ATLAS_INTEGRATION_DATABASE_URL"],
        token_map={"you-token": "你"},
    )
    engine = create_db_engine(settings)
    create_tables(engine)
    suffix = uuid4().hex[:8]

    with session_scope(engine) as session:
        seed_people_from_tokens(session, settings.token_map)
        actor_id = resolve_actor_id(session, "you-token", settings.token_map)
        item = add_item(
            session,
            actor_id=actor_id,
            name=f"同物品并发-{suffix}",
            kind=ItemKind.TOOL,
            location_name=f"初始位置-{suffix}",
        )
        assert item.id is not None
        item_id = item.id

    locations = [f"并发位置-{suffix}-{index}" for index in range(8)]

    def move(location_name: str) -> None:
        with session_scope(engine) as session:
            actor_id = resolve_actor_id(session, "you-token", settings.token_map)
            move_item(session, actor_id=actor_id, item_id=item_id, location_name=location_name)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(move, locations))

    with session_scope(engine) as session:
        versions = session.exec(
            select(Event.version).where(Event.item_id == item_id).order_by(Event.version)
        ).all()

    assert versions == list(range(1, len(locations) + 2))


@pytest.mark.skipif(
    not os.getenv("HOME_ATLAS_INTEGRATION_DATABASE_URL"),
    reason="set HOME_ATLAS_INTEGRATION_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_alembic_schema_supports_jsonb_filter_and_set_person_role() -> None:
    database_url = _temporary_database_url(os.environ["HOME_ATLAS_INTEGRATION_DATABASE_URL"])
    try:
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            token_map={"you-token": "你", "spouse-token": "配偶"},
            admins="你",
        )
        init_db(settings)
        engine = create_db_engine(settings)

        with session_scope(engine) as session:
            actor_id = resolve_actor_id(session, "you-token", settings.token_map)
            spouse = session.exec(select(Person).where(Person.name == "配偶")).first()
            assert spouse is not None

            item = add_item(
                session,
                actor_id=actor_id,
                name="PG迁移过滤测试",
                kind=ItemKind.DOCUMENT,
                location_name="保险柜",
                properties={"document_number": "E12345678", "issuing_authority": "出入境"},
            )
            set_person_role(session, actor_id=actor_id, person_name="配偶", role="viewer")
            results = search_items(session, property_filter={"issuing_authority": "出入境"})
            event = session.exec(select(Event).where(Event.item_id == item.id).order_by(Event.id)).first()
            assert event is not None
            item_id = item.id
            event_created_at = event.created_at

        assert item_id is not None
        assert event_created_at.tzinfo is not None
        assert event_created_at.isoformat().endswith("+00:00")
        assert any(row["name"] == "PG迁移过滤测试" for row in results)
    finally:
        _drop_database(database_url)
