from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from home_atlas.cli import init_db
from home_atlas.config import Settings
from home_atlas.db import create_db_engine, session_scope
from home_atlas.models import Event, Person
from home_atlas.ontology import get_registry
from home_atlas.rest_api import build_rest_app


def _build_test_app(tmp_path: Path) -> tuple[TestClient, int]:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'home_atlas_test_rest.db'}",
        token_map={"test-token": "你", "spouse-token": "配偶"},
        admins="你",
    )
    init_db(settings)
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
    response = client.get("/api/ontology", headers={"Authorization": "Bearer test-token"})
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
    response = client.get("/api/objects/Food", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    items = response.json()
    names = [i["name"] for i in items]
    assert "测试食品" in names


def test_rest_non_item_object_types_are_not_registered_as_item_lists(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    assert client.get("/api/objects/Person", headers=headers).status_code == 404
    assert client.get("/api/objects/Location", headers=headers).status_code == 404
    assert client.get("/api/objects/Event", headers=headers).status_code == 404


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


def test_rest_read_endpoints_require_bearer_token(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)

    assert client.get("/api/objects/Food").status_code == 401
    assert client.get("/api/functions/search_items").status_code == 401
    assert client.get("/api/ontology").status_code == 401


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


def test_rest_dispatches_all_registered_actions(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    created = client.post("/api/actions/AddItem", json={
        "params": {"name": "REST全动作", "kind": "food", "location_name": "冰箱", "quantity": 2},
    }, headers=headers)
    assert created.status_code == 200
    item_id = created.json()["result"]["id"]

    calls = {
        "MoveItem": {"params": {"item_id": item_id, "location_name": "餐桌"}},
        "AdjustQuantity": {"params": {"item_id": item_id, "delta": 1}},
        "SetQuantity": {"params": {"item_id": item_id, "quantity": 5}},
        "UpdateItem": {"params": {"item_id": item_id, "notes": "updated"}, "confirm": True},
        "UpsertCardReference": {
            "params": {
                "name": "REST卡引用",
                "location_name": "钱包",
                "card_type": "payment_card",
                "properties": {"issuer": "招商", "card_type": "Visa", "last4": "4242", "physical_location": "钱包"},
            },
        },
        "SetPersonRole": {"params": {"person_name": "配偶", "role": "member"}},
        "DiscardItem": {"params": {"item_id": item_id}, "confirm": True},
    }
    for action_name, body in calls.items():
        response = client.post(f"/api/actions/{action_name}", json=body, headers=headers)
        assert response.status_code == 200, (action_name, response.text)
        assert response.json()["status"] == "ok"

    response = client.post("/api/actions/NotRegistered", json={"params": {}}, headers=headers)
    assert response.status_code == 404


def test_secret_properties_are_masked_in_rest_reads(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    response = client.post("/api/actions/AddItem", json={
        "params": {
            "name": "护照",
            "kind": "document",
            "location_name": "保险柜",
            "properties": {"document_number": "E12345678"},
        },
    }, headers=headers)
    assert response.status_code == 200

    items = client.get("/api/objects/Document", headers=headers).json()
    item = next(item for item in items if item["name"] == "护照")
    assert item["properties"]["document_number"] == "****5678"


def test_secret_properties_are_described_for_llm() -> None:
    text = get_registry().describe_for_llm()
    assert "document_number(optional, str, secret)" in text


def test_rest_registered_functions_are_callable(tmp_path: Path) -> None:
    client, _ = _build_test_app(tmp_path)
    headers = {"Authorization": "Bearer test-token"}
    client.post("/api/actions/AddItem", json={
        "params": {"name": "函数测试物品", "kind": "food", "location_name": "冰箱"},
    }, headers=headers)

    calls = {
        "search_items": {"query": "函数测试"},
        "where_is": {"name": "函数测试物品"},
        "list_expiring": {"within_days": "30"},
        "recent_activity": {"limit": "5"},
        "last_touched": {"name": "函数测试物品"},
    }
    for function_name, params in calls.items():
        response = client.get(f"/api/functions/{function_name}", params=params, headers=headers)
        assert response.status_code == 200, (function_name, response.text)

    response = client.get("/api/functions/not_registered", headers=headers)
    assert response.status_code == 404
