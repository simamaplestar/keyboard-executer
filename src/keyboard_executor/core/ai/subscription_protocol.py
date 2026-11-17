"""訂閱 provider 共用的結構化輸出協定。"""
from __future__ import annotations

import json
from collections.abc import Callable

from keyboard_executor.core.ai.provider import AiProviderError, ChatResult, ToolCall
from keyboard_executor.core.ai.messages import (
    render_subscription_history,
    subscription_image_paths,
)
from keyboard_executor.core.ai.tools import TOOL_DEMO, TOOL_NAMES

TOOL_MARKER_OPEN = "\n<keyboard_executor_tool>"
TOOL_MARKER_CLOSE = "</keyboard_executor_tool>"


class SubscriptionStreamDecoder:
    """Stream plain answer text while withholding an optional tool marker.

    Enforcing one JSON schema makes Claude Code buffer the entire response.
    Subscription runtimes therefore emit normal text immediately and append a
    machine-readable marker only when proposing a script.  The marker is never
    forwarded to the UI; its payload still goes through the same strict parser.
    """

    def __init__(self, on_delta: Callable[[str], None]) -> None:
        self._on_delta = on_delta
        self._buffer = ""
        self._marker_data = ""
        self._visible = ""
        self._in_marker = False
        self._finished = False

    def _emit(self, text: str) -> None:
        if text:
            self._visible += text
            self._on_delta(text)

    def feed(self, chunk: str) -> None:
        if self._finished or not chunk:
            return
        if self._in_marker:
            self._marker_data += chunk
            return
        self._buffer += chunk
        marker_at = self._buffer.find(TOOL_MARKER_OPEN)
        if marker_at >= 0:
            self._emit(self._buffer[:marker_at])
            self._marker_data = self._buffer[marker_at + len(TOOL_MARKER_OPEN):]
            self._buffer = ""
            self._in_marker = True
            return
        # Keep only a suffix that could be the beginning of a split marker.
        keep = 0
        limit = min(len(self._buffer), len(TOOL_MARKER_OPEN) - 1)
        for size in range(limit, 0, -1):
            if TOOL_MARKER_OPEN.startswith(self._buffer[-size:]):
                keep = size
                break
        safe = self._buffer[:-keep] if keep else self._buffer
        self._emit(safe)
        self._buffer = self._buffer[-keep:] if keep else ""

    def finish(self, final_output: str | None = None) -> ChatResult:
        if self._finished:
            return ChatResult(self._visible)
        self._finished = True
        if final_output is not None:
            result = parse_subscription_output(final_output)
            if result.text.startswith(self._visible):
                self._emit(result.text[len(self._visible):])
            return result
        if not self._in_marker:
            self._emit(self._buffer)
            return ChatResult(self._visible)
        payload, separator, _tail = self._marker_data.partition(TOOL_MARKER_CLOSE)
        if not separator:
            raise AiProviderError("AI 訂閱服務回傳的腳本提案標記不完整")
        return ChatResult(self._visible, _parse_tool_marker(payload))


def parse_subscription_output(output: str) -> ChatResult:
    marker_at = output.find(TOOL_MARKER_OPEN)
    if marker_at < 0:
        return ChatResult(output)
    payload_start = marker_at + len(TOOL_MARKER_OPEN)
    marker_end = output.find(TOOL_MARKER_CLOSE, payload_start)
    if marker_end < 0:
        raise AiProviderError("AI 訂閱服務回傳的腳本提案標記不完整")
    return ChatResult(output[:marker_at],
                      _parse_tool_marker(output[payload_start:marker_end]))


def _parse_tool_marker(payload: str) -> ToolCall:
    try:
        data = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise AiProviderError("AI 訂閱服務回傳的腳本提案不是合法 JSON") from exc
    if (not isinstance(data, dict)
            or data.get("name") not in (*TOOL_NAMES, TOOL_DEMO)
            or not isinstance(data.get("args"), dict)):
        raise AiProviderError("AI 訂閱服務回傳的腳本提案格式不完整")
    return ToolCall(data["name"], data["args"])


def build_subscription_prompt(messages: list[dict], tools: list[dict], *,
                              expose_image_paths: bool = False) -> str:
    """把通用對話與工具定義交給無原生 function-call adapter 的 agent runtime。"""
    history = render_subscription_history(messages)
    paths = subscription_image_paths(messages)
    image_instruction = ""
    if paths:
        if expose_image_paths:
            listed = "\n".join(f"- 圖片附件 {i + 1}: {path}"
                               for i, path in enumerate(paths))
            image_instruction = (
                "\n本次對話含圖片附件。請先用 Read 工具逐張讀取下列唯讀圖片，"
                "再依使用者意圖回答或提案：\n" + listed + "\n")
        else:
            image_instruction = (
                f"\n本次對話含 {len(paths)} 張圖片，已依附件編號隨本次輸入附上。"
                "請實際查看圖片後再回答或提案。\n")
    return (
        "請直接以繁體中文純文字回覆這個應用程式內的使用者，不要把回答包成 JSON。\n"
        "若要提出腳本、規則或自動化套組，在回答文字結尾另起一行，附加且只附加一次：\n"
        f"{TOOL_MARKER_OPEN.lstrip()}"
        "{\"name\":\"工具名稱\",\"args\":{...}}"
        f"{TOOL_MARKER_CLOSE}\n"
        "若沒有提案，絕對不要輸出上述標記。標記前的內容會即時顯示給使用者。\n"
        "只能提出下列 App 工具；不可執行 shell、寫檔或自行修改專案。"
        "若本次含圖片且 runtime 提供 Read，只可唯讀列出的圖片附件：\n"
        f"{json.dumps(tools, ensure_ascii=False)}\n"
        f"{image_instruction}\n對話：\n{history}"
    )
