from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic_ai import Agent, FunctionToolset, RunContext
from sqlmodel import Session

from home_atlas import actions
from home_atlas.config import Settings
from home_atlas.dispatcher import dispatch_action
from home_atlas.links import auto_traverse
from home_atlas.llm_config import export_provider_api_key, has_configured_api_key, normalize_model_name
from home_atlas.models import ItemDomain, ItemKind
from home_atlas.ontology import OntologyRegistry, get_registry
from home_atlas.security import HomeAtlasError


@dataclass
class HomeAtlasDeps:
    session: Session
    actor_id: int


@dataclass(frozen=True)
class HomeAtlasAgents:
    orchestrator: Agent[HomeAtlasDeps, str]
    perishables: Agent[HomeAtlasDeps, str]
    cards_docs: Agent[HomeAtlasDeps, str]
    equipment: Agent[HomeAtlasDeps, str]


def should_use_ai(settings: Settings) -> bool:
    if settings.agent_mode == "rules":
        return False
    if settings.agent_mode == "ai":
        return True
    return has_configured_api_key(settings.llm_api_key)


def run_ai_home_atlas(request: str, session: Session, actor_id: int, settings: Settings) -> dict[str, Any]:
    if not settings.llm_model:
        raise ValueError("HOME_ATLAS_LLM_MODEL must be configured for AI mode.")
    export_provider_api_key(settings.llm_api_key)
    agents = build_agents(normalize_model_name(settings.llm_model))
    result = agents.orchestrator.run_sync(request, deps=HomeAtlasDeps(session=session, actor_id=actor_id))
    return {"intent": "ai_delegation", "answer": result.output}


def _build_sub_agent_instructions(registry: OntologyRegistry, domain: ItemDomain) -> str:
    ots = registry.object_types_for_domain(domain)
    types_desc = ", ".join(f"{ot.api_name}({ot.item_kind.value})" for ot in ots)
    lines = [
        f"You are the {domain.value} sub-agent for HomeAtlas.",
        f"Handle these object types: {types_desc}.",
        "Use only the provided tools.",
        "If a user asks to put or store an unknown item, add it instead of refusing.",
    ]
    if domain == ItemDomain.CARDS_DOCS:
        lines.append("Never store full card numbers or CVV.")
    lines.append("Return a short Chinese answer.")
    return " ".join(lines)


def _build_orchestrator_instructions(registry: OntologyRegistry) -> str:
    domain_summaries = []
    for domain in (ItemDomain.PERISHABLE, ItemDomain.CARDS_DOCS, ItemDomain.EQUIPMENT):
        ots = registry.object_types_for_domain(domain)
        kinds = ", ".join(ot.item_kind.value for ot in ots)
        domain_summaries.append(f"  - {domain.value}: {kinds}")
    domains_text = "\n".join(domain_summaries)

    return (
        "You are the HomeAtlas orchestrator. Classify the user's Chinese household inventory request, "
        "delegate to exactly the relevant domain sub-agent, and combine results.\n"
        f"Domains:\n{domains_text}\n"
        "Do not invent stored data. Writes must be delegated to sub-agent tools. "
        "A request like 'put X into Y' for an unknown item is a create request; delegate it. "
        "For audit history, expiry, renewal, or whole-home inventory listing questions, use the atlas_* tools directly. "
        "For broad questions like '家里有什么物品' or '列出所有物品', call atlas_list_items. "
        "Return a concise Chinese answer."
    )


