"""Security verification for the web/BFF process environment allowlist.

Ensures that the Next.js process receives only allowlisted web and runtime settings,
and that backend-only credentials (database passwords, MCP role passwords, ACTION_SIGNING_KEY,
Ollama/LLM internals) are strictly excluded from the web process environment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from opspilot_shared.web_env import (
    BACKEND_DENYLIST_EXACT,
    BACKEND_DENYLIST_PREFIXES,
    WEB_ALLOWLIST,
    WEB_OPTIONAL_VARS,
    WEB_REQUIRED_VARS,
    build_web_env,
    is_backend_only,
)

# Sentinel tokens for testing secret isolation without using real credentials
SENTINEL_OPERATOR = "SENTINEL-operator-token-web-0001"
SENTINEL_SESSION_SECRET = "SENTINEL-session-secret-at-least-32-chars-long"
SENTINEL_OPERATOR_PASS = "SENTINEL-operator-pass-12-chars"
SENTINEL_VIEWER_PASS = "SENTINEL-viewer-pass-12-chars"

SENTINEL_DB_PASS = "SENTINEL-postgres-app-db-password-secret"
SENTINEL_SUPERUSER_PASS = "SENTINEL-postgres-superuser-secret-0002"
SENTINEL_MCP_READ_PASS = "SENTINEL-mcp-read-db-password-secret-0003"
SENTINEL_MCP_ACT_PASS = "SENTINEL-mcp-actions-db-password-secret-0004"
SENTINEL_SIGNING_KEY = "SENTINEL-action-signing-key-secret-0005"
SENTINEL_LOKI_TOKEN = "SENTINEL-loki-bearer-token-secret-0006"
SENTINEL_PROM_PASS = "SENTINEL-prometheus-password-secret-0007"


def make_sample_root_env() -> dict[str, str]:
    """Simulate a repository-root environment containing full .env configuration."""
    return {
        # Process / runtime
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/Users/opspilot",
        "TMPDIR": "/tmp",
        "NODE_ENV": "development",
        "SHELL": "/bin/zsh",
        "LANG": "en_US.UTF-8",
        # Web / BFF required
        "OPSPILOT_API_URL": "http://127.0.0.1:8000",
        "OPERATOR_TOKEN": SENTINEL_OPERATOR,
        "OPSPILOT_WEB_SESSION_SECRET": SENTINEL_SESSION_SECRET,
        "OPSPILOT_WEB_OPERATOR_PASSPHRASE": SENTINEL_OPERATOR_PASS,
        # Web / BFF optional
        "OPSPILOT_WEB_VIEWER_PASSPHRASE": SENTINEL_VIEWER_PASS,
        "OPSPILOT_WEB_ORIGIN": "http://127.0.0.1:3000",
        "OPSPILOT_ENV": "local",
        # Backend-only database credentials
        "POSTGRES_SUPERUSER": "postgres",
        "POSTGRES_SUPERUSER_PASSWORD": SENTINEL_SUPERUSER_PASS,
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "5433",
        "DB_NAME": "opspilot",
        "TEST_DB_NAME": "opspilot_test",
        "DB_USER": "opspilot_app",
        "DB_PASSWORD": SENTINEL_DB_PASS,
        "DB_POOL_SIZE": "5",
        "MCP_READ_DB_PASSWORD": SENTINEL_MCP_READ_PASS,
        "MCP_ACTIONS_DB_PASSWORD": SENTINEL_MCP_ACT_PASS,
        # Backend signing and approval settings
        "ACTION_SIGNING_KEY": SENTINEL_SIGNING_KEY,
        "APPROVAL_TOKEN_TTL_SECONDS": "900",
        "APPROVAL_REQUEST_TTL_SECONDS": "3600",
        # Backend LLM, Ollama, and agent settings
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "LLM_MODEL": "qwen3.5:9b-q4_K_M",
        "LLM_THINK": "false",
        "LLM_NUM_CTX": "8192",
        "EMBEDDING_MODEL": "qwen3-embedding:0.6b",
        "EMBEDDING_DIMENSIONS": "1024",
        "KNOWLEDGE_DIR": "datasets/synthetic/knowledge",
        "RETRIEVAL_TOP_K": "6",
        "CHUNK_MAX_WORDS": "220",
        "AGENT_MAX_TOOL_CALLS": "60",
        "LANGGRAPH_STRICT_MSGPACK": "true",
        # Connected observability credentials
        "LOKI_URL": "http://127.0.0.1:3100",
        "LOKI_BEARER_TOKEN": SENTINEL_LOKI_TOKEN,
        "PROMETHEUS_URL": "http://127.0.0.1:9090",
        "PROMETHEUS_PASSWORD": SENTINEL_PROM_PASS,
        # Tracing / internal
        "OTEL_EXPORTER": "none",
        "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    }


def test_build_web_env_includes_all_required_web_variables() -> None:
    source = make_sample_root_env()
    web_env = build_web_env(source)

    for req_key in WEB_REQUIRED_VARS:
        assert req_key in web_env, f"Required variable {req_key} missing from web environment"
        assert web_env[req_key] == source[req_key]


def test_build_web_env_includes_optional_and_runtime_variables() -> None:
    source = make_sample_root_env()
    web_env = build_web_env(source)

    for opt_key in WEB_OPTIONAL_VARS:
        if opt_key in source:
            assert web_env[opt_key] == source[opt_key]

    for rt_key in ("PATH", "HOME", "TMPDIR", "NODE_ENV", "SHELL", "LANG"):
        assert web_env[rt_key] == source[rt_key]


def test_build_web_env_excludes_database_credentials() -> None:
    source = make_sample_root_env()
    web_env = build_web_env(source)

    db_keys = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "TEST_DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_POOL_SIZE",
        "POSTGRES_SUPERUSER",
        "POSTGRES_SUPERUSER_PASSWORD",
        "MCP_READ_DB_PASSWORD",
        "MCP_ACTIONS_DB_PASSWORD",
    ]
    for key in db_keys:
        assert key not in web_env, f"Database credential key {key} leaked into web environment"


def test_build_web_env_excludes_signing_and_backend_secrets() -> None:
    source = make_sample_root_env()
    web_env = build_web_env(source)

    backend_keys = [
        "ACTION_SIGNING_KEY",
        "APPROVAL_TOKEN_TTL_SECONDS",
        "APPROVAL_REQUEST_TTL_SECONDS",
        "OLLAMA_BASE_URL",
        "LLM_MODEL",
        "LLM_THINK",
        "EMBEDDING_MODEL",
        "KNOWLEDGE_DIR",
        "RETRIEVAL_TOP_K",
        "CHUNK_MAX_WORDS",
        "AGENT_MAX_TOOL_CALLS",
        "LANGGRAPH_STRICT_MSGPACK",
        "LOKI_URL",
        "LOKI_BEARER_TOKEN",
        "PROMETHEUS_URL",
        "PROMETHEUS_PASSWORD",
        "OTEL_EXPORTER",
        "CORS_ALLOWED_ORIGINS",
    ]
    for key in backend_keys:
        assert key not in web_env, f"Backend configuration key {key} leaked into web environment"


def test_backend_secret_values_never_present_in_web_env() -> None:
    source = make_sample_root_env()
    web_env = build_web_env(source)

    backend_sentinels = [
        SENTINEL_DB_PASS,
        SENTINEL_SUPERUSER_PASS,
        SENTINEL_MCP_READ_PASS,
        SENTINEL_MCP_ACT_PASS,
        SENTINEL_SIGNING_KEY,
        SENTINEL_LOKI_TOKEN,
        SENTINEL_PROM_PASS,
    ]

    env_values = set(web_env.values())
    for sentinel in backend_sentinels:
        assert sentinel not in env_values, "Backend secret value leaked into web environment dictionary"


def test_allowlist_does_not_intersect_denylist() -> None:
    for allowed_key in WEB_ALLOWLIST:
        assert not is_backend_only(allowed_key), f"Allowlisted key {allowed_key} is a backend setting"
        assert allowed_key not in BACKEND_DENYLIST_EXACT
        for pfx in BACKEND_DENYLIST_PREFIXES:
            assert not allowed_key.startswith(pfx), f"Allowlisted key {allowed_key} starts with forbidden prefix {pfx}"


def test_child_process_environment_isolation(tmp_path: Path) -> None:
    """Verify that a spawned child process executing with build_web_env only sees allowlisted vars."""
    source = make_sample_root_env()
    web_env = build_web_env(source)

    # Run Python inline script to inspect the child process os.environ keys
    script = "import os, json; print(json.dumps(list(os.environ.keys())))"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=web_env,
    )

    import json

    child_keys = set(json.loads(proc.stdout))

    # Required variables must be in the child process
    for req in WEB_REQUIRED_VARS:
        assert req in child_keys, f"Child process missing {req}"

    # Backend secrets must not be in the child process
    for forbidden in (
        "DB_PASSWORD",
        "POSTGRES_SUPERUSER_PASSWORD",
        "ACTION_SIGNING_KEY",
        "MCP_READ_DB_PASSWORD",
        "MCP_ACTIONS_DB_PASSWORD",
        "LLM_MODEL",
        "OLLAMA_BASE_URL",
    ):
        assert forbidden not in child_keys, f"Child process received forbidden key {forbidden}"


FAKE_NEXT = """#!{python}
import json, os, subprocess, sys
out = os.environ.get("TMPDIR_PROBE_OUT") or sys.argv[0] + ".json"
grandchild = subprocess.run(
    [sys.executable, "-c", "import json, os; print(json.dumps(sorted(os.environ)))"],
    capture_output=True, text=True, check=True,
)
report = {{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "sid": os.getsid(0),
    "stdin_tty": os.isatty(0),
    "keys": sorted(os.environ),
    "values": sorted(os.environ.values()),
    "grandchild_keys": json.loads(grandchild.stdout),
}}
with open(out + ".tmp", "w") as fh:
    json.dump(report, fh)
