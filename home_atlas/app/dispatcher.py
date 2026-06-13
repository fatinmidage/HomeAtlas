from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, get_args, get_origin

from sqlmodel import Session

from home_atlas.ontology import ActionParameterDef, get_registry
from home_atlas.core.security import HomeAtlasError, check_action_permission, check_function_permission


def dispatch_action(
    session: Session,
    actor_id: int,
    api_name: str,
    params: dict[str, Any],
    confirm: bool = False,
) -> Any:
    registry = get_registry()
    action = registry.action_types.get(api_name)
    if action is None:
        raise HomeAtlasError(f"unknown action type: {api_name}")
    validated = _validate_params(action.parameters, params)
    check_action_permission(session, actor_id, api_name)
    if action.requires_confirm and not confirm:
        raise HomeAtlasError(f"{api_name} requires confirm=true")
    impl = registry.resolve_action(api_name)
    if action.requires_confirm:
        validated["confirm"] = confirm
    return impl(session, actor_id=actor_id, **validated)


def dispatch_function(session: Session, actor_id: int, api_name: str, params: dict[str, Any]) -> Any:
    registry = get_registry()
    function = registry.function_defs.get(api_name)
    if function is None:
        raise HomeAtlasError(f"unknown function: {api_name}")
    validated = _validate_params(function.parameters, params)
    check_function_permission(session, actor_id, api_name)
    impl = registry.resolve_function(api_name)
    return impl(session, **validated)


def _validate_params(defs: tuple[ActionParameterDef, ...], params: dict[str, Any]) -> dict[str, Any]:
    declared = {param.name: param for param in defs}
    missing = [name for name, param in declared.items() if param.required and name not in params]
    if missing:
        raise HomeAtlasError(f"missing required parameter: {missing[0]}")
    unknown = sorted(set(params) - set(declared))
    if unknown:
        raise HomeAtlasError(f"unknown parameter: {unknown[0]}")
    return {
        name: _coerce_value(param, params[name])
        for name, param in declared.items()
        if name in params
    }


def _coerce_value(param: ActionParameterDef, value: Any) -> Any:
    if value is None and not param.required:
        return None
    expected = param.python_type
    origin = get_origin(expected)
    if origin is not None:
        args = get_args(expected)
        if type(None) in args and value is None:
            return None
        expected = next((arg for arg in args if arg is not type(None)), expected)
    try:
        if isinstance(expected, type) and issubclass(expected, Enum):
            return value if isinstance(value, expected) else expected(value)
        if expected is date and isinstance(value, str):
            return date.fromisoformat(value)
        if expected is bool and isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            raise ValueError(value)
        if expected is int and isinstance(value, str):
            return int(value)
        if expected is float and isinstance(value, str):
            return float(value)
        if expected is float and isinstance(value, int):
            return float(value)
        if expected is dict and isinstance(value, dict):
            return value
        if expected is list and isinstance(value, list):
            return value
        if isinstance(expected, type) and isinstance(value, expected):
            return value
    except (TypeError, ValueError) as exc:
        raise HomeAtlasError(f"invalid parameter {param.name}: expected {param.python_type.__name__}") from exc
    expected_name = getattr(param.python_type, "__name__", str(param.python_type))
    raise HomeAtlasError(f"invalid parameter {param.name}: expected {expected_name}")