@lru_cache(maxsize=8)
def build_agents(model: str) -> HomeAtlasAgents:
    registry = get_registry()

    perishables = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_build_ai_toolset_for_domain(ItemDomain.PERISHABLE)],
        instructions=_build_sub_agent_instructions(registry, ItemDomain.PERISHABLE),
        defer_model_check=True,
    )
    cards_docs = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_build_ai_toolset_for_domain(ItemDomain.CARDS_DOCS)],
        instructions=_build_sub_agent_instructions(registry, ItemDomain.CARDS_DOCS),
        defer_model_check=True,
    )
    equipment = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_build_ai_toolset_for_domain(ItemDomain.EQUIPMENT)],
        instructions=_build_sub_agent_instructions(registry, ItemDomain.EQUIPMENT),
        defer_model_check=True,
    )

    orchestrator_toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_orchestrator_delegates")

    @orchestrator_toolset.tool
    def delegate_perishables(ctx: RunContext[HomeAtlasDeps], request: str) -> str:
        """Delegate a food or medicine request to the perishables sub-agent."""

        return perishables.run_sync(request, deps=ctx.deps, usage=ctx.usage).output

    @orchestrator_toolset.tool
    def delegate_cards_docs(ctx: RunContext[HomeAtlasDeps], request: str) -> str:
        """Delegate a document, insurance, payment card, or membership card request."""

        return cards_docs.run_sync(request, deps=ctx.deps, usage=ctx.usage).output

    @orchestrator_toolset.tool
    def delegate_equipment(ctx: RunContext[HomeAtlasDeps], request: str) -> str:
        """Delegate a tool or appliance request to the equipment sub-agent."""

        return equipment.run_sync(request, deps=ctx.deps, usage=ctx.usage).output

    @orchestrator_toolset.tool
    def atlas_last_touched(ctx: RunContext[HomeAtlasDeps], name: str) -> dict[str, Any]:
        """Return the most recent audit event and actor for any household item."""

        try:
            return actions.last_touched(ctx.deps.session, name)
        except HomeAtlasError as exc:
            return {"error": str(exc)}

    @orchestrator_toolset.tool
    def atlas_list_expiring(ctx: RunContext[HomeAtlasDeps], within_days: int = 30) -> list[dict[str, Any]]:
        """List items with expiry or renewal dates within the given number of days."""

        return actions.list_expiring(ctx.deps.session, within_days=within_days)

    @orchestrator_toolset.tool
    def atlas_list_items(ctx: RunContext[HomeAtlasDeps]) -> list[dict[str, Any]]:
        """List all non-archived household inventory items across every domain."""

        return actions.search_items(ctx.deps.session)

    @orchestrator_toolset.tool
    def atlas_traverse_links(
        ctx: RunContext[HomeAtlasDeps],
        source_type: str,
        source_id: int,
        target_type: str,
    ) -> list[dict[str, Any]]:
        """Traverse relationships across object types via the shortest link path."""

        try:
            return auto_traverse(ctx.deps.session, source_type, source_id, target_type)
        except HomeAtlasError as exc:
            return [{"error": str(exc)}]

    orchestrator = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[orchestrator_toolset],
        instructions=_build_orchestrator_instructions(registry),
        defer_model_check=True,
    )
    return HomeAtlasAgents(
        orchestrator=orchestrator,
        perishables=perishables,
        cards_docs=cards_docs,
        equipment=equipment,
    )


def _build_ai_toolset_for_domain(domain: ItemDomain) -> FunctionToolset[HomeAtlasDeps]:
    if domain == ItemDomain.PERISHABLE:
        return _build_perishable_tools()
    if domain == ItemDomain.CARDS_DOCS:
        return _build_cards_docs_tools()
    if domain == ItemDomain.EQUIPMENT:
        return _build_equipment_tools()
    raise ValueError(f"unsupported AI toolset domain: {domain}")


