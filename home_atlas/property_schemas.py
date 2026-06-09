"""Per-ObjectType Pydantic validation models for the properties JSON pocket."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, field_validator

from home_atlas.models import ItemKind
from home_atlas.security import HomeAtlasError


class FoodProperties(BaseModel):
    brand: str | None = None
    weight: str | None = None


class MedicineProperties(BaseModel):
    dosage: str | None = None
    prescription: bool | None = None


class InsurancePolicyProperties(BaseModel):
    policy_number: str | None = None
    provider: str | None = None


class PaymentCardProperties(BaseModel, extra="forbid"):
    issuer: str | None = None
    card_type: str | None = None
    last4: str | None = None
    expiry_my: str | None = None
    physical_location: str | None = None

    @field_validator("last4")
    @classmethod
    def validate_last4(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{4}", v):
            raise ValueError("last4 must be exactly four digits")
        return v


class MembershipCardProperties(BaseModel):
    member_id: str | None = None
    issuer: str | None = None


class DocumentProperties(BaseModel):
    document_number: str | None = None
    issuing_authority: str | None = None


class ToolProperties(BaseModel):
    brand: str | None = None
    model: str | None = None


class ApplianceProperties(BaseModel):
    brand: str | None = None
    model: str | None = None
    warranty_expiry: str | None = None


PROPERTY_SCHEMAS: dict[ItemKind, type[BaseModel]] = {
    ItemKind.FOOD: FoodProperties,
    ItemKind.MEDICINE: MedicineProperties,
    ItemKind.INSURANCE_POLICY: InsurancePolicyProperties,
    ItemKind.PAYMENT_CARD: PaymentCardProperties,
    ItemKind.MEMBERSHIP_CARD: MembershipCardProperties,
    ItemKind.DOCUMENT: DocumentProperties,
    ItemKind.TOOL: ToolProperties,
    ItemKind.APPLIANCE: ApplianceProperties,
}


def validate_item_properties(kind: ItemKind, properties: dict[str, Any]) -> dict[str, Any]:
    schema = PROPERTY_SCHEMAS.get(kind)
    if schema is None:
        return properties
    try:
        validated = schema.model_validate(properties)
    except Exception as exc:
        raise HomeAtlasError(f"invalid properties for {kind.value}: {exc}") from exc
    return validated.model_dump(exclude_none=True)
