from __future__ import annotations

import pytest

from home_atlas.domain.models import Event, EventAction, Item, ItemDomain, ItemKind, Location, Person, domain_for_kind
from home_atlas.domain.ontology import LinkTypeDef, OntologyRegistry, build_registry, get_registry
from home_atlas.infra.schema_migration import CURRENT_SCHEMA_VERSION
from home_atlas.core.security import HomeAtlasError


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


def test_registry_to_dict_returns_all_types(registry: OntologyRegistry) -> None:
    d = registry.to_dict()
    assert d["schema_version"] == CURRENT_SCHEMA_VERSION
    assert len(d["object_types"]) == len(ItemKind) + 4
    assert len(d["link_types"]) == 6
    assert len(d["action_types"]) == len(EventAction)
    for ot in d["object_types"]:
        assert "api_name" in ot
        assert ot["primary_key"] == "id"
        assert ot["title_property"] == "name"
        assert "typed_properties" in ot


def test_ontology_describes_table_entities(registry: OntologyRegistry) -> None:
    text = registry.describe_for_llm()
    assert "## Person" in text
    assert "## Location" in text
    assert "## Event" in text


def test_registry_rejects_link_with_unregistered_endpoint() -> None:
    registry = OntologyRegistry()
    registry.register_object_type(build_registry().object_types["Item"])
    registry.register_link_type(LinkTypeDef("badLink", "Item", "Missing", "location_id"))

    with pytest.raises(HomeAtlasError, match="target type is not registered"):
        registry.validate_links()


def test_keywords_for_domain_returns_non_empty(registry: OntologyRegistry) -> None:
    for domain in (ItemDomain.PERISHABLE, ItemDomain.CARDS_DOCS, ItemDomain.EQUIPMENT):
        keywords = registry.keywords_for_domain(domain)
        assert len(keywords) > 0, f"no keywords for domain {domain.value}"


def test_action_type_to_dict_excludes_implementation(registry: OntologyRegistry) -> None:
    for at in registry.action_types.values():
        d = at.to_dict()
        assert "implementation" not in d
        assert "api_name" in d
        assert "parameters" in d


def test_registered_functions_resolve(registry: OntologyRegistry) -> None:
    expected = {"search_items", "where_is", "list_expiring", "recent_activity", "last_touched"}
    assert set(registry.function_defs) == expected
    for api_name in expected:
        assert callable(registry.resolve_function(api_name))
