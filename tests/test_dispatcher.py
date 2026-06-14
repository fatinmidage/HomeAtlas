from __future__ import annotations

import inspect

import pytest
from sqlmodel import Session

from home_atlas.app.actions import add_item
from home_atlas.app.dispatcher import dispatch_action, dispatch_function
from home_atlas.domain.models import ItemKind, Person
from home_atlas.domain.ontology import ActionParameterDef, FunctionDef, build_registry, get_registry
from home_atlas.core.security import HomeAtlasError, UnauthorizedError


def test_dispatcher_rejects_missing_unknown_and_wrong_type(session: Session, actor_id: int) -> None:
    with pytest.raises(HomeAtlasError, match="location_name"):
        dispatch_action(session, actor_id, "AddItem", {"name": "缺位置", "kind": "food"})

    with pytest.raises(HomeAtlasError, match="unknown parameter: surprise"):
        dispatch_action(
            session,
            actor_id,
            "AddItem",
            {"name": "多余参数", "kind": "food", "location_name": "冰箱", "surprise": True},
        )

    with pytest.raises(HomeAtlasError, match="quantity"):
        dispatch_action(
            session,
            actor_id,
            "SetQuantity",
            {"item_id": 1, "quantity": "not-float"},
        )


def test_dispatcher_update_routine_fields_do_not_require_confirm(session: Session, actor_id: int) -> None:
    item = dispatch_action(
        session,
        actor_id,
        "AddItem",
        {"name": "确认测试", "kind": "tool", "location_name": "工具箱"},
    )

    updated = dispatch_action(
        session,
        actor_id,
        "UpdateItem",
        {"item_id": item.id, "notes": "只改备注"},
    )
    assert updated.notes == "只改备注"

    with pytest.raises(HomeAtlasError, match="overwriting identifying fields requires confirm=true"):
        dispatch_action(session, actor_id, "UpdateItem", {"item_id": item.id, "name": "新名字"})

    renamed = dispatch_action(session, actor_id, "UpdateItem", {"item_id": item.id, "name": "新名字", "confirm": True})
    assert renamed.name == "新名字"

    with pytest.raises(HomeAtlasError, match="DiscardItem requires confirm=true"):
        dispatch_action(session, actor_id, "DiscardItem", {"item_id": item.id})


def test_dispatcher_enforces_rbac(session: Session) -> None:
    admin = Person(name="管理员", roles=["admin"])
    member = Person(name="成员", roles=["member"])
    viewer = Person(name="观察者", roles=["viewer"])
    session.add(admin)
    session.add(member)
    session.add(viewer)
    session.commit()
    session.refresh(admin)
    session.refresh(member)
    session.refresh(viewer)

    item = add_item(session, actor_id=admin.id, name="权限测试", kind=ItemKind.FOOD, location_name="冰箱")

    updated = dispatch_action(session, member.id, "UpdateItem", {"item_id": item.id, "notes": "成员可改日常字段"})
    assert updated.notes == "成员可改日常字段"

    dispatched = dispatch_action(session, member.id, "DiscardItem", {"item_id": item.id}, confirm=True)
    assert dispatched.archived is True

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        dispatch_action(session, viewer.id, "UpdateItem", {"item_id": item.id, "notes": "viewer 不可改"})

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        dispatch_action(session, viewer.id, "DiscardItem", {"item_id": item.id}, confirm=True)


def test_dispatcher_enforces_function_required_role(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = Person(name="管理员", roles=["admin"])
    member = Person(name="成员", roles=["member"])
    session.add(admin)
    session.add(member)
    session.commit()
    session.refresh(admin)
    session.refresh(member)

    registry = get_registry()
    patched_functions = dict(registry.function_defs)
    patched_functions["admin_ping"] = FunctionDef(
        api_name="admin_ping",
        parameters=(ActionParameterDef("message", str),),
        implementation="tests.test_dispatcher._admin_ping",
        required_role="admin",
    )
    monkeypatch.setattr(registry, "function_defs", patched_functions)

    with pytest.raises(UnauthorizedError, match="lacks permission"):
        dispatch_function(session, member.id, "admin_ping", {"message": "hello"})

    assert dispatch_function(session, admin.id, "admin_ping", {"message": "hello"}) == {"message": "hello"}


def _admin_ping(session: Session, message: str) -> dict[str, str]:
    return {"message": message}


def test_registry_action_implementations_resolve_and_match_parameters() -> None:
    registry = build_registry()
    for action in registry.action_types.values():
        impl = registry.resolve_action(action.api_name)
        signature = inspect.signature(impl)
        parameters = signature.parameters
        has_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        for declared in action.parameters:
            assert declared.name in parameters or has_var_kwargs, (
                f"{action.api_name} declares {declared.name} but {impl} does not accept it"
            )
