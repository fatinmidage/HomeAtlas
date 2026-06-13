from __future__ import annotations

from datetime import date

import pytest

from home_atlas.domain.models import ItemKind
from home_atlas.domain.property_schemas import validate_item_properties
from home_atlas.core.security import HomeAtlasError


def test_payment_card_extra_forbid() -> None:
    with pytest.raises(HomeAtlasError, match="invalid properties"):
        validate_item_properties(ItemKind.PAYMENT_CARD, {"unknown": "x"})


def test_payment_card_last4_format() -> None:
    with pytest.raises(HomeAtlasError, match="last4"):
        validate_item_properties(ItemKind.PAYMENT_CARD, {"last4": "12"})


def test_payment_card_valid() -> None:
    result = validate_item_properties(
        ItemKind.PAYMENT_CARD, {"issuer": "ICBC", "last4": "5678"}
    )
    assert result == {"issuer": "ICBC", "last4": "5678"}


def test_food_optional_fields() -> None:
    result = validate_item_properties(ItemKind.FOOD, {})
    assert result == {}


def test_food_strips_none_values() -> None:
    result = validate_item_properties(ItemKind.FOOD, {"brand": "Nestle"})
    assert result == {"brand": "Nestle"}


def test_appliance_accepts_all_fields() -> None:
    result = validate_item_properties(
        ItemKind.APPLIANCE, {"brand": "Dyson", "model": "V15", "warranty_expiry": date(2027, 6, 1)}
    )
    assert result == {"brand": "Dyson", "model": "V15", "warranty_expiry": "2027-06-01"}


def test_other_kind_passes_through() -> None:
    result = validate_item_properties(ItemKind.OTHER, {"arbitrary": "data"})
    assert result == {"arbitrary": "data"}
