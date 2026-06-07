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
uv run python -m home_atlas.cli dual-smoke --writer-token you-token --reader-token spouse-token
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

Use `deploy/hermes/mcp.yaml.example` as the two-device template. Each Hermes client should use the same URL but its own Bearer token.

Before the two physical Hermes clients are connected, this command validates the same actor model locally: token A writes, token B reads, and the database audit event must show token A's actor.

```bash
uv run python -m home_atlas.cli dual-smoke \
  --writer-token you-token \
  --reader-token spouse-token \
  --item 双端烟测护照 \
  --location 双端烟测保险柜
```

## Agent Mode

HomeAtlas supports two orchestrator paths:

- `HOME_ATLAS_AGENT_MODE=rules`: deterministic keyword/regex router, no LLM key required.
- `HOME_ATLAS_AGENT_MODE=ai`: Pydantic AI parent Agent delegates to perishables, cards/docs, or equipment child Agents.
- `HOME_ATLAS_AGENT_MODE=auto`: use AI only when `HOME_ATLAS_LLM_API_KEY` is present; otherwise use rules.

Fill this in `.env` to enable Pydantic AI delegation:

```bash
HOME_ATLAS_LLM_MODEL=deepseek:deepseek-chat
HOME_ATLAS_LLM_API_KEY=...
```

The model value lives with the rest of the runtime configuration in `.env`. `home_atlas/llm_config.py` only defines the environment variable names and DeepSeek provider key mapping.

Bare DeepSeek model names such as `deepseek-v4-flash` are normalized to Pydantic AI's provider form `deepseek:deepseek-v4-flash` at runtime.

## Home Server Process

The launchd template lives at `deploy/launchd/com.homeatlas.server.plist`. It runs:

```bash
/Users/wuyingheng/项目/HomeAtlas/.venv/bin/python -m home_atlas.mcp_server
```

with `WorkingDirectory=/Users/wuyingheng/项目/HomeAtlas`, so the service reads the real local `.env`.

Install on the home-server Mac:

```bash
mkdir -p logs
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
HOME_ATLAS_INTEGRATION_DATABASE_URL='postgresql+psycopg://home_atlas:home_atlas@localhost:5432/home_atlas' \
  uv run pytest tests/test_postgres_integration.py
```

The test writes multiple items concurrently into the same new location and verifies the resulting items and audit events.

## Hermes Reminders

Use `deploy/hermes/list_expiring_reminder.md` to configure a Hermes scheduled reminder that calls:

```text
哪些物品 14 天内临期或待续费？
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
- Install the launchd plist on the home-server Mac.
- Install `pg_dump`/`pg_restore` on the home-server Mac and run backup verification.
- Configure the Hermes scheduled reminder on the real Hermes client.
