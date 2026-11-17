import json
import subprocess

import pytest

from keyboard_executor.core.ai.auth.claude_auth import ClaudeAuthManager, claude_command
from keyboard_executor.core.ai.auth.models import AuthError
from keyboard_executor.core.ai.auth.secret_store import MemorySecretStore


def _done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def test_claude_cli_status_parses_subscription_account():
    manager = ClaudeAuthManager(
        MemorySecretStore(), which=lambda _n: "claude",
        run=lambda *a, **k: _done(json.dumps({
            "loggedIn": True, "authMethod": "claude.ai",
            "email": "me@example.test", "subscriptionType": "max"})))
    status = manager.cli_status()
    assert status.configured and status.profile_id == "claude-cli"
    assert status.account_label == "me@example.test"


def test_claude_cli_status_forces_utf8_for_wsl_output():
    seen = {}

    def run(*args, **kwargs):
        seen.update(kwargs)
        return _done(json.dumps({"loggedIn": True, "email": "測試@example.test"},
                                ensure_ascii=False))

    status = ClaudeAuthManager(
        MemorySecretStore(), which=lambda _n: "claude", run=run).cli_status()
    assert status.configured and status.account_label == "測試@example.test"
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_claude_cli_missing_is_actionable():
    with pytest.raises(AuthError, match="安裝"):
        ClaudeAuthManager(MemorySecretStore(), which=lambda _n: None).cli_status()


def test_claude_command_falls_back_to_wsl_on_windows():
    wsl = r"C:\Windows\System32\wsl.exe"
    paths = {"claude": None, "wsl.exe": wsl, "wsl": None}

    def probe(command, **_kwargs):
        assert command[-1] == "command -v claude"
        return _done("/home/u/bin/claude\n")

    assert claude_command(paths.get, run=probe, platform_name="nt") == [
        wsl, "-e", "bash", "-lc", 'exec claude "$@"', "claude"]


def test_setup_token_is_stored_outside_settings_and_deletable():
    store = MemorySecretStore()
    manager = ClaudeAuthManager(store)
    status = manager.save_setup_token("oauth-token-abcdefghijklmnopqrstuvwxyz")
    assert status.configured and status.profile_id == "setup-token"
    assert manager.get_setup_profile().access_token.startswith("oauth-token")
    manager.logout("setup-token")
    assert not manager.setup_token_status().configured


def test_setup_token_rejects_short_or_whitespace():
    manager = ClaudeAuthManager(MemorySecretStore())
    for value in ("short", "oauth-token has space xxxxxxxxx"):
        with pytest.raises(AuthError, match="格式"):
            manager.save_setup_token(value)
