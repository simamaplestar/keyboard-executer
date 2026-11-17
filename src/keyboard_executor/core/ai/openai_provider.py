"""OpenAI Chat Completions 串流實作（SSE + tool calling）。"""
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
from keyboard_executor.core.ai.messages import to_openai_messages

_URL = "https://api.openai.com/v1/chat/completions"


class OpenAiProvider(ChatProvider):
    def __init__(self, api_key: str, model: str, opener=None, *, endpoint: str = _URL):
        self._api_key = api_key
        self._model = model
        self._opener = opener or urllib.request.urlopen
        self._endpoint = endpoint

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        payload = {"model": self._model, "stream": True,
                   "messages": ([{"role": "system", "content": system}]
                                + to_openai_messages(messages))}
        if tools:
            payload["tools"] = tools
        req = build_request(self._endpoint, json.dumps(payload).encode("utf-8"),
                            {"Authorization": f"Bearer {self._api_key}"})
        resp = open_streaming(self._opener, req)
        text_parts: list[str] = []
        tool_name: str | None = None
        tool_json_parts: list[str] = []
        finish_reason = None
        refused = False
        try:
            for data in iter_sse_data(resp, should_abort):
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise AiProviderError("AI 串流資料不是合法 JSON") from exc
                if not isinstance(event, dict):
                    raise AiProviderError("AI 串流資料格式不正確")
                if event.get("error"):
                    error = event["error"]
                    detail = (error.get("message", "未知錯誤")
                              if isinstance(error, dict) else str(error))
                    raise AiProviderError(f"AI 串流錯誤：{detail}")
                choices = event.get("choices") or []
                if not choices:
                    continue
                reason = choices[0].get("finish_reason")
                if reason is not None:
                    # Only protocol values may appear in diagnostics, never an
                    # arbitrary upstream string or the refusal/reasoning text.
                    finish_reason = (reason if reason in (
                        "stop", "length", "content_filter", "tool_calls",
                        "function_call", "error") else "未知")
                delta = choices[0].get("delta") or {}
                refused = refused or bool(delta.get("refusal"))
                content = delta.get("content")
                if content:
                    text_parts.append(content)
                    on_delta(content)
                for tc in delta.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        tool_name = fn["name"]
                    tool_json_parts.append(fn.get("arguments") or "")
        finally:
            resp.close()
        # A terminal limit/filter invalidates even syntactically complete
        # partial text or tool arguments. Consumers must not act on them.
        if finish_reason == "length":
            raise AiProviderError("AI 回覆因長度限制而中斷（finish_reason=length）")
        if finish_reason == "content_filter":
            raise AiProviderError("AI 回覆被內容篩選中止（finish_reason=content_filter）")
        text = "".join(text_parts)
        tool_call = _parse_tool(tool_name, tool_json_parts)
        if not text.strip() and tool_call is None:
            ending = f"（finish_reason={finish_reason or '未提供'}）"
            if refused:
                raise AiProviderError(f"AI 拒絕回覆，未回傳可使用的文字{ending}")
            raise AiProviderError(f"AI 回傳空白內容{ending}")
        return ChatResult(text=text, tool_call=tool_call)


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
