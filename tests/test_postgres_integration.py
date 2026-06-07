from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlmodel import select

from home_atlas.actions import add_item
from home_atlas.config import Settings
from home_atlas.db import create_db_engine, create_tables, seed_people_from_tokens, session_scope
from home_atlas.models import Event, Item, ItemKind
from home_atlas.security import resolve_actor_id


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
