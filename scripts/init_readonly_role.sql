-- Create a read-only role for external consumers (e.g. Hermes MCP postgres tool).
-- Mounted into /docker-entrypoint-initdb.d/ so it runs on first DB init.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'home_atlas_readonly') THEN
        CREATE ROLE home_atlas_readonly LOGIN PASSWORD 'home_atlas_ro';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE home_atlas TO home_atlas_readonly;
GRANT USAGE ON SCHEMA public TO home_atlas_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE home_atlas IN SCHEMA public
    GRANT SELECT ON TABLES TO home_atlas_readonly;

-- Cover tables that already exist at init time.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO home_atlas_readonly;
