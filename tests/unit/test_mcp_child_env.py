"""C0 item O: MCP server children get a minimal environment with only their own secrets."""

import pytest

from opspilot_mcp.gateway import child_env
from opspilot_shared.config import Settings

OPERATOR, SIGNING, APP_PW, READ_PW, ACT_PW = (
    "SENTINEL-operator-token-0001",
    "SENTINEL-signing-key-0002-xxxxxxxx",
    "SENTINEL-app-db-0003",
    "SENTINEL-read-db-0004",
    "SENTINEL-actions-db-0005",
)


def settings(**kw: object) -> Settings:
    base = {
        "operator_token": OPERATOR,
        "action_signing_key": SIGNING,
        "db_user": "opspilot_app",
        "db_password": APP_PW,
        "mcp_read_db_password": READ_PW,
        "mcp_actions_db_password": ACT_PW,
        "db_name": "opspilot_test",
    }
    return Settings(_env_file=None, **{**base, **kw})  # type: ignore[call-arg,arg-type]


@pytest.fixture(autouse=True)
def parent_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Secrets present in the parent's environment must not leak through inheritance.
    for k, v in {
        "OPERATOR_TOKEN": OPERATOR,
        "OPSPILOT_WEB_SESSION_SECRET": "SENTINEL-web-session",
        "OPSPILOT_WEB_OPERATOR_PASSPHRASE": "SENTINEL-web-pass",
        "POSTGRES_SUPERUSER_PASSWORD": "SENTINEL-superuser",
    }.items():
        monkeypatch.setenv(k, v)


def values(env: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in env.items())


def test_read_server_gets_its_role_and_no_other_secret() -> None:
    env = child_env(settings(), "read")
    dump = values(env)
    assert env["DB_USER"] == "opspilot_mcp_read" and env["DB_PASSWORD"] == READ_PW
    assert env["OPSPILOT_NO_DOTENV"] == "1" and env["DB_NAME"] == "opspilot_test"
    for secret in (OPERATOR, SIGNING, APP_PW, ACT_PW, "SENTINEL-web", "SENTINEL-superuser"):
        assert secret not in dump, secret
    assert "ACTION_SIGNING_KEY" not in env and "OPERATOR_TOKEN" not in env


def test_action_server_gets_the_verification_key_but_not_the_operator_token() -> None:
    env = child_env(settings(), "actions")
    dump = values(env)
    assert env["DB_USER"] == "opspilot_mcp_actions" and env["DB_PASSWORD"] == ACT_PW
    assert env["ACTION_SIGNING_KEY"] == SIGNING
    for secret in (OPERATOR, APP_PW, READ_PW, "SENTINEL-web", "SENTINEL-superuser"):
        assert secret not in dump, secret


def test_unprovisioned_roles_fall_back_to_the_application_role() -> None:
    env = child_env(settings(mcp_read_db_password=""), "read")
    assert env["DB_USER"] == "opspilot_app" and env["DB_PASSWORD"] == APP_PW
    assert OPERATOR not in values(env) and SIGNING not in values(env)


def test_child_settings_ignore_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    from opspilot_shared import config

    monkeypatch.setenv("OPSPILOT_NO_DOTENV", "1")
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    config.get_settings.cache_clear()
    try:
        assert config.get_settings().operator_token.get_secret_value() == ""  # .env not consulted
    finally:
        config.get_settings.cache_clear()
