from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from home_atlas.config import Settings, get_settings
from home_atlas.models import Person


def create_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


def create_tables(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def seed_people_from_tokens(session: Session, token_map: dict[str, str]) -> None:
    for person_name in set(token_map.values()):
        person = session.exec(select(Person).where(Person.name == person_name)).first()
        if person is None:
            session.add(Person(name=person_name))
    session.commit()
