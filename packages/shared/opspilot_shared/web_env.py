"""Web/BFF process environment builder and detached launcher.

Generates a minimal, strictly allowlisted environment for the Next.js process,
preventing repository-root `.env` backend secrets (DB credentials, MCP database
passwords, ACTION_SIGNING_KEY, etc.) from leaking into the web runtime.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

# Required web / BFF configuration variables
WEB_REQUIRED_VARS: frozenset[str] = frozenset(
    {
        "OPSPILOT_API_URL",
        "OPERATOR_TOKEN",
        "OPSPILOT_WEB_SESSION_SECRET",
        "OPSPILOT_WEB_OPERATOR_PASSPHRASE",
    }
)

# Optional web / BFF runtime settings
WEB_OPTIONAL_VARS: frozenset[str] = frozenset(
    {
        "OPSPILOT_WEB_VIEWER_PASSPHRASE",
        "OPSPILOT_WEB_ORIGIN",
        "OPSPILOT_ENV",
        "OPSPILOT_WEB_DIST_DIR",
        "PORT",
        "HOSTNAME",
    }
)

# Essential host and Node/pnpm execution environment variables
PROCESS_PASSTHROUGH_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "SYSTEMROOT",
        "NODE_ENV",
        "NODE_OPTIONS",
        "PNPM_HOME",
        "NVM_DIR",
        "NVM_BIN",
        "NEXT_TELEMETRY_DISABLED",
    }
)

WEB_ALLOWLIST: frozenset[str] = frozenset(WEB_REQUIRED_VARS | WEB_OPTIONAL_VARS | PROCESS_PASSTHROUGH_VARS)

# Explicit denylist prefixes and exact keys for backend-only credentials and settings.
# Used for defensive validation to guarantee no backend secret ever leaks.
BACKEND_DENYLIST_PREFIXES: tuple[str, ...] = (
    "DB_",
    "POSTGRES_",
    "MCP_",
    "ACTION_SIGNING_",
    "APPROVAL_",
    "LLM_",
    "OLLAMA_",
    "EMBEDDING_",
    "KNOWLEDGE_",
    "CHUNK_",
    "RETRIEVAL_",
    "AGENT_",
    "RCA_",
    "TOOL_",
    "LOKI_",
    "PROMETHEUS_",
    "DATADOG_",
    "DD_",
    "AZURE_",  # v0.10: Azure Monitor settings and Microsoft Entra credentials
    "MSAL_",
    "IDENTITY_",  # managed identity endpoint/header variables
    "TELEMETRY_",
    "OTEL_",
    "LANGGRAPH_",
    "EXECUTION_OWNER_",
)

BACKEND_DENYLIST_EXACT: frozenset[str] = frozenset(
    {
        "ACTION_SIGNING_KEY",
        "POSTGRES_SUPERUSER",
        "POSTGRES_SUPERUSER_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "TEST_DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_POOL_SIZE",
        "MCP_READ_DB_PASSWORD",
        "MCP_ACTIONS_DB_PASSWORD",
        "MAX_CONCURRENT_INVESTIGATIONS",
        "MAX_PENDING_INVESTIGATIONS",
        "COMMAND_LEASE_SECONDS",
        "RUN_LEASE_SECONDS",
        "CORS_ALLOWED_ORIGINS",
    }
)


def is_backend_only(key: str) -> bool:
    """Check if an environment variable key is a backend-only setting or credential."""
    if key in BACKEND_DENYLIST_EXACT:
        return True
    return any(key.startswith(pfx) for pfx in BACKEND_DENYLIST_PREFIXES)


def build_web_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a sanitized environment dictionary for the Next.js process.

    Only allowlisted variables are passed. Any backend-only credentials or database
    secrets present in the source environment are strictly excluded.
    """
    src = os.environ if source is None else source
    env: dict[str, str] = {}
    for key in sorted(WEB_ALLOWLIST):
        if key in src:
            if is_backend_only(key):
                # Defensive check: allowlist must never intersect backend secrets
                continue
            env[key] = src[key]
    return env


def spawn_web_server(
    root_dir: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 3000,
) -> int:
    """Launch the Next.js dev server as a detached background process."""
    root_path = Path(os.environ.get("ROOT_DIR", ".")).resolve() if root_dir is None else Path(root_dir).resolve()

    run_dir = root_path / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "web.log"
    pid_path = run_dir / "web.pid"

    env = build_web_env()

    # Same command and working directory as `pnpm dev` in apps/web, minus pnpm's own environment additions.
    web_dir = root_path / "apps/web"
    next_bin = web_dir / "node_modules/.bin/next"
    cmd = [str(next_bin), "dev", "--hostname", host, "--port", str(port)]

    # Truncate like the API log (`>`), so a failed start shows only this attempt.
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
            cwd=str(web_dir),
        )

    pid_path.write_text(f"{proc.pid}\n", encoding="ascii")
    return proc.pid


if __name__ == "__main__":
    host_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    spawn_web_server(host=host_arg, port=port_arg)
