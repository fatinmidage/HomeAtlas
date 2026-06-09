from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from home_atlas.config import Settings
from home_atlas.models import Person
from home_atlas.rest_api import build_rest_app


def _build_test_app() -> tuple[TestClient, int]:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:////private/tmp/home_atlas_test_rest.db",
        token_map={"test-token": "你"},
    )
    app = build_rest_app(settings)
    client = TestClient(app)
    from home_atlas.db import create_db_engine, session_scope
    engine = create_db_engine(settings)
    with session_scope(engine) as session:
        person = session.exec(select(Person).where(Person.name == "你")).first()
        assert person is not None
        actor_id = person.id
    return client, actor_id


def test_rest_ontology_endpoint() -> None:
    client, _ = _build_test_app()
    response = client.get("/api/ontology")
    assert response.status_code == 200
    data = response.json()
    assert "schema_version" in data
    assert len(data["object_types"]) > 0
    assert len(data["action_types"]) > 0


def test_rest_list_objects_by_type() -> None:
    client, actor_id = _build_test_app()
    client.post("/api/actions/AddItem", json={
        "actor_id": actor_id,
        "params": {"name": "测试食品", "kind": "food", "location_name": "冰箱"},
    })
    response = client.get("/api/objects/Food")
    assert response.status_code == 200
    items = response.json()
    names = [i["name"] for i in items]
    assert "测试食品" in names


def test_rest_invoke_action() -> None:
    client, actor_id = _build_test_app()
    response = client.post("/api/actions/AddItem", json={
        "actor_id": actor_id,
        "params": {"name": "REST测试物品", "kind": "other", "location_name": "桌子"},
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["result"]["name"] == "REST测试物品"
