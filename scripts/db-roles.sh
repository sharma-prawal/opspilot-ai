#!/usr/bin/env bash
# Least-privilege database roles for the MCP server processes (C0 item O). Idempotent and additive:
# creates/updates two LOGIN roles and grants; never revokes from or drops anything else.
#
#   opspilot_mcp_read     SELECT on sim.* and kb.*, SELECT on ops.incidents, INSERT on kb.retrieval_queries
#   opspilot_mcp_actions  SELECT/INSERT/UPDATE on sim.* (no DELETE), SELECT on ops.action_requests,
#                         UPDATE of ops.action_requests.status only (the execution claim) and EXECUTE on
#                         ops.execution_fence (the claim's owner fence, C0-H2)
#
# Run after migrations (bootstrap does). Future sim/kb tables are covered by default privileges.
source "$(dirname "$0")/lib.sh"
load_env
SU=${POSTGRES_SUPERUSER:-postgres}
APP=${DB_USER:-opspilot_app}
READ=${MCP_READ_DB_USER:-opspilot_mcp_read}
ACT=${MCP_ACTIONS_DB_USER:-opspilot_mcp_actions}
[[ -n "${MCP_READ_DB_PASSWORD:-}" && -n "${MCP_ACTIONS_DB_PASSWORD:-}" ]] \
  || { fail "MCP_READ_DB_PASSWORD / MCP_ACTIONS_DB_PASSWORD not set in .env (run scripts/bootstrap.sh)"; exit 1; }
psql_su() { docker exec -i opspilot-postgres psql -v ON_ERROR_STOP=1 -U "$SU" "$@"; }

psql_su -d postgres -v r="$READ" -v rp="$MCP_READ_DB_PASSWORD" -v a="$ACT" -v ap="$MCP_ACTIONS_DB_PASSWORD" >/dev/null <<'SQL'
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', :'r')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'r') \gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', :'a')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'a') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'r', :'rp') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'a', :'ap') \gexec
SQL

for db in "$DB_NAME" "$TEST_DB_NAME"; do
  psql_su -d "$db" -v r="$READ" -v a="$ACT" -v app="$APP" -v db="$db" >/dev/null <<'SQL'
SET client_min_messages = warning;
SELECT format('GRANT CONNECT ON DATABASE %I TO %I, %I', :'db', :'r', :'a') \gexec
SELECT format('GRANT USAGE ON SCHEMA sim, kb, ops TO %I, %I', :'r', :'a') \gexec
-- read server
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA sim, kb TO %I', :'r') \gexec
SELECT format('GRANT SELECT ON ops.incidents TO %I', :'r') \gexec
SELECT format('GRANT INSERT ON kb.retrieval_queries TO %I', :'r') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA sim, kb GRANT SELECT ON TABLES TO %I', :'app', :'r') \gexec
-- action server
SELECT format('GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA sim TO %I', :'a') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sim TO %I', :'a') \gexec
SELECT format('GRANT SELECT ON ops.action_requests TO %I', :'a') \gexec
SELECT format('GRANT UPDATE (status) ON ops.action_requests TO %I', :'a') \gexec
-- C0-H2: the execution claim is fenced on the minting owner's epoch (function from migration 0008)
SELECT format('GRANT EXECUTE ON FUNCTION ops.execution_fence(bigint, integer) TO %I', :'a')
WHERE to_regprocedure('ops.execution_fence(bigint, integer)') IS NOT NULL \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA sim GRANT SELECT, INSERT, UPDATE ON TABLES TO %I', :'app', :'a') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA sim GRANT USAGE, SELECT ON SEQUENCES TO %I', :'app', :'a') \gexec
SQL
done
ok "MCP roles '$READ' and '$ACT' provisioned for '$DB_NAME' and '$TEST_DB_NAME'"