def _build_perishable_tools() -> FunctionToolset[HomeAtlasDeps]:
    toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_perishables")

    @toolset.tool
    def perishable_add_item(
        ctx: RunContext[HomeAtlasDeps],
        name: str,
        location_name: str,
        kind: ItemKind = ItemKind.FOOD,
        quantity: float | None = None,
        unit: str | None = None,
    ) -> dict[str, Any]:
        """Add food or medicine to a household location."""

        item = dispatch_action(
            ctx.deps.session,
            ctx.deps.actor_id,
            "AddItem",
            {
                "name": name,
                "kind": kind,
                "location_name": location_name,
                "quantity": quantity,
                "unit": unit,
            },
        )
        return {"id": item.id, "name": item.name, "location_id": item.location_id}

    @toolset.tool
    def perishable_search(ctx: RunContext[HomeAtlasDeps], query: str | None = None) -> list[dict[str, Any]]:
        """Search food and medicine inventory."""

        return actions.search_items(ctx.deps.session, query=query, domain=ItemDomain.PERISHABLE)

    @toolset.tool
    def perishable_list_expiring(ctx: RunContext[HomeAtlasDeps], within_days: int = 30) -> list[dict[str, Any]]:
        """List food and medicine expiring within the given number of days."""

        return actions.list_expiring(ctx.deps.session, within_days=within_days)

    return toolset


def _build_cards_docs_tools() -> FunctionToolset[HomeAtlasDeps]:
    toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_cards_docs")

    @toolset.tool
    def card_add_document(ctx: RunContext[HomeAtlasDeps], name: str, location_name: str) -> dict[str, Any]:
        """Add a document such as a passport, certificate, or policy reference."""

        item = dispatch_action(
            ctx.deps.session,
            ctx.deps.actor_id,
            "AddItem",
            {"name": name, "kind": ItemKind.DOCUMENT, "location_name": location_name},
        )
        return {"id": item.id, "name": item.name, "location_id": item.location_id}

    @toolset.tool
    def card_upsert_payment_reference(
        ctx: RunContext[HomeAtlasDeps],
        name: str,
        location_name: str,
        issuer: str,
        card_type: str,
        last4: str,
        expiry_my: str | None = None,
    ) -> dict[str, Any]:
        """Store a payment card reference using issuer, card type, last4, and optional expiry only."""

        properties = {"issuer": issuer, "card_type": card_type, "last4": last4, "physical_location": location_name}
        if expiry_my:
            properties["expiry_my"] = expiry_my
        item = dispatch_action(
            ctx.deps.session,
            ctx.deps.actor_id,
            "UpsertCardReference",
            {
                "name": name,
                "location_name": location_name,
                "card_type": ItemKind.PAYMENT_CARD,
                "properties": properties,
            },
        )
        return {"id": item.id, "name": item.name, "properties": item.properties}

    @toolset.tool
    def card_search(ctx: RunContext[HomeAtlasDeps], query: str | None = None) -> list[dict[str, Any]]:
        """Search documents, policies, payment cards, and membership cards."""

        return actions.search_items(ctx.deps.session, query=query, domain=ItemDomain.CARDS_DOCS)

    @toolset.tool
    def card_where_is(ctx: RunContext[HomeAtlasDeps], name: str) -> dict[str, Any]:
        """Find where a document or card is stored."""

        return actions.where_is(ctx.deps.session, name)

    return toolset


def _build_equipment_tools() -> FunctionToolset[HomeAtlasDeps]:
    toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_equipment")

    @toolset.tool
    def equipment_add_item(
        ctx: RunContext[HomeAtlasDeps],
        name: str,
        location_name: str,
        kind: ItemKind = ItemKind.TOOL,
    ) -> dict[str, Any]:
        """Add a tool or appliance to a household location."""

        item = dispatch_action(
            ctx.deps.session,
            ctx.deps.actor_id,
            "AddItem",
            {"name": name, "kind": kind, "location_name": location_name},
        )
        return {"id": item.id, "name": item.name, "location_id": item.location_id}

    @toolset.tool
    def equipment_search(ctx: RunContext[HomeAtlasDeps], query: str | None = None) -> list[dict[str, Any]]:
        """Search tools and appliances."""

        return actions.search_items(ctx.deps.session, query=query, domain=ItemDomain.EQUIPMENT)

    return toolset
