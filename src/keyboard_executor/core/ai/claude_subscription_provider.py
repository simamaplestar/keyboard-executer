"""以 Claude Code 登入或 setup-token 使用 Claude 訂閱。"""
from __future__ import annotations

import json
import os
import posixpath
import queue
import subprocess
from keyboard_executor.platforms.common.process import background_process_options
import threading
import time

from keyboard_executor.core.ai.auth.claude_auth import claude_command
from keyboard_executor.core.ai.auth.cli_bridge import command_uses_wsl, path_for_cli
from keyboard_executor.core.ai.auth.models import AuthError
from keyboard_executor.core.ai.messages import (
    subscription_image_paths,
    with_transformed_image_paths,
)
from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatProvider,
    ChatResult,
)
from keyboard_executor.core.ai.subscription_protocol import (
    SubscriptionStreamDecoder,
    build_subscription_prompt,
)


class _ClaudeStreamParser:
    """Parse Claude Code JSONL and forward each plain-text delta."""

    def __init__(self, on_delta) -> None:
        self._decoder = SubscriptionStreamDecoder(on_delta)
        self._final_value = None
        self._is_error = False

    def feed_line(self, line: str) -> None:
        try:
            message = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        if message.get("type") == "stream_event":
            event = message.get("event") or {}
            delta = event.get("delta") or {}
            if (event.get("type") == "content_block_delta"
                    and delta.get("type") == "text_delta"):
                self._decoder.feed(str(delta.get("text", "")))
        if message.get("type") == "result" or "structured_output" in message:
            self._is_error = bool(message.get("is_error"))
            self._final_value = message.get("structured_output")
            if self._final_value is None:
                self._final_value = message.get("result")

    def feed_output(self, output: str) -> None:
        for line in (output or "").splitlines():
            self.feed_line(line)

    def finish(self) -> ChatResult:
        if self._is_error:
            raise AiProviderError("Claude Code 回應失敗，請稍後再試")
        return self._decoder.finish(
            str(self._final_value) if self._final_value is not None else None)


class ClaudeSubscriptionProvider(ChatProvider):
    def __init__(self, model: str, *, oauth_token: str = "", run=None,
                 popen=subprocess.Popen, command_factory=claude_command) -> None:
        self._model = model
        self._oauth_token = oauth_token
        self._run = run
        self._popen = popen
        self._command_factory = command_factory

    def stream_chat(self, messages: list[dict], *, system: str,
                    tools: list[dict], on_delta, should_abort) -> ChatResult:
        if should_abort():
            raise AiAborted()
        try:
            command_prefix = self._command_factory()
        except AuthError as exc:
            raise AiProviderError(str(exc)) from exc
        uses_wsl = command_uses_wsl(command_prefix)
        runtime_messages = with_transformed_image_paths(
            messages, lambda path: path_for_cli(path, uses_wsl=uses_wsl))
        has_images = bool(subscription_image_paths(runtime_messages))
        command = [
            *command_prefix, "-p", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--permission-mode", "dontAsk", "--tools", "Read" if has_images else "",
            "--safe-mode",
            "--no-session-persistence",
            "--system-prompt", system,
        ]
        if self._model:
            prefix_len = len(command_prefix)
            command[prefix_len:prefix_len] = ["--model", self._model]
        if has_images:
            directories = []
            for path in subscription_image_paths(runtime_messages):
                parent = (posixpath.dirname(path) if path.startswith("/")
                          else os.path.dirname(path))
                if parent and parent not in directories:
                    directories.append(parent)
            for directory in directories:
                command.extend(["--add-dir", directory])
        env = os.environ.copy()
        # 訂閱模式絕不可被殘留的 API key 環境變數攔截，否則會產生非預期費用。
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        # setup-token 只交給官方 Claude Code；不自行猜測 Anthropic 私有 headers。
        if self._oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._oauth_token
            if uses_wsl:
                forwarded = [part for part in env.get("WSLENV", "").split(":")
                             if part]
                if not any(part.split("/", 1)[0] == "CLAUDE_CODE_OAUTH_TOKEN"
                           for part in forwarded):
                    forwarded.append("CLAUDE_CODE_OAUTH_TOKEN")
                env["WSLENV"] = ":".join(forwarded)
        prompt = build_subscription_prompt(runtime_messages, tools,
                                           expose_image_paths=has_images)
        parser = _ClaudeStreamParser(on_delta)
        try:
            if self._run is not None:  # 單測 seam
                completed = self._run(
                    command, input=prompt, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=env, timeout=180,
                    check=False, **background_process_options())
                parser.feed_output(completed.stdout)
                returncode, stderr = completed.returncode, completed.stderr or ""
            else:
                returncode, stderr = self._run_interruptible(
                    command, prompt, env, should_abort, parser)
        except subprocess.TimeoutExpired as exc:
            raise AiProviderError("Claude 訂閱回應逾時") from exc
        except OSError as exc:
            raise AiProviderError("無法啟動 Claude Code") from exc
        if should_abort():
            raise AiAborted()
        if returncode != 0:
            lowered = stderr.lower()
            if "login" in lowered or "auth" in lowered or "oauth" in lowered:
                raise AiProviderError("Claude 訂閱登入已失效，請重新連結")
            if "rate" in lowered or "limit" in lowered:
                raise AiProviderError("Claude 訂閱用量已達上限")
            raise AiProviderError("Claude Code 回應失敗，請檢查登入狀態")
        return parser.finish()

    def _run_interruptible(self, command, prompt, env, should_abort, parser):
        proc = self._popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace", env=env, bufsize=1, **background_process_options())
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            proc.kill()
            raise AiProviderError("Claude Code 串流管線無法使用")
        lines: queue.Queue[str | None] = queue.Queue()
        stderr_parts: list[str] = []

        def read_stdout() -> None:
            try:
                for line in proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        def read_stderr() -> None:
            stderr_parts.append(proc.stderr.read())

        stdout_thread = threading.Thread(target=read_stdout,
                                         name="claude-stream", daemon=True)
        stderr_thread = threading.Thread(target=read_stderr,
                                         name="claude-stderr", daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        try:
            deadline = time.monotonic() + 180
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (OSError, ValueError) as exc:
                raise AiProviderError("無法傳送資料給 Claude Code") from exc
            while True:
                if should_abort():
                    self._terminate(proc)
                    raise AiAborted()
                if time.monotonic() >= deadline:
                    self._terminate(proc)
                    raise AiProviderError("Claude 訂閱回應逾時")
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                parser.feed_line(line)
            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate(proc)
                raise AiProviderError("Claude Code 結束逾時")
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            return returncode, "".join(stderr_parts)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise

    @staticmethod
    def _terminate(proc) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
