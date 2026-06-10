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


def seed_people_from_tokens(session: Session, token_map: dict[str, str], admin_names: str | list[str] | tuple[str, ...] = ()) -> None:
    if isinstance(admin_names, str):
        admins = {name.strip() for name in admin_names.split(",") if name.strip()}
    else:
        admins = {name for name in admin_names if name}
    for person_name in set(token_map.values()):
        person = session.exec(select(Person).where(Person.name == person_name)).first()
        if person is None:
            roles = ["admin"] if person_name in admins else ["member"]
            session.add(Person(name=person_name, roles=roles))
        elif person_name in admins and "admin" not in (person.roles or []):
            person.roles = sorted(set(person.roles or []) | {"admin"})
            session.add(person)
    session.commit()
