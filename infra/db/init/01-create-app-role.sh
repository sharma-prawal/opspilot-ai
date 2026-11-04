#!/usr/bin/env bash
# Runs once, on first initialisation of the data volume (docker-entrypoint-initdb.d).
# Creates a non-superuser application role, the application and test databases,
# and the pgvector extension (which requires superuser to create).
# scripts/db-ensure.sh performs the same steps idempotently for existing volumes.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v app_user="$OPSPILOT_DB_USER" -v app_password="$OPSPILOT_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SQL

for db in "$OPSPILOT_DB_NAME" "$OPSPILOT_TEST_DB_NAME"; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -v db="$db" -v app_user="$OPSPILOT_DB_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" -c "CREATE EXTENSION IF NOT EXISTS vector;"
done
