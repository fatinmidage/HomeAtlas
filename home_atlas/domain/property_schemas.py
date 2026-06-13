"""Registry-derived Pydantic validation models for item properties."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model, field_validator

from home_atlas.core.security import HomeAtlasError
from home_atlas.domain.models import ItemKind


class PaymentCardPropertiesBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("last4", check_fields=False)
    @classmethod
    def validate_last4(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"\d{4}", value):
            raise ValueError("last4 must be exactly four digits")
        return value


def _schema_for_kind(kind: ItemKind) -> type[BaseModel] | None:
    from home_atlas.domain.ontology import get_registry

    ot = get_registry().object_type_for_kind(kind)
    if ot is None or not ot.typed_properties:
        return None
    fields = {
        prop.name: (prop.python_type | None, ... if prop.required else None)
        for prop in ot.typed_properties
    }
    base = PaymentCardPropertiesBase if kind == ItemKind.PAYMENT_CARD else BaseModel
    return create_model(f"{ot.api_name}Properties", __base__=base, **fields)


def validate_item_properties(kind: ItemKind, properties: dict[str, Any]) -> dict[str, Any]:
    schema = _schema_for_kind(kind)
    if schema is None:
        return properties
    try:
        validated = schema.model_validate(properties)
    except Exception as exc:
        raise HomeAtlasError(f"invalid properties for {kind.value}: {exc}") from exc
    return _serialize_properties(validated.model_dump(exclude_none=True))


def _serialize_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in properties.items()
    }
