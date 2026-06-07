from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from home_atlas.models import Person

FULL_CARD_RE = re.compile(r"\b\d{13,19}\b")
PAYMENT_CARD_ALLOWED_KEYS = {"issuer", "card_type", "last4", "expiry_my", "physical_location"}
CVV_KEYS = {"cvv", "cvc", "security_code", "card_security_code"}


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


def reject_payment_card_secrets(properties: dict[str, Any]) -> None:
    extra_keys = set(properties) - PAYMENT_CARD_ALLOWED_KEYS
    if extra_keys:
        raise HomeAtlasError(f"payment card properties only allow reference fields: {sorted(extra_keys)}")
    if CVV_KEYS & {key.lower() for key in properties}:
        raise HomeAtlasError("payment card CVV must never be stored")
    for key, value in properties.items():
        text = str(value)
        if FULL_CARD_RE.search(text):
            raise HomeAtlasError(f"payment card field {key!r} looks like a full card number")
    last4 = properties.get("last4")
    if last4 is not None and not re.fullmatch(r"\d{4}", str(last4)):
        raise HomeAtlasError("payment card last4 must be exactly four digits")

