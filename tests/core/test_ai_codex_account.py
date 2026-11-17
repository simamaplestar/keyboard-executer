import subprocess

import pytest

from keyboard_executor.core.ai.auth.codex_account import (
    CodexAccountClient,
    CodexAuthManager,
    codex_command,
)
from keyboard_executor.core.ai.auth.models import AuthError


class FakeRpc:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.closed = False

    def request(self, method, params=None, timeout=30.0):
        self.calls.append((method, params))
        return self.results.pop(0)

    def close(self):
        self.closed = True

    def notify(self, method, params=None):
        self.calls.append((method, params))


def test_codex_command_missing_is_actionable():
    with pytest.raises(AuthError, match="安裝 OpenAI Codex"):
        codex_command(lambda _name: None)


def test_codex_command_falls_back_to_wsl_on_windows():
    wsl = r"C:\Windows\System32\wsl.exe"
    paths = {"codex": None, "wsl.exe": wsl, "wsl": None}

    def probe(command, **_kwargs):
        assert command[-1] == "command -v codex"
        return subprocess.CompletedProcess(command, 0, stdout="/home/u/bin/codex\n")

    assert codex_command(paths.get, run=probe, platform_name="nt") == [
        wsl, "-e", "bash", "-lc", 'exec codex "$@"', "codex", "app-server"]


def test_account_initialize_status_and_browser_login():
    rpc = FakeRpc([
        {},
        {"account": {"type": "chatgpt", "email": "a@example.test",
                     "planType": "plus"}, "requiresOpenaiAuth": True},
        {"loginId": "login-1", "authUrl": "https://example.test/login"},
    ])
    account = CodexAccountClient(rpc)
    account.initialize()
    status = account.status(refresh=True)
    login = account.start_login()
    assert status.configured and status.profile_id == "codex"
    assert status.account_label == "a@example.test"
    assert login.login_id == "login-1" and login.auth_url.startswith("https://")
    assert rpc.calls[1] == ("initialized", {})
    assert rpc.calls[2] == ("account/read", {"refreshToken": True})
    assert rpc.calls[3] == ("account/login/start", {"type": "chatgpt"})


def test_device_login_cancel_logout_and_close():
    rpc = FakeRpc([
        {"loginId": "d", "userCode": "ABCD", "verificationUrl": "https://v"},
        {}, {},
    ])
    account = CodexAccountClient(rpc)
    login = account.start_login(device_code=True)
    account.cancel_login(login.login_id)
    account.logout()
    account.close()
    assert login.user_code == "ABCD"
    assert rpc.calls == [
        ("account/login/start", {"type": "chatgptDeviceCode"}),
        ("account/login/cancel", {"loginId": "d"}),
        ("account/logout", {}),
    ]
    assert rpc.closed


def test_auth_manager_waits_for_matching_login_completion():
    made = []

    class LoginRpc(FakeRpc):
        def __init__(self, on_notification=None):
            super().__init__([
                {},
                {"loginId": "login-1", "authUrl": "https://login"},
                {"account": {"type": "chatgpt", "email": "me@test",
                             "planType": "plus"}, "requiresOpenaiAuth": True},
            ])
            self.on_notification = on_notification

        def request(self, method, params=None, timeout=30.0):
            result = super().request(method, params, timeout)
            if method == "account/login/start":
                self.on_notification("account/login/completed", {
                    "loginId": "login-1", "success": True, "error": None})
            return result

    def factory(**kwargs):
        rpc = LoginRpc(kwargs.get("on_notification"))
        made.append(rpc)
        return rpc

    opened = []
    status = CodexAuthManager(rpc_factory=factory, open_url=opened.append).login()
    assert status.configured and status.account_label == "me@test"
    assert opened == ["https://login"] and made[0].closed


def test_auth_manager_cancel_aborts_pending_login_and_closes_rpc():
    made = []

    class PendingLoginRpc(FakeRpc):
        def __init__(self, on_notification=None):
            super().__init__([{}, {"loginId": "pending", "authUrl": ""}, {}])
            self.on_notification = on_notification

    def factory(**kwargs):
        rpc = PendingLoginRpc(kwargs.get("on_notification"))
        made.append(rpc)
        return rpc

    with pytest.raises(AuthError, match="已取消"):
        CodexAuthManager(rpc_factory=factory).login(should_abort=lambda: True)
    assert ("account/login/cancel", {"loginId": "pending"}) in made[0].calls
    assert made[0].closed


def test_model_discovery_paginates_filters_hidden_and_uses_model_id():
    rpc = FakeRpc([{}, {"data": [
        {"id": "picker-id", "model": "new-model", "displayName": "New Model"},
        {"id": "secret", "model": "secret", "hidden": True},
    ], "nextCursor": "page-2"}, {"data": [
        {"id": "older-cli-model", "displayName": "Older CLI"},
        {"model": "new-model", "displayName": "duplicate"},
    ], "nextCursor": None}])
    manager = CodexAuthManager(rpc_factory=lambda: rpc)
    assert manager.list_models() == (("New Model", "new-model"),
                                     ("Older CLI", "older-cli-model"))
    requests = [(method, params) for method, params in rpc.calls if method == "model/list"]
    assert requests[0][1]["includeHidden"] is False
    assert requests[1][1]["cursor"] == "page-2"
    assert rpc.closed


def test_model_discovery_error_closes_rpc():
    class BrokenRpc(FakeRpc):
        def request(self, method, params=None, timeout=30.0):
            if method == "model/list":
                raise AuthError("offline")
            return super().request(method, params, timeout)

    rpc = BrokenRpc([{}])
    with pytest.raises(AuthError, match="offline"):
        CodexAuthManager(rpc_factory=lambda: rpc).list_models()
    assert rpc.closed
