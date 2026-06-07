from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic_ai import Agent, FunctionToolset, RunContext
from sqlmodel import Session

from home_atlas import actions
from home_atlas.config import Settings
from home_atlas.models import ItemDomain, ItemKind


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
    return bool(settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY"))


def run_ai_home_atlas(request: str, session: Session, actor_id: int, settings: Settings) -> dict[str, Any]:
    if settings.openrouter_api_key:
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
    agents = build_agents(settings.llm_model)
    result = agents.orchestrator.run_sync(request, deps=HomeAtlasDeps(session=session, actor_id=actor_id))
    return {"intent": "ai_delegation", "answer": result.output}


@lru_cache(maxsize=8)
def build_agents(model: str) -> HomeAtlasAgents:
    perishables = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_perishable_ai_toolset()],
        instructions=(
            "You are the perishables sub-agent for HomeAtlas. "
            "Handle only food and medicine inventory. Use only the provided tools. "
            "Return a short Chinese answer."
        ),
        defer_model_check=True,
    )
    cards_docs = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_cards_docs_ai_toolset()],
        instructions=(
            "You are the cards and documents sub-agent for HomeAtlas. "
            "Handle documents, passports, insurance policies, payment cards, and membership cards. "
            "Never store full card numbers or CVV. Use only the provided tools. "
            "Return a short Chinese answer."
        ),
        defer_model_check=True,
    )
    equipment = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[_equipment_ai_toolset()],
        instructions=(
            "You are the equipment sub-agent for HomeAtlas. "
            "Handle tools and appliances only. Use only the provided tools. "
            "Return a short Chinese answer."
        ),
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

    orchestrator = Agent(
        model,
        deps_type=HomeAtlasDeps,
        toolsets=[orchestrator_toolset],
        instructions=(
            "You are the HomeAtlas orchestrator. Classify the user's Chinese household inventory request, "
            "delegate to exactly the relevant domain sub-agent, and combine results. "
            "Do not invent stored data. Writes must be delegated to sub-agent tools. "
            "Return a concise Chinese answer."
        ),
        defer_model_check=True,
    )
    return HomeAtlasAgents(
        orchestrator=orchestrator,
        perishables=perishables,
        cards_docs=cards_docs,
        equipment=equipment,
    )


def _perishable_ai_toolset() -> FunctionToolset[HomeAtlasDeps]:
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

        item = actions.add_item(
            ctx.deps.session,
            actor_id=ctx.deps.actor_id,
            name=name,
            kind=kind,
            location_name=location_name,
            quantity=quantity,
            unit=unit,
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


def _cards_docs_ai_toolset() -> FunctionToolset[HomeAtlasDeps]:
    toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_cards_docs")

    @toolset.tool
    def card_add_document(ctx: RunContext[HomeAtlasDeps], name: str, location_name: str) -> dict[str, Any]:
        """Add a document such as a passport, certificate, or policy reference."""

        item = actions.add_item(
            ctx.deps.session,
            actor_id=ctx.deps.actor_id,
            name=name,
            kind=ItemKind.DOCUMENT,
            location_name=location_name,
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
        item = actions.upsert_card_reference(
            ctx.deps.session,
            actor_id=ctx.deps.actor_id,
            name=name,
            location_name=location_name,
            card_type=ItemKind.PAYMENT_CARD,
            properties=properties,
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


def _equipment_ai_toolset() -> FunctionToolset[HomeAtlasDeps]:
    toolset = FunctionToolset[HomeAtlasDeps](id="home_atlas_equipment")

    @toolset.tool
    def equipment_add_item(
        ctx: RunContext[HomeAtlasDeps],
        name: str,
        location_name: str,
        kind: ItemKind = ItemKind.TOOL,
    ) -> dict[str, Any]:
        """Add a tool or appliance to a household location."""

        item = actions.add_item(
            ctx.deps.session,
            actor_id=ctx.deps.actor_id,
            name=name,
            kind=kind,
            location_name=location_name,
        )
        return {"id": item.id, "name": item.name, "location_id": item.location_id}

    @toolset.tool
    def equipment_search(ctx: RunContext[HomeAtlasDeps], query: str | None = None) -> list[dict[str, Any]]:
        """Search tools and appliances."""

        return actions.search_items(ctx.deps.session, query=query, domain=ItemDomain.EQUIPMENT)

    return toolset
