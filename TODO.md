# HomeAtlas TODO

## Next Commit Scope

- [x] Add a local operations CLI for PostgreSQL doctor/init/smoke flows.
- [x] Document local Mac PostgreSQL setup without assuming `psql` is on `PATH`.
- [x] Keep tests proving the local smoke path works through the same orchestrator and Action layer.

## Remaining Before Real Household Use

- [x] Add Docker Compose PostgreSQL for local deployment.
- [x] Verify against the running Docker PostgreSQL server on this Mac.
- [ ] Configure the home-server process to use `HOME_ATLAS_DATABASE_URL` and `HOME_ATLAS_TOKEN_MAP`.
- [ ] Adapt FastMCP streamable HTTP auth so Hermes sends only `home_atlas(request)` while the server extracts Bearer headers.
- [ ] Replace deterministic routing with Pydantic AI multi-agent delegation.
- [ ] Validate two Hermes clients: token A writes, token B reads, audit shows token A's actor.
- [ ] Add PostgreSQL concurrent-write integration tests.
- [ ] Add launchd or another supervisor config.
- [ ] Add `pg_dump` backup and restore verification.
- [ ] Configure Hermes scheduled reminders around `list_expiring`.
