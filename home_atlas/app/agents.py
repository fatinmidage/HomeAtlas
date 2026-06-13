from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic_ai import Agent, FunctionToolset, RunContext
from sqlmodel import Session

from home_atlas import actions
from home_atlas.core.config import Settings
from home_atlas.app.dispatcher import dispatch_action, dispatch_function
from home_atlas.domain.links import auto_traverse
from home_atlas.core.llm_config import export_provider_api_key, has_configured_api_key, normalize_model_name
from home_atlas.domain.models import ItemDomain, ItemKind
from home_atlas.domain.ontology import AIToolDef, ActionParameterDef, ActionTypeDef, FunctionDef, OntologyRegistry, get_registry
from home_atlas.core.security import HomeAtlasError


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
            return dispatch_function(ctx.deps.session, ctx.deps.actor_id, "last_touched", {"name": name})
        except HomeAtlasError as exc:
            return {"error": str(exc)}

    @orchestrator_toolset.tool
    def atlas_list_expiring(ctx: RunContext[HomeAtlasDeps], within_days: int = 30) -> list[dict[str, Any]]:
        """List items with expiry or renewal dates within the given number of days."""

        return dispatch_function(
            ctx.deps.session,
            ctx.deps.actor_id,
            "list_expiring",
            {"within_days": within_days},
        )

    @orchestrator_toolset.tool
    def atlas_list_items(ctx: RunContext[HomeAtlasDeps]) -> list[dict[str, Any]]:
        """List all non-archived household inventory items across every domain."""

        return dispatch_function(ctx.deps.session, ctx.deps.actor_id, "search_items", {})

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
    registry = get_registry()
    ids = {
        ItemDomain.PERISHABLE: "home_atlas_perishables",
        ItemDomain.CARDS_DOCS: "home_atlas_cards_docs",
        ItemDomain.EQUIPMENT: "home_atlas_equipment",
    }
    if domain not in ids:
        raise ValueError(f"unsupported AI toolset domain: {domain}")

    toolset = FunctionToolset[HomeAtlasDeps](id=ids[domain])
    for action in registry.action_types.values():
        for tool_def in action.ai_tools:
            if tool_def.domain == domain:
                toolset.add_function(
                    _make_action_tool(action, tool_def),
                    takes_ctx=True,
                    name=tool_def.name,
                    description=tool_def.description or action.description,
                )
    for function in registry.function_defs.values():
        for tool_def in function.ai_tools:
            if tool_def.domain == domain:
                toolset.add_function(
                    _make_function_tool(function, tool_def),
                    takes_ctx=True,
                    name=tool_def.name,
                    description=tool_def.description or function.description,
                )
    return toolset


def _make_action_tool(action: ActionTypeDef, tool_def: AIToolDef):
    parameter_defs = _tool_parameter_defs(action.parameters, tool_def)
    adapter = _resolve_adapter(tool_def.adapter)

    def generated_tool(ctx: RunContext[HomeAtlasDeps], **kwargs: Any) -> Any:
        params = {**tool_def.constants, **kwargs}
        if adapter is not None:
            params = adapter(**params)
        item = dispatch_action(ctx.deps.session, ctx.deps.actor_id, action.api_name, params)
        return _tool_result(item)

    return _with_tool_signature(generated_tool, tool_def.name, tool_def.description or action.description, parameter_defs, tool_def)


def _make_function_tool(function: FunctionDef, tool_def: AIToolDef):
    parameter_defs = _tool_parameter_defs(function.parameters, tool_def)

    def generated_tool(ctx: RunContext[HomeAtlasDeps], **kwargs: Any) -> Any:
        params = {**tool_def.constants, **kwargs}
        return dispatch_function(ctx.deps.session, ctx.deps.actor_id, function.api_name, params)

    return _with_tool_signature(generated_tool, tool_def.name, tool_def.description or function.description, parameter_defs, tool_def)


def _tool_parameter_defs(
    declared_parameters: tuple[ActionParameterDef, ...],
    tool_def: AIToolDef,
) -> tuple[ActionParameterDef, ...]:
    if tool_def.parameters:
        by_name = {param.name: param for param in tool_def.parameters}
    else:
        by_name = {param.name: param for param in declared_parameters}
    return tuple(by_name[name] for name in tool_def.parameter_names)


def _with_tool_signature(
    func,
    name: str,
    description: str,
    parameter_defs: tuple[ActionParameterDef, ...],
    tool_def: AIToolDef,
):
    parameters = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=RunContext[HomeAtlasDeps],
        )
    ]
    for param in parameter_defs:
        default = inspect.Parameter.empty
        if param.name in tool_def.defaults:
            default = tool_def.defaults[param.name]
        elif not param.required:
            default = None
        parameters.append(
            inspect.Parameter(
                param.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=param.python_type,
            )
        )
    func.__name__ = name
    func.__doc__ = description
    func.__annotations__ = {
        "ctx": RunContext[HomeAtlasDeps],
        **{param.name: param.python_type for param in parameter_defs},
        "return": Any,
    }
    func.__signature__ = inspect.Signature(parameters, return_annotation=Any)
    return func


def _resolve_adapter(adapter_path: str):
    if not adapter_path:
        return None
    module_path, _, attr = adapter_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _payment_card_reference_params(
    *,
    name: str,
    location_name: str,
    issuer: str,
    card_type: str,
    last4: str,
    expiry_my: str | None = None,
) -> dict[str, Any]:
    properties = {"issuer": issuer, "card_type": card_type, "last4": last4, "physical_location": location_name}
    if expiry_my:
        properties["expiry_my"] = expiry_my
    return {
        "name": name,
        "location_name": location_name,
        "card_type": ItemKind.PAYMENT_CARD,
        "properties": properties,
    }


def _tool_result(value: Any) -> Any:
    if hasattr(value, "id") and hasattr(value, "name"):
        result = {"id": value.id, "name": value.name}
        if hasattr(value, "location_id"):
            result["location_id"] = value.location_id
        if hasattr(value, "properties") and value.properties:
            result["properties"] = actions._masked_properties(value)
        return result
    return value
