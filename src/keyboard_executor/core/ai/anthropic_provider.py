"""Anthropic Messages API 串流實作（SSE + tool use）。"""
from __future__ import annotations

import json
import urllib.request

from keyboard_executor.core.ai.provider import (
    AiProviderError,
    ChatProvider,
    ChatResult,
    ToolCall,
    build_request,
    iter_sse_data,
    open_streaming,
)
from keyboard_executor.core.ai.messages import to_anthropic_messages

_URL = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"
_MAX_TOKENS = 4096


class AnthropicProvider(ChatProvider):
    def __init__(self, api_key: str, model: str, opener=None):
        self._api_key = api_key
        self._model = model
        self._opener = opener or urllib.request.urlopen

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        payload = {"model": self._model, "max_tokens": _MAX_TOKENS,
                   "stream": True, "system": system,
                   "messages": to_anthropic_messages(messages)}
        if tools:
            payload["tools"] = tools
        req = build_request(_URL, json.dumps(payload).encode("utf-8"),
                            {"x-api-key": self._api_key,
                             "anthropic-version": _VERSION})
        resp = open_streaming(self._opener, req)
        text_parts: list[str] = []
        tool_name: str | None = None
        tool_json_parts: list[str] = []
        try:
            for data in iter_sse_data(resp, should_abort):
                event = json.loads(data)
                etype = event.get("type")
                if etype == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        tool_name = block.get("name")
                elif etype == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text_parts.append(delta["text"])
                        on_delta(delta["text"])
                    elif delta.get("type") == "input_json_delta":
                        tool_json_parts.append(delta.get("partial_json", ""))
                elif etype == "message_stop":
                    break
        finally:
            resp.close()
        return ChatResult(text="".join(text_parts),
                          tool_call=_parse_tool(tool_name, tool_json_parts))


def _parse_tool(name: str | None, json_parts: list[str]) -> ToolCall | None:
    if not name:
        return None
    raw = "".join(json_parts) or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AiProviderError(f"AI 工具參數不是合法 JSON: {e}") from e
    if not isinstance(args, dict):
        raise AiProviderError("AI 工具參數必須是 JSON 物件")
    return ToolCall(name=name, args=args)
