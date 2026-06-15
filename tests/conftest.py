from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from home_atlas.domain.models import Location, Person
from home_atlas.infra.schema_migration import SchemaMetadata  # noqa: F401


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Person(name="你", roles=["admin"]))
        session.add(Person(name="配偶"))
        for name in (
            "主卧衣柜",
            "书房抽屉",
            "保险柜",
            "保险柜抽屉",
            "冰箱",
            "冷藏区",
            "厨房",
            "厨房台面",
            "工具箱",
            "手机卡包",
            "抽屉",
            "文件夹",
            "新钱包",
            "旧钱包",
            "玄关",
            "玄关柜",
            "钱包",
            "桌子",
            "餐桌",
            "厨房柜子",
            "双端烟测保险柜",
        ):
            session.add(Location(name=name))
        session.commit()
        yield session


@pytest.fixture()
def actor_id(session: Session) -> int:
    person = session.exec(select(Person).where(Person.name == "你")).first()
    assert person is not None
    assert person.id is not None
    return person.id
