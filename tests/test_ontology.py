from __future__ import annotations

import pytest

from home_atlas.models import Event, EventAction, Item, ItemDomain, ItemKind, Location, Person, domain_for_kind
from home_atlas.ontology import OntologyRegistry, build_registry, get_registry
from home_atlas.security import HomeAtlasError


@pytest.fixture()
def registry() -> OntologyRegistry:
    return build_registry()


def test_every_item_kind_has_object_type(registry: OntologyRegistry) -> None:
    for kind in ItemKind:
        ot = registry.object_type_for_kind(kind)
        assert ot is not None, f"no ObjectTypeDef for {kind}"
        assert ot.domain == domain_for_kind(kind)


def test_every_event_action_has_action_type(registry: OntologyRegistry) -> None:
    registered = {at.event_action for at in registry.action_types.values()}
    for action in EventAction:
        assert action in registered, f"no ActionTypeDef for {action}"


def test_object_types_for_domain(registry: OntologyRegistry) -> None:
    perishables = registry.object_types_for_domain(ItemDomain.PERISHABLE)
    kinds = {ot.item_kind for ot in perishables}
    assert kinds == {ItemKind.FOOD, ItemKind.MEDICINE}


def test_actions_for_object_type(registry: OntologyRegistry) -> None:
    actions = registry.actions_for_object_type("Food")
    action_names = {a.api_name for a in actions}
    assert "AddItem" in action_names
    assert "AdjustQuantity" in action_names
    assert "UpsertCardReference" not in action_names


def test_validate_properties_rejects_unknown_key(registry: OntologyRegistry) -> None:
    with pytest.raises(HomeAtlasError, match="invalid properties"):
        registry.validate_properties("PaymentCard", {"unknown_field": "x"})


def test_validate_properties_accepts_known_keys(registry: OntologyRegistry) -> None:
    result = registry.validate_properties("PaymentCard", {"issuer": "ICBC", "last4": "1234"})
    assert result == {"issuer": "ICBC", "last4": "1234"}


def test_validate_properties_passes_empty_for_type_without_properties(registry: OntologyRegistry) -> None:
    result = registry.validate_properties("Other", {"anything": "goes"})
    assert result == {"anything": "goes"}


def test_validate_properties_unknown_object_type(registry: OntologyRegistry) -> None:
    with pytest.raises(HomeAtlasError, match="unknown object type"):
        registry.validate_properties("Nonexistent", {})


def test_link_type_fk_columns_exist(registry: OntologyRegistry) -> None:
    model_map = {"Item": Item, "Location": Location, "Person": Person, "Event": Event}
    for lt in registry.link_types.values():
        if lt.cardinality == "one-to-many":
            owner = model_map.get(lt.target_type)
        else:
            owner = model_map.get(lt.source_type)
        if owner is not None:
            assert hasattr(owner, lt.fk_column), (
                f"LinkType {lt.api_name}: expected {lt.fk_column} on {owner.__name__}"
            )


def test_describe_for_llm_produces_text(registry: OntologyRegistry) -> None:
    text = registry.describe_for_llm()
    assert len(text) > 0
    assert "Food" in text
    assert "PaymentCard" in text


def test_describe_for_llm_filters_by_domain(registry: OntologyRegistry) -> None:
    text = registry.describe_for_llm(domain=ItemDomain.EQUIPMENT)
    assert "Tool" in text
    assert "Food" not in text


def test_get_registry_is_singleton() -> None:
    assert get_registry() is get_registry()
