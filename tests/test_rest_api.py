from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from home_atlas.config import Settings
from home_atlas.db import create_db_engine, session_scope
from home_atlas.models import Event, Person
from home_atlas.rest_api import build_rest_app


def _build_test_app(tmp_path: Path) -> tuple[TestClient, int]:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'home_atlas_test_rest.db'}",
        token_map={"test-token": "你", "spouse-token": "配偶"},
        admins="你",
    )
    app = build_rest_app(settings)
    client = TestClient(app)
    engine = create_db_engine(settings)
    with session_scope(engine) as session:
        person = session.exec(select(Person).where(Person.name == "你")).first()
        assert person is not None
        actor_id = person.id
    return client, actor_id


def test_rest_ontology_endpoint(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    response = client.get("/api/ontology")
    assert response.status_code == 200
    data = response.json()
    assert "schema_version" in data
    assert len(data["object_types"]) > 0
    assert len(data["action_types"]) > 0


def test_rest_list_objects_by_type(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    client.post("/api/actions/AddItem", json={
        "params": {"name": "测试食品", "kind": "food", "location_name": "冰箱"},
    }, headers={"Authorization": "Bearer test-token"})
    response = client.get("/api/objects/Food")
    assert response.status_code == 200
    items = response.json()
    names = [i["name"] for i in items]
    assert "测试食品" in names


def test_rest_invoke_action(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    response = client.post("/api/actions/AddItem", json={
        "params": {"name": "REST测试物品", "kind": "other", "location_name": "桌子"},
    }, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["result"]["name"] == "REST测试物品"


def test_rest_write_requires_bearer_token(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)

    response = client.post("/api/actions/AddItem", json={
        "params": {"name": "未授权物品", "kind": "other", "location_name": "桌子"},
    })

    assert response.status_code == 401


def test_rest_uses_token_actor_and_ignores_spoofed_actor_id(tmp_path: Path) -> None:
    client, actor_id = _build_test_app(tmp_path)

    response = client.post("/api/actions/AddItem", json={
        "actor_id": 999999,
        "params": {"name": "服务端身份物品", "kind": "other", "location_name": "桌子"},
    }, headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'home_atlas_test_rest.db'}",
        token_map={"test-token": "你", "spouse-token": "配偶"},
        admins="你",
    )
    engine = create_db_engine(settings)
    with session_scope(engine) as session:
        event = session.exec(select(Event).order_by(Event.id.desc())).first()
        assert event is not None
        assert event.actor_id == actor_id
