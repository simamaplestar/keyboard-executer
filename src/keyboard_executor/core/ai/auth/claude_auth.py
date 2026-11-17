"""Claude Code 訂閱登入狀態與 setup-token 管理。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

from keyboard_executor.core.ai.auth.cli_bridge import macos_cli_prefix, wsl_cli_prefix
from keyboard_executor.core.ai.auth.models import AuthError, AuthProfile, AuthStatus
from keyboard_executor.core.ai.auth.secret_store import SecretStore
from keyboard_executor.platforms.common.process import background_process_options

_SETUP_PROFILE = "setup-token"


def claude_command(which=shutil.which, *, run=subprocess.run,
                   platform_name: str = os.name) -> list[str]:
    path = which("claude")
    if not path:
        prefix = wsl_cli_prefix("claude", which=which, run=run,
                                platform_name=platform_name)
        if prefix:
            return prefix
        prefix = macos_cli_prefix("claude", run=run)
        if prefix:
            return prefix
        raise AuthError(
            "找不到 Claude Code，請先安裝並登入 Claude Code")
    if platform_name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", path]
    return [path]


class ClaudeAuthManager:
    def __init__(self, secret_store: SecretStore, *, run=subprocess.run,
                 popen=subprocess.Popen, which=shutil.which,
                 sleep=time.sleep) -> None:
        self._store = secret_store
        self._run = run
        self._popen = popen
        self._which = which
        self._sleep = sleep

    def cli_status(self) -> AuthStatus:
        command = [*claude_command(self._which, run=self._run),
                   "auth", "status", "--json"]
        try:
            completed = self._run(command,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=15,
                                  check=False, **background_process_options())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuthError("無法讀取 Claude Code 登入狀態") from exc
        if completed.returncode != 0:
            return AuthStatus(configured=False, provider="anthropic")
        try:
            data = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise AuthError("Claude Code 登入狀態格式無法解析") from exc
        logged_in = bool(data.get("loggedIn"))
        label = data.get("email") or data.get("orgName") or ""
        return AuthStatus(configured=logged_in, provider="anthropic",
                          profile_id="claude-cli" if logged_in else "",
                          source="claude_cli" if logged_in else "",
                          account_label=str(label))

    def login_cli(self, should_abort=None) -> AuthStatus:
        command = [*claude_command(self._which, run=self._run), "auth", "login"]
        try:
            proc = self._popen(command)
        except OSError as exc:
            raise AuthError("無法啟動 Claude 登入") from exc
        deadline = time.monotonic() + 180
        while proc.poll() is None:
            if should_abort and should_abort():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise AuthError("Claude 登入已取消")
            if time.monotonic() >= deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                raise AuthError("Claude 登入逾時，請重試")
            self._sleep(0.1)
        if proc.returncode != 0:
            raise AuthError("Claude 登入未完成")
        status = self.cli_status()
        if not status.configured:
            raise AuthError("Claude 登入未完成")
        return status

    def setup_token_status(self) -> AuthStatus:
        profile = self._store.get("anthropic", _SETUP_PROFILE)
        return AuthStatus(configured=profile is not None, provider="anthropic",
                          profile_id=_SETUP_PROFILE if profile else "",
                          source="anthropic_setup_token" if profile else "",
                          account_label="Claude setup-token" if profile else "")

    def save_setup_token(self, token: str) -> AuthStatus:
        token = token.strip()
        if len(token) < 20 or any(c.isspace() for c in token):
            raise AuthError("Claude setup-token 格式不合法")
        self._store.put(AuthProfile(
            provider="anthropic", profile_id=_SETUP_PROFILE,
            access_token=token, source="anthropic_setup_token"))
        return self.setup_token_status()

    def get_setup_profile(self) -> AuthProfile | None:
        return self._store.get("anthropic", _SETUP_PROFILE)

    def logout(self, profile_id: str) -> None:
        if profile_id == _SETUP_PROFILE:
            self._store.delete("anthropic", _SETUP_PROFILE)
            return
        if profile_id != "claude-cli":
            return
        command = [*claude_command(self._which, run=self._run), "auth", "logout"]
        try:
            completed = self._run(command, timeout=30,
                                  check=False, **background_process_options())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AuthError("Claude 登出失敗") from exc
        if completed.returncode != 0:
            raise AuthError("Claude 登出失敗")
