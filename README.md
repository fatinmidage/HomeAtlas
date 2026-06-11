# HomeAtlas

HomeAtlas is a household inventory service shaped around the handoff plan in `handoff.md`.

It exposes one high-level delegated tool, `home_atlas(request)`, while keeping writes behind Ontology-style Actions that validate input, stamp the actor, and append audit Events.

## What Is Implemented

- SQLModel object model: `Person`, `Location`, `Item`, `Event`
- Ontology Actions: add, move, adjust quantity, set quantity, update, upsert card reference, discard, set person role
- Registry-projected Read Functions: search, where-is, expiring list, recent activity, last touched
- Sensitive-data validation across names, locations, notes, and properties: no full 13-19 digit card numbers, including space- or hyphen-separated forms; no CVV/card-number keys; payment-card properties allow only reference fields
- Token-to-person identity resolution; REST and MCP resolve actors server-side
- RBAC defaults new people to `member`; admin-only actions include update, discard, and role changes
- Startup schema gate: services refuse to start until Alembic migrations and schema metadata are current
- Masked read outputs: registry read functions return MCP/REST-safe dictionaries
- Deterministic lookup behavior for duplicate names, with newest match selected and ambiguity noted
- Domain toolsets with prefixes: `perishable_*`, `card_*`, `equipment_*`
- Rule-based orchestrator behind `home_atlas(request)` for local deterministic behavior
- FastMCP construction hook and a small stdlib HTTP runner for local smoke tests
- Alembic migration and pytest coverage for the core verification checklist

## Setup

```bash
uv sync
cp .env.example .env
uv run python -m home_atlas.cli init-db
```

Run `init-db` before starting any long-running entrypoint, including `home_atlas.mcp_server`,
`home_atlas.http_server`, or the generated REST app. HomeAtlas no longer creates tables at
service startup; it fails fast when the database schema is missing or older than the code.

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
uv run python -m home_atlas.cli smoke --token replace-with-token-1
uv run python -m home_atlas.cli dual-smoke --writer-token replace-with-token-1 --reader-token replace-with-token-2
```

Expected smoke result includes:

```text
"answer": "护照 在 保险柜抽屉"
```

If you manage PostgreSQL outside Docker, create a database, set `HOME_ATLAS_DATABASE_URL`, then run:

```bash
uv run python -m home_atlas.cli init-db
```

Example connection string:

```text
postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas
```

The Python ops entrypoint does not require `psql` to be on `PATH`:

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas'
export HOME_ATLAS_TOKEN_MAP='{"replace-with-token-1":"你","replace-with-token-2":"配偶"}'
export HOME_ATLAS_ADMINS='你'

uv run python -m home_atlas.cli doctor
uv run python -m home_atlas.cli init-db --create-database
uv run python -m home_atlas.cli smoke --token replace-with-token-1
```

If the database role already exists but the database does not, `--create-database` creates the configured database through the maintenance database named `postgres`. If your local Postgres uses your macOS user as the role, change the URL accordingly, for example:

```bash
export HOME_ATLAS_DATABASE_URL='postgresql+psycopg://<local-user>@localhost:5432/home_atlas'
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
{"replace-with-token-1":"你","replace-with-token-2":"配偶"}
```

The service resolves the Bearer token server-side and passes only `actor_id` into Actions, so the LLM cannot spoof the actor.
Set initial admins with `HOME_ATLAS_ADMINS` as a comma-separated name list matching `HOME_ATLAS_TOKEN_MAP` values. Existing rows keep their current roles; use the `SetPersonRole` Action to change roles with an audit trail.

Run the FastMCP streamable HTTP server with bearer authentication:

```bash
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.mcp_server
```

Hermes sends `Authorization: Bearer <token>` to `/mcp`. FastMCP validates the bearer token before the tool runs, then `home_atlas(request)` resolves the actor server-side.

Use `deploy/hermes/mcp.yaml.example` as the two-device template. Each Hermes client should use the same URL but its own Bearer token.

Before the two physical Hermes clients are connected, this command validates the same actor model locally: token A writes, token B reads, and the database audit event must show token A's actor.

```bash
uv run python -m home_atlas.cli dual-smoke \
  --writer-token replace-with-token-1 \
  --reader-token replace-with-token-2 \
  --item 双端烟测护照 \
  --location 双端烟测保险柜
```

## REST API

The generated REST API also resolves actors from Bearer tokens. Read and write
endpoints all require `Authorization`; unauthenticated reads return 401.

```bash
curl http://localhost:8080/api/objects/Food \
  -H 'Authorization: Bearer replace-with-token-1'

curl http://localhost:8080/api/ontology \
  -H 'Authorization: Bearer replace-with-token-1'
```

## Agent Mode

HomeAtlas supports two orchestrator paths:

- `HOME_ATLAS_AGENT_MODE=rules`: deterministic keyword/regex router, no LLM key required.
- `HOME_ATLAS_AGENT_MODE=ai`: Pydantic AI parent Agent delegates to perishables, cards/docs, or equipment child Agents.
- `HOME_ATLAS_AGENT_MODE=auto`: use AI when `HOME_ATLAS_LLM_API_KEY` or the provider key is present; otherwise return a configuration reminder to Hermes instead of silently falling back.

