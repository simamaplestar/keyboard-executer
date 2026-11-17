"""Codex app-server account JSON-RPC client（OpenAI ChatGPT 訂閱登入）。"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from keyboard_executor.core.ai.auth.cli_bridge import (
    command_uses_wsl,
    macos_cli_prefix,
    wsl_cli_prefix,
)
from keyboard_executor.core.ai.auth.models import AuthError, AuthStatus
from keyboard_executor.platforms.common.process import background_process_options


class RpcClient(Protocol):
    def request(self, method: str, params: dict | None = None,
                timeout: float = 30.0) -> dict: ...
    def notify(self, method: str, params: dict | None = None) -> None: ...
    def close(self) -> None: ...


def codex_command(which: Callable[[str], str | None] = shutil.which, *,
                  run=subprocess.run, platform_name: str = os.name) -> list[str]:
    path = which("codex")
    if not path:
        prefix = wsl_cli_prefix("codex", which=which, run=run,
                                platform_name=platform_name)
        if prefix:
            return [*prefix, "app-server"]
        prefix = macos_cli_prefix("codex", run=run)
        if prefix:
            return [*prefix, "app-server"]
        raise AuthError(
            "找不到 Codex app-server，請先安裝 OpenAI Codex 並登入")
    if platform_name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c",
                path, "app-server"]
    return [path, "app-server"]


class JsonRpcProcess:
    """換行分隔 JSON-RPC 2.0 stdio transport；不記錄 payload/token。"""

    def __init__(self, command: list[str] | None = None, *, popen=subprocess.Popen,
                 on_notification: Callable[[str, dict], None] | None = None) -> None:
        command = command or codex_command()
        self.runs_in_wsl = command_uses_wsl(command)
        try:
            self._proc = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                               errors="replace", bufsize=1, **background_process_options())
        except OSError as exc:
            raise AuthError("無法啟動 Codex app-server") from exc
        if self._proc.stdin is None or self._proc.stdout is None:
            self._proc.kill()
            raise AuthError("Codex app-server stdio 無法使用")
        self._on_notification = on_notification or (lambda _m, _p: None)
        self._notification_handlers: list[Callable[[str, dict], None]] = []
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop,
                                        name="codex-app-server", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        try:
            for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if "id" in msg:
                    with self._lock:
                        target = self._pending.get(msg["id"])
                    if target is not None:
                        target.put(msg)
                elif isinstance(msg.get("method"), str):
                    try:
                        self._on_notification(msg["method"], msg.get("params") or {})
                    except Exception:
                        pass
                    for handler in list(self._notification_handlers):
                        try:
                            handler(msg["method"], msg.get("params") or {})
                        except Exception:
                            pass
        finally:
            with self._lock:
                waiting = list(self._pending.values())
            for target in waiting:
                target.put({"error": {"message": "Codex app-server 已停止"}})

    def request(self, method: str, params: dict | None = None,
                timeout: float = 30.0) -> dict:
        if self._closed:
            raise AuthError("Codex app-server 已關閉")
        target: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = target
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            try:
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self._pending.pop(request_id, None)
                raise AuthError("無法傳送資料給 Codex app-server") from exc
        try:
            response = target.get(timeout=timeout)
        except queue.Empty as exc:
            raise AuthError("Codex app-server 回應逾時") from exc
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if response.get("error"):
            message = response["error"].get("message", "未知錯誤")
            raise AuthError(f"Codex app-server 錯誤：{message}")
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def notify(self, method: str, params: dict | None = None) -> None:
        if self._closed:
            raise AuthError("Codex app-server 已關閉")
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        with self._lock:
            try:
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise AuthError("無法傳送資料給 Codex app-server") from exc

    def add_notification_handler(self, handler: Callable[[str, dict], None]) -> None:
        self._notification_handlers.append(handler)

    def remove_notification_handler(self, handler: Callable[[str, dict], None]) -> None:
        try:
            self._notification_handlers.remove(handler)
        except ValueError:
            pass

    def is_alive(self) -> bool:
        return not self._closed and self._proc.poll() is None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        self._reader.join(timeout=1)


@dataclass(frozen=True)
class LoginStart:
    login_id: str
    auth_url: str = ""
    user_code: str = ""
    verification_url: str = ""


class CodexAccountClient:
    def __init__(self, rpc: RpcClient) -> None:
        self._rpc = rpc

    def initialize(self) -> None:
        self._rpc.request("initialize", {
            "clientInfo": {"name": "keyboard-executor", "version": "1.0"},
            "capabilities": {},
        })
        self._rpc.notify("initialized", {})

    def status(self, *, refresh: bool = False) -> AuthStatus:
        result = self._rpc.request("account/read", {"refreshToken": refresh})
        account = result.get("account") or {}
        account_type = account.get("type")
        configured = account_type == "chatgpt"
        return AuthStatus(configured=configured, provider="openai",
                          profile_id="codex" if configured else "",
                          source="codex_app_server" if configured else "",
                          account_label=(account.get("email") or
                                         account.get("name") or ""))

    def start_login(self, *, device_code: bool = False) -> LoginStart:
        kind = "chatgptDeviceCode" if device_code else "chatgpt"
        result = self._rpc.request("account/login/start", {"type": kind})
        return LoginStart(login_id=str(result.get("loginId", "")),
                          auth_url=str(result.get("authUrl", "")),
                          user_code=str(result.get("userCode", "")),
                          verification_url=str(result.get("verificationUrl", "")))

    def cancel_login(self, login_id: str) -> None:
        self._rpc.request("account/login/cancel", {"loginId": login_id})

    def logout(self) -> None:
        self._rpc.request("account/logout", {})

    def list_models(self) -> tuple[tuple[str, str], ...]:
        """讀取可顯示的模型，保留 server 順序與 model（推論用 ID）。"""
        options: dict[str, str] = {}
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {"limit": 100, "includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            result = self._rpc.request("model/list", params, timeout=5.0)
            for item in result.get("data") or []:
                if not isinstance(item, dict) or item.get("hidden"):
                    continue
                model = item.get("model") or item.get("id")
                if isinstance(model, str) and model.strip():
                    label = item.get("displayName") or model
                    options.setdefault(model, str(label))
            cursor = result.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_cursors:
                raise AuthError("Codex 模型清單分頁無效")
            seen_cursors.add(cursor)
        return tuple((label, model) for model, label in options.items())

    def close(self) -> None:
        self._rpc.close()


class CodexAuthManager:
    """每個操作開一條短生命週期 app-server 連線；token 仍由 Codex 管理。"""

    def __init__(self, *, rpc_factory=JsonRpcProcess,
                 open_url=webbrowser.open, clock=time.monotonic) -> None:
        self._rpc_factory = rpc_factory
        self._open_url = open_url
        self._clock = clock

    def _with_client(self):
        rpc = self._rpc_factory()
        client = CodexAccountClient(rpc)
        try:
            client.initialize()
        except Exception:
            client.close()
            raise
        return client

    def status(self, *, refresh: bool = False) -> AuthStatus:
        client = self._with_client()
        try:
            return client.status(refresh=refresh)
        finally:
            client.close()

    def list_models(self) -> tuple[tuple[str, str], ...]:
        client = self._with_client()
        try:
            return client.list_models()
        finally:
            client.close()

    def login(self, *, device_code: bool = False,
              on_info: Callable[[dict], None] | None = None,
              should_abort: Callable[[], bool] | None = None,
              timeout: float = 180.0) -> AuthStatus:
        completed: queue.Queue[dict] = queue.Queue()

        def on_notification(method: str, params: dict) -> None:
            if method == "account/login/completed":
                completed.put(params)

        rpc = self._rpc_factory(on_notification=on_notification)
        client = CodexAccountClient(rpc)
        try:
            client.initialize()
            started = client.start_login(device_code=device_code)
            info = {"kind": "device_code" if device_code else "browser",
                    "auth_url": started.auth_url,
                    "verification_url": started.verification_url,
                    "user_code": started.user_code,
                    "login_id": started.login_id}
            if on_info:
                on_info(info)
            url = started.verification_url if device_code else started.auth_url
            if url:
                self._open_url(url)
            deadline = self._clock() + timeout
            while True:
                if should_abort and should_abort():
                    client.cancel_login(started.login_id)
                    raise AuthError("ChatGPT 登入已取消")
                left = deadline - self._clock()
                if left <= 0:
                    client.cancel_login(started.login_id)
                    raise AuthError("ChatGPT 登入逾時，請重試")
                try:
                    result = completed.get(timeout=min(0.25, left))
                    break
                except queue.Empty:
                    continue
            if result.get("loginId") not in (None, started.login_id):
                raise AuthError("收到不相符的 ChatGPT 登入結果")
            if not result.get("success"):
                raise AuthError("ChatGPT 登入失敗或已取消")
            return client.status(refresh=False)
        finally:
            client.close()

    def logout(self) -> None:
        client = self._with_client()
        try:
            client.logout()
        finally:
            client.close()
