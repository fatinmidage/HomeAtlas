# HomeAtlas

HomeAtlas is a household inventory service shaped around the handoff plan in `handoff.md`.

It exposes one high-level delegated tool, `home_atlas(request)`, while keeping writes behind Ontology-style Actions that validate input, stamp the actor, and append audit Events.

## What Is Implemented

- SQLModel object model: `Person`, `Location`, `Item`, `Event`
- Ontology Actions: add, move, adjust quantity, set quantity, update, upsert card reference, discard
- Read Functions: search, get item, where-is, expiring list, recent activity, last touched
- Sensitive-card validation: no full 13-19 digit card numbers, no CVV, payment-card properties allow only reference fields
- Token-to-person identity resolution
- Domain toolsets with prefixes: `perishable_*`, `card_*`, `equipment_*`
- Rule-based orchestrator behind `home_atlas(request)` for local deterministic behavior
- FastMCP construction hook and a small stdlib HTTP runner for local smoke tests
- Alembic migration and pytest coverage for the core verification checklist

## Setup

```bash
uv sync
cp .env.example .env
```

For local unit tests, no PostgreSQL server is required. Tests use an in-memory SQLite database while exercising the same SQLModel tables and Action layer.

```bash
uv run pytest
```

## PostgreSQL

Create a database, set `HOME_ATLAS_DATABASE_URL`, then run:

```bash
uv run alembic upgrade head
```

Example connection string:

```text
postgresql+psycopg://home_atlas:home_atlas@localhost:5432/home_atlas
```

## Hermes MCP Shape

Hermes should see a single write-capable tool:

```yaml
mcp_servers:
  home_atlas:
    url: "http://<家庭服务器局域网IP>:8080/mcp"
    headers: { Authorization: "Bearer <该机器的token>" }
```

Set token ownership through `HOME_ATLAS_TOKEN_MAP`:

```json
{"you-token":"你","spouse-token":"配偶"}
```

The service resolves the Bearer token server-side and passes only `actor_id` into Actions, so the LLM cannot spoof the actor.

## Local HTTP Smoke Runner

The stdlib runner is intentionally small and useful before wiring a full MCP deployment:

```bash
uv run python -m home_atlas.http_server
```

Then call:

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Authorization: Bearer you-token' \
  -H 'Content-Type: application/json' \
  -d '{"request":"把护照放进保险柜抽屉"}'
```

## Design Walkthrough

Input flows through:

1. `home_atlas.orchestrator.home_atlas()` classifies the natural-language request.
2. The selected domain tool calls `home_atlas.actions`.
3. Each Action validates, writes the object table, and records an `Event`.
4. Read Functions return simple dictionaries safe for an MCP response.

Example code path:

```python
result = home_atlas("把护照放进保险柜抽屉", session, actor_id)
```

This routes to `card_add_item`, creates or reuses the location, upserts the item, and writes an `Event` with the resolved actor.

