# HomeAtlas TODO

## Next Commit Scope

- [x] Add a local operations CLI for PostgreSQL doctor/init/smoke flows.
- [x] Document local Mac PostgreSQL setup without assuming `psql` is on `PATH`.
- [x] Keep tests proving the local smoke path works through the same orchestrator and Action layer.

## Remaining Before Real Household Use

- [x] Add Docker Compose PostgreSQL for local deployment.
- [x] Verify against the running Docker PostgreSQL server on this Mac.
- [x] Configure the home-server process to use `HOME_ATLAS_DATABASE_URL` and `HOME_ATLAS_TOKEN_MAP`.
- [x] Adapt FastMCP streamable HTTP auth so Hermes sends only `home_atlas(request)` while the server extracts Bearer headers.
- [x] Add Pydantic AI parent/child Agent delegation with deterministic fallback when no LLM key is configured.
- [x] Fill `HOME_ATLAS_LLM_API_KEY` in local `.env` and run a live AI delegation smoke test.
- [x] Validate two-token flow locally: token A writes, token B reads, audit shows token A's actor.
- [ ] Validate two physical Hermes clients: token A writes, token B reads, audit shows token A's actor.
- [x] Add PostgreSQL concurrent-write integration tests.
- [x] Add launchd or another supervisor config.
- [x] Add `pg_dump` backup and restore verification command.
- [ ] Install `pg_dump`/`pg_restore` locally and run backup + restore verification.
- [x] Add Hermes scheduled reminder instructions around `list_expiring`.
- [ ] Configure the reminder in the real Hermes client.
