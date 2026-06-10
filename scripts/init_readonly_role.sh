#!/usr/bin/env bash
set -euo pipefail

: "${HOME_ATLAS_READONLY_PASSWORD:?set HOME_ATLAS_READONLY_PASSWORD in .env}"

if ! psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'home_atlas_readonly'" | grep -q 1; then
  psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v readonly_password="$HOME_ATLAS_READONLY_PASSWORD" <<'SQL'
CREATE ROLE home_atlas_readonly LOGIN PASSWORD :'readonly_password';
SQL
fi

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
GRANT CONNECT ON DATABASE home_atlas TO home_atlas_readonly;
GRANT USAGE ON SCHEMA public TO home_atlas_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE home_atlas IN SCHEMA public
    GRANT SELECT ON TABLES TO home_atlas_readonly;

-- Cover tables that already exist at init time.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO home_atlas_readonly;
SQL
