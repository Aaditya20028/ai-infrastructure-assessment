import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from task_02_security.auth import AuthenticationError, authenticate
from task_02_security.config import Settings
from task_02_security.policy import may_call_tool


@pytest.mark.parametrize("role,name,expected", [
    ("admin", "admin_reset_key", True), ("viewer", "admin_reset_key", False),
    ("viewer", "admin_nonexistent", False), ("viewer", "get_status", True),
    ("admin", "get_status", True), ("unknown", "get_status", False),
])
def test_role_policy(role, name, expected):
    assert may_call_tool(role, name) is expected


def test_verified_token_resolves_role_without_exposing_token(tokens):
    settings = Settings(token_roles={token: role for role, token in tokens.items()})
    assert authenticate(["bEaReR " + tokens["admin"]], settings) == "admin"
    assert authenticate(["Bearer " + tokens["viewer"]], settings) == "viewer"
    assert all(token not in repr(settings) for token in tokens.values())


@pytest.mark.parametrize("headers", [[], [""], ["Bearer"], ["Basic value"], ["Bearer viewer"], ["Bearer admin"], ["Bearer a b"], ["Bearer é"], ["Bearer fake", "Bearer other"]])
def test_invalid_authorization(headers, tokens):
    settings = Settings(token_roles={tokens["admin"]: "admin"})
    with pytest.raises(AuthenticationError):
        authenticate(headers, settings)


@pytest.mark.parametrize("changes", [
    {"token_roles": {}}, {"token_roles": {"short": "admin"}},
    {"token_roles": {"a" * 32: "superadmin"}}, {"timeout_seconds": 0},
    {"timeout_seconds": float("inf")}, {"max_request_bytes": -1},
    {"upstream_url": "file:///tmp/server"}, {"upstream_url": "http://user:password@localhost/mcp"},
    {"upstream_url": "http://localhost/mcp?token=hidden"}, {"upstream_url": "http://localhost/mcp#fragment"},
])
def test_invalid_config(changes, tokens):
    values = {"token_roles": {tokens["admin"]: "admin"}, **changes}
    with pytest.raises(ValidationError):
        Settings(**values)


def test_config_environment_and_missing_credentials(monkeypatch, tokens):
    monkeypatch.setenv("TASK2_TOKEN_ROLES", json.dumps({tokens["viewer"]: "viewer"}))
    monkeypatch.setenv("TASK2_TIMEOUT_SECONDS", "1.5")
    settings = Settings.from_env()
    assert settings.timeout_seconds == 1.5
    assert authenticate(["Bearer " + tokens["viewer"]], settings) == "viewer"
    monkeypatch.delenv("TASK2_TOKEN_ROLES")
    with pytest.raises(RuntimeError, match="Invalid Task 2 configuration"):
        Settings.from_env()


def test_cli_fails_closed_without_tokens():
    env = {key: value for key, value in os.environ.items() if not key.startswith("TASK2_")}
    result = subprocess.run([sys.executable, "-m", "task_02_security"], env=env,
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert "could not start" in result.stderr
    assert "Traceback" not in result.stderr
