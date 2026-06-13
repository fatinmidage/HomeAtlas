from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from home_atlas.domain.models import Person

SEPARATED_CARD_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d[ -]?){13,19}(?![A-Za-z0-9])")
PAYMENT_CARD_ALLOWED_KEYS = {"issuer", "card_type", "last4", "expiry_my", "physical_location"}
CVV_KEYS = {"cvv", "cvc", "security_code", "card_security_code"}
CARD_NUMBER_KEYS = {"card_number", "card_no", "pan"}


class HomeAtlasError(ValueError):
    """Domain-level error safe to return to a caller."""


class UnauthorizedError(PermissionError):
    """Raised when an MCP token cannot be resolved to a person."""


def resolve_actor_id(session: Session, token: str | None, token_map: dict[str, str]) -> int:
    if not token or token not in token_map:
        raise UnauthorizedError("missing or invalid token")
    person_name = token_map[token]
    person = session.exec(select(Person).where(Person.name == person_name)).first()
    if person is None:
        person = Person(name=person_name)
        session.add(person)
        session.commit()
        session.refresh(person)
    assert person.id is not None
    return person.id


def check_action_permission(session: Session, actor_id: int, action_name: str) -> None:
    from home_atlas.domain.ontology import get_registry
    person = session.get(Person, actor_id)
    if person is None:
        raise UnauthorizedError("unknown actor")
    roles = person.roles if person.roles else ["viewer"]
    registry = get_registry()
    if not registry.check_permission(action_name, roles):
        raise UnauthorizedError(f"role {roles} lacks permission for {action_name}")


def check_function_permission(session: Session, actor_id: int, function_name: str) -> None:
    from home_atlas.domain.ontology import get_registry
    person = session.get(Person, actor_id)
    if person is None:
        raise UnauthorizedError("unknown actor")
    roles = person.roles if person.roles else ["viewer"]
    registry = get_registry()
    if not registry.check_function_permission(function_name, roles):
        raise UnauthorizedError(f"role {roles} lacks permission for {function_name}")


def scan_sensitive_text(value: Any, path: str = "value") -> None:
    """Reject full payment secrets anywhere user-controlled text can be stored."""
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in CVV_KEYS:
                raise HomeAtlasError(f"sensitive CVV field {key!r} must never be stored")
            if lowered in CARD_NUMBER_KEYS:
                raise HomeAtlasError(f"sensitive card-number field {key!r} must never be stored")
            scan_sensitive_text(nested, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set)):
        for index, nested in enumerate(value):
            scan_sensitive_text(nested, f"{path}[{index}]")
        return
    if isinstance(value, str) and _contains_full_card_number(value):
        raise HomeAtlasError(f"{path} looks like a full card number")


def reject_payment_card_secrets(properties: dict[str, Any]) -> None:
    extra_keys = set(properties) - PAYMENT_CARD_ALLOWED_KEYS
    if extra_keys:
        raise HomeAtlasError(f"payment card properties only allow reference fields: {sorted(extra_keys)}")
    if CVV_KEYS & {key.lower() for key in properties}:
        raise HomeAtlasError("payment card CVV must never be stored")
    for key, value in properties.items():
        text = str(value)
        if _contains_full_card_number(text):
            raise HomeAtlasError(f"payment card field {key!r} looks like a full card number")
    last4 = properties.get("last4")
    if last4 is not None and not re.fullmatch(r"\d{4}", str(last4)):
        raise HomeAtlasError("payment card last4 must be exactly four digits")


def _contains_full_card_number(text: str) -> bool:
    for match in SEPARATED_CARD_CANDIDATE_RE.finditer(text):
        normalized = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(normalized) <= 19:
            return True
    return False
