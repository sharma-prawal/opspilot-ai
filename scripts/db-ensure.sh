#!/usr/bin/env bash
# Idempotently ensure the app role, app/test databases and pgvector extension exist.
# Safe to run repeatedly; never drops anything.
source "$(dirname "$0")/lib.sh"
load_env
SU=${POSTGRES_SUPERUSER:-postgres}
psql_su() { docker exec -i opspilot-postgres psql -v ON_ERROR_STOP=1 -U "$SU" "$@"; }

psql_su -d postgres -v app_user="$DB_USER" -v app_password="$DB_PASSWORD" >/dev/null <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'app_user', :'app_password') \gexec
SQL
for db in "$DB_NAME" "$TEST_DB_NAME"; do
  psql_su -d postgres -v db="$db" -v app_user="$DB_USER" >/dev/null <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL
  psql_su -d "$db" -c "SET client_min_messages = warning; CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
done
ok "database role '$DB_USER', databases '$DB_NAME' and '$TEST_DB_NAME', extension 'vector' present"
