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

For local development, use Docker Compose:

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose up -d postgres
```

Then initialize the schema and seed token-mapped people:

```bash
cp .env.example .env
uv run python -m home_atlas.cli doctor
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.cli smoke --token you-token
```

Expected smoke result includes:

```text
"answer": "护照 在 保险柜抽屉"
```

If you manage PostgreSQL outside Docker, create a database, set `HOME_ATLAS_DATABASE_URL`, then run:

```bash
uv run alembic upgrade head
```

Example connection string:

```text
postgresql+psycopg://home_atlas:home_atlas@localhost:5432/home_atlas
```

The Python ops entrypoint does not require `psql` to be on `PATH`:

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://home_atlas:home_atlas@localhost:5432/home_atlas'
export HOME_ATLAS_TOKEN_MAP='{"you-token":"你","spouse-token":"配偶"}'

uv run python -m home_atlas.cli doctor
uv run python -m home_atlas.cli init-db --create-database
uv run python -m home_atlas.cli smoke --token you-token
```

If the database role already exists but the database does not, `--create-database` creates the configured database through the maintenance database named `postgres`. If your local Postgres uses your macOS user as the role, change the URL accordingly, for example:

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://wuyingheng@localhost:5432/home_atlas'
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

Run the FastMCP streamable HTTP server with bearer authentication:

```bash
uv run python -m home_atlas.mcp_server
```

Hermes sends `Authorization: Bearer <token>` to `/mcp`. FastMCP validates the bearer token before the tool runs, then `home_atlas(request)` resolves the actor server-side.

## Agent Mode

HomeAtlas supports two orchestrator paths:

- `HOME_ATLAS_AGENT_MODE=rules`: deterministic keyword/regex router, no LLM key required.
- `HOME_ATLAS_AGENT_MODE=ai`: Pydantic AI parent Agent delegates to perishables, cards/docs, or equipment child Agents.
- `HOME_ATLAS_AGENT_MODE=auto`: use AI only when `OPENROUTER_API_KEY` is present; otherwise use rules.

Fill this in `.env` to enable Pydantic AI delegation:

```bash
OPENROUTER_API_KEY=...
```

## Local HTTP Smoke Runner

The stdlib runner is intentionally small and useful before wiring a full MCP deployment. It uses the same `HOME_ATLAS_DATABASE_URL` and token map as the CLI:

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

## Remaining Production Work

- Run the two-Mac Hermes validation: token A writes, token B reads, and audit reports the original actor.
- Add launchd or another process supervisor for the home-server Mac.
- Add `pg_dump` backup and restore verification.
- Add concurrent-write integration tests against PostgreSQL.