Fill this in `.env` to enable Pydantic AI delegation:

```bash
HOME_ATLAS_LLM_MODEL=deepseek:deepseek-chat
HOME_ATLAS_LLM_API_KEY=...
```

If you intentionally want the deterministic keyword router without an LLM, set:

```bash
HOME_ATLAS_AGENT_MODE=rules
```

The model value lives with the rest of the runtime configuration in `.env`. `home_atlas/llm_config.py` only defines the environment variable names and DeepSeek provider key mapping.

Bare DeepSeek model names such as `deepseek-v4-flash` are normalized to Pydantic AI's provider form `deepseek:deepseek-v4-flash` at runtime.

## Home Server Process

### Docker Compose

The production-style compose stack runs PostgreSQL and the HomeAtlas MCP service together. The
PostgreSQL container is only reachable on the internal compose network.

```bash
docker compose up -d postgres
docker compose build home_atlas
docker compose run --rm home_atlas python -m home_atlas.cli init-db
docker compose up -d home_atlas
docker logs homeatlas-service --tail 20
```

Use the same `compose run --rm home_atlas python -m home_atlas.cli init-db` step after pulling
code that contains new migrations. If an existing deployment was created by an old `create_all`
snapshot, migrate or rebuild the database before starting the new service; otherwise the schema
gate will intentionally stop the service.

### launchd

The launchd template lives at `deploy/launchd/com.homeatlas.server.plist`. It runs:

```bash
/path/to/HomeAtlas/.venv/bin/python -m home_atlas.mcp_server
```

with `WorkingDirectory=/path/to/HomeAtlas`, so the service reads the real local `.env`.

Install on the home-server Mac:

```bash
mkdir -p logs
uv run python -m home_atlas.cli init-db
cp deploy/launchd/com.homeatlas.server.plist ~/Library/LaunchAgents/com.homeatlas.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.homeatlas.server.plist
launchctl kickstart -k gui/$(id -u)/com.homeatlas.server
launchctl print gui/$(id -u)/com.homeatlas.server
```

Stop it with:

```bash
launchctl bootout gui/$(id -u)/com.homeatlas.server
```

## Backups

HomeAtlas wraps PostgreSQL's native backup tools. `pg_dump` and `pg_restore` must be installed on the home-server Mac and available on `PATH`.

```bash
uv run python -m home_atlas.cli backup-db --output backups/home_atlas-$(date +%Y%m%d-%H%M%S).dump
uv run python -m home_atlas.cli verify-backup backups/<backup-file>.dump
```

`verify-backup` creates a temporary PostgreSQL database, restores the dump into it, checks `item` and `event` counts, then drops the temporary database.

## PostgreSQL Integration Tests

Concurrent PostgreSQL writes are covered by an opt-in integration test:

```bash
HOME_ATLAS_INTEGRATION_DATABASE_URL='postgresql+psycopg://home_atlas:<password>@localhost:5432/home_atlas' \
  uv run pytest tests/test_postgres_integration.py
```

The tests write multiple items concurrently into the same new location and, when PostgreSQL is configured, concurrently update the same item to verify audit versions remain unique and ordered.

## Hermes Reminders

Use `deploy/hermes/list_expiring_reminder.md` to configure a Hermes scheduled reminder that calls:

```text
哪些物品 14 天内临期或待续费？
```

## Local HTTP Smoke Runner

The stdlib runner is intentionally small and useful before wiring a full MCP deployment. It uses the same `HOME_ATLAS_DATABASE_URL` and token map as the CLI:

```bash
uv run python -m home_atlas.cli init-db
uv run python -m home_atlas.http_server
```

Then call:

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Authorization: Bearer replace-with-token-1' \
  -H 'Content-Type: application/json' \
  -d '{"request":"把护照放进保险柜抽屉"}'
```

## Design Walkthrough

Input flows through:

1. `home_atlas.orchestrator.home_atlas()` classifies the natural-language request.
2. The selected domain tool calls the Registry-driven dispatcher.
3. The dispatcher validates parameters, RBAC, confirmation, and invokes the Action.
4. Each Action validates, writes the object table, records an `Event`, and EventBus handlers run only after commit succeeds.
5. Read Functions are registered in the Ontology Registry and return dictionaries safe for an MCP response.

Example code path:

```python
result = home_atlas("把护照放进保险柜抽屉", session, actor_id)
```

This routes to the cards/docs domain, creates or reuses the location, inserts the item through `AddItem`, and writes an `Event` with the resolved actor.

## Remaining Production Work

- Run the two-Mac Hermes validation: token A writes, token B reads, and audit reports the original actor.
- Install the launchd plist on the home-server Mac.
- Install `pg_dump`/`pg_restore` on the home-server Mac and run backup verification.
- Configure the Hermes scheduled reminder on the real Hermes client.
