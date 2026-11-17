import subprocess
import os
import json
import shutil
import shlex
from types import SimpleNamespace

import pytest

from keyboard_executor.core.ai.auth import cli_bridge
from keyboard_executor.core.ai.auth.claude_auth import claude_command
from keyboard_executor.core.ai.auth.codex_account import codex_command


def test_mac_finder_cli_prefix_forwards_arguments_without_interpolation():
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=(
            "Welcome to my shell\n"
            "__KEYBOARD_EXECUTOR_CLI__=/Users/測試 user/.local/bin/claude\n"
            "__KEYBOARD_EXECUTOR_PATH__=/Users/測試 user/.local/bin:/usr/bin:/bin\n"))
    prefix = cli_bridge.macos_cli_prefix("claude", run=run, platform_name="darwin")
    assert prefix == ["/usr/bin/env", "PATH=/Users/測試 user/.local/bin:/usr/bin:/bin",
                      "/Users/測試 user/.local/bin/claude"]
    assert calls[0][0][:2] == ["/bin/zsh", "-lic"]
    assert calls[0][0][-2:] == ["keyboard-executor", "claude"]
    assert calls[0][1]["timeout"] == 8
    assert not calls[0][1].get("shell", False)


@pytest.mark.parametrize("outcome", [None, "missing", "timeout"])
def test_mac_cli_probe_failure_returns_none(outcome):
    def run(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("zsh", 8)
        return SimpleNamespace(returncode=1 if outcome == "missing" else 0, stdout="")
    assert cli_bridge.macos_cli_prefix("codex", run=run, platform_name="darwin") is None


def test_non_mac_does_not_launch_login_shell():
    def unexpected(*args, **kwargs):
        pytest.fail("非 Mac 不應呼叫登入 shell")
    assert cli_bridge.macos_cli_prefix("codex", run=unexpected, platform_name="win32") is None


@pytest.mark.parametrize("command,tool,tail", [(claude_command, "claude", []),
                                            (codex_command, "codex", ["app-server"])])
def test_auth_commands_use_mac_login_shell_if_path_is_missing(monkeypatch, command, tool, tail):
    monkeypatch.setattr(cli_bridge.sys, "platform", "darwin")
    result = command(which=lambda name: None, platform_name="posix",
                     run=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=(
                         f"__KEYBOARD_EXECUTOR_CLI__=/opt/homebrew/bin/{tool}\n"
                         "__KEYBOARD_EXECUTOR_PATH__=/opt/homebrew/bin:/usr/bin:/bin\n")))
    assert result == ["/usr/bin/env", "PATH=/opt/homebrew/bin:/usr/bin:/bin",
                      f"/opt/homebrew/bin/{tool}", *tail]


@pytest.mark.skipif(os.name == "nt" or not shutil.which("zsh"), reason="需 Unix zsh")
def test_cli_json_is_clean_when_login_shell_prints_a_banner(tmp_path):
    tool = tmp_path / "CLI dir" / "claude"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\nprintf '%s\\n' '{\"loggedIn\": true}'\n")
    tool.chmod(0o755)
    (tmp_path / ".zshrc").write_text(
        f"print 'startup banner'\nexport PATH={shlex.quote(str(tool.parent))}:$PATH\n")
    shell_env = dict(os.environ, ZDOTDIR=str(tmp_path))
    def run(argv, **kwargs):
        return subprocess.run(argv, env=shell_env, **kwargs)
    prefix = cli_bridge.macos_cli_prefix("claude", run=run, platform_name="darwin")
    assert prefix is not None
    result = subprocess.run([*prefix, "auth", "status", "--json"],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"loggedIn": True}
