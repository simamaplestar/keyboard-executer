"""以 Codex app-server 使用 ChatGPT/Codex 訂閱。"""
from __future__ import annotations

import queue
import tempfile

from keyboard_executor.core.ai.auth.codex_account import (
    CodexAccountClient,
    JsonRpcProcess,
)
from keyboard_executor.core.ai.auth.models import AuthError
from keyboard_executor.core.ai.auth.cli_bridge import path_for_cli
from keyboard_executor.core.ai.messages import (
    message_images,
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


class OpenAiSubscriptionProvider(ChatProvider):
    def __init__(self, model: str, *, rpc_factory=JsonRpcProcess,
                 reasoning_effort: str | None = None) -> None:
        self._model = model
        self._rpc_factory = rpc_factory
        self._requested_effort = reasoning_effort
        self._effort_checked = False
        self._effort = None

    def _resolve_effort(self, rpc, should_abort):
        if self._requested_effort is None or not self._model or self._effort_checked:
            return self._effort
        self._effort_checked = True
        # Resolve once per session. Unknown/custom models retain their defaults;
        # a slow/old model catalog must not prevent normal replies.
        cursor, visited = None, set()
        try:
            while not should_abort():
                params = {"limit": 100, "includeHidden": True}
                if cursor:
                    params["cursor"] = cursor
                page = rpc.request("model/list", params, timeout=2)
                for model in page.get("data") or []:
                    if not isinstance(model, dict):
                        continue
                    if model.get("model") == self._model:
                        supported = [item.get("reasoningEffort") for item in
                                     (model.get("supportedReasoningEfforts") or [])
                                     if isinstance(item, dict)]
                        if self._requested_effort in supported:
                            self._effort = self._requested_effort
                        return self._effort
                cursor = page.get("nextCursor")
                if not isinstance(cursor, str) or not cursor or cursor in visited:
                    break
                visited.add(cursor)
        except AuthError:
            pass
        return self._effort

    def stream_chat(self, messages: list[dict], *, system: str,
                    tools: list[dict], on_delta, should_abort) -> ChatResult:
        events: queue.Queue[tuple[str, dict]] = queue.Queue()
        rpc = None
        thread_id = turn_id = ""
        interrupted = False
        chunks: list[str] = []
        decoder = SubscriptionStreamDecoder(on_delta)

        def on_event(method: str, params: dict) -> None:
            events.put((method, params))

        try:
            rpc = self._rpc_factory(on_notification=on_event)
            account = CodexAccountClient(rpc)
            account.initialize()
            if not account.status(refresh=True).configured:
                raise AiProviderError("ChatGPT 訂閱尚未登入，請到設定重新連結")
            thread_params = {
                # Windows 打包版可自動使用 WSL 裡的 Codex；WSL app-server
                # 看不懂 C:\...，此時必須給 Linux 路徑。
                "cwd": "/tmp" if getattr(rpc, "runs_in_wsl", False)
                else tempfile.gettempdir(),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "baseInstructions": system,
                "developerInstructions": (
                    "你是 Keyboard Executor 的內建說明與腳本提案助手。"
                    "禁止執行工具、shell 或修改檔案，只輸出指定結構。"),
            }
            if self._model:
                thread_params["model"] = self._model
            started = rpc.request("thread/start", thread_params)
            thread_id = str((started.get("thread") or {}).get("id", ""))
            if not thread_id:
                raise AiProviderError("Codex 無法建立對話")
            uses_wsl = bool(getattr(rpc, "runs_in_wsl", False))
            runtime_messages = with_transformed_image_paths(
                messages, lambda path: path_for_cli(path, uses_wsl=uses_wsl))
            prompt = build_subscription_prompt(runtime_messages, tools)
            turn_input = [{"type": "text", "text": prompt}]
            image_no = 0
            for message in runtime_messages:
                for image in message_images(message):
                    if not image.get("path"):
                        continue
                    image_no += 1
                    turn_input.append({
                        "type": "text",
                        "text": f"圖片附件 {image_no}：{image.get('name', '圖片')}",
                    })
                    turn_input.append({"type": "localImage", "path": image["path"]})
            turn_params = {
                "threadId": thread_id,
                "input": turn_input,
                "approvalPolicy": "never",
            }
            effort = self._resolve_effort(rpc, should_abort)
            if effort is not None:
                turn_params["effort"] = effort
            if should_abort():
                raise AiAborted()
            turn = rpc.request("turn/start", turn_params)
            turn_id = str((turn.get("turn") or {}).get("id", ""))
            while True:
                if should_abort() and not interrupted:
                    interrupted = True
                    if turn_id:
                        try:
                            rpc.request("turn/interrupt", {
                                "threadId": thread_id, "turnId": turn_id}, timeout=5)
                        except AuthError:
                            pass  # turn 可能恰好已完成；下面仍以 completed/abort 收尾
                try:
                    method, params = events.get(timeout=0.1)
                except queue.Empty:
                    alive = getattr(rpc, "is_alive", lambda: True)
                    if not alive():
                        raise AiProviderError("Codex app-server 意外停止")
                    continue
                if params.get("threadId") not in (None, thread_id):
                    continue
                if method == "item/agentMessage/delta":
                    chunk = str(params.get("delta", ""))
                    chunks.append(chunk)
                    decoder.feed(chunk)
                elif method == "item/completed":
                    item = params.get("item") or {}
                    if item.get("type") == "agentMessage" and not chunks:
                        chunk = str(item.get("text", ""))
                        chunks.append(chunk)
                        decoder.feed(chunk)
                elif method == "turn/completed":
                    completed = params.get("turn") or {}
                    status = completed.get("status")
                    if interrupted or status == "interrupted":
                        raise AiAborted()
                    if status not in ("completed", None):
                        error = completed.get("error") or {}
                        code = error.get("codexErrorInfo")
                        if code == "usageLimitExceeded":
                            raise AiProviderError("ChatGPT/Codex 訂閱用量已達上限")
                        if code == "unauthorized":
                            raise AiProviderError("ChatGPT 訂閱登入已失效，請重新連結")
                        raise AiProviderError("Codex 回應失敗，請稍後再試")
                    break
            return decoder.finish("".join(chunks))
        except AiAborted:
            raise
        except AiProviderError:
            raise
        except AuthError as exc:
            raise AiProviderError(str(exc)) from exc
        except Exception as exc:
            raise AiProviderError("Codex app-server 執行失敗") from exc
        finally:
            if rpc is not None:
                rpc.close()