os.replace(out + ".tmp", out)
"""


def test_spawn_web_server_detaches_and_isolates_descendants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real launcher path: allowlisted env for the server and its children, new session, apps/web cwd."""
    import json
    import os
    import time

    from opspilot_shared.web_env import spawn_web_server

    bin_dir = tmp_path / "apps/web/node_modules/.bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "next"
    fake.write_text(FAKE_NEXT.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)

    for key in list(os.environ):
        if key not in ("PATH", "HOME", "TMPDIR", "LANG"):
            monkeypatch.delenv(key, raising=False)
    for key, value in make_sample_root_env().items():
        if key not in ("PATH", "HOME", "TMPDIR"):
            monkeypatch.setenv(key, value)

    pid = spawn_web_server(root_dir=tmp_path, host="127.0.0.1", port=3999)

    report_path = Path(str(fake) + ".json")
    deadline = time.monotonic() + 20
    while not report_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert report_path.exists(), "fake web server did not run"
    report = json.loads(report_path.read_text())

    assert (tmp_path / ".run/web.pid").read_text().strip() == str(pid)
    assert (tmp_path / ".run/web.log").exists()
    assert report["argv"] == ["dev", "--hostname", "127.0.0.1", "--port", "3999"]
    assert Path(report["cwd"]).resolve() == (tmp_path / "apps/web").resolve()
    assert report["sid"] == pid, "web server must lead its own session (detached from the launcher)"
    assert report["sid"] != os.getsid(0)
    assert report["stdin_tty"] is False

    for keys in (set(report["keys"]), set(report["grandchild_keys"])):
        assert keys >= WEB_REQUIRED_VARS
        assert keys <= WEB_ALLOWLIST | {"PWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING", "__PYVENV_LAUNCHER__"}
        assert not any(is_backend_only(k) for k in keys)

    leaked = {
        SENTINEL_DB_PASS,
        SENTINEL_SUPERUSER_PASS,
        SENTINEL_MCP_READ_PASS,
        SENTINEL_MCP_ACT_PASS,
        SENTINEL_SIGNING_KEY,
        SENTINEL_LOKI_TOKEN,
        SENTINEL_PROM_PASS,
    } & set(report["values"])
    assert not leaked, "backend secret value reached the web process"
