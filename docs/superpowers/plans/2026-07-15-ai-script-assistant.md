# AI 腳本助手（BYO 金鑰）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 主視窗右側可收合 AI 聊天面板：使用者自帶 Anthropic/OpenAI 金鑰，可問 App 用法、可讓 AI 產生/修改腳本（預覽卡片 → 套用才落地、可復原）。

**Architecture:** `core/ai/` 全部無 Qt、只用 stdlib urllib 自解 SSE（ChatProvider 抽象＋兩實作＋手冊/工具＋script_gen 驗證）；app 層擴充 Settings 與設定頁、`ai_worker` 包現有 `Worker` 背景串流、`ai_panel` QDockWidget 聊天面板、main_window 掛 dock。產出一律過既有 `script_from_dict` 驗證才可能落地。

**Tech Stack:** Python 3.11+、PySide6、stdlib urllib（SSE 串流）、pytest（offscreen Qt）。

**Spec:** `docs/superpowers/specs/2026-07-15-ai-script-assistant-design.md`

## Global Constraints

- **不新增任何依賴**：HTTP 一律 stdlib `urllib`（比照 `core/discord_notify.py`），不引入 httpx/anthropic/openai SDK。
- **`core/ai/` 不得 import 任何 Qt**（比照 core 層慣例）。
- 所有使用者可見文字與錯誤訊息一律**繁體中文**；例外不崩潰（spec §10 慣例）。
- 產出腳本**只有通過既有 `script_from_dict`/`action_from_dict` 驗證才可能落地**。
- system prompt 必含行為界線：只協助合法自動化；反偵測／反外掛繞過、CAPTCHA 辨識或繞過、背景視窗注入輸入等規避類請求一律婉拒。
- Settings 新欄位：`ai_provider`（`""`/`"anthropic"`/`"openai"` 白名單）、`ai_model`、`ai_api_key`（設了 provider 則 model 與 key 不可空白）、`ai_privacy_ack: bool`。
- 金鑰明文存本機 settings.json，設定頁**如實標示**。
- 測試命令（Windows venv、offscreen）：`QT_QPA_PLATFORM=offscreen python.exe -m pytest <path> -q`。基線 739 passed, 4 skipped，不得破壞既有測試。
- 分支：`feat/ai-script-assistant`（Task 1 Step 0 建立）。

---

## 檔案結構

| 檔案 | 責任 |
|------|------|
| `src/keyboard_executor/core/ai/__init__.py` | 空（套件宣告） |
| `src/keyboard_executor/core/ai/provider.py` | ToolCall/ChatResult dataclass、AiProviderError/AiAborted、ChatProvider ABC、共用 SSE 讀取與 HTTP 錯誤轉譯 |
| `src/keyboard_executor/core/ai/anthropic_provider.py` | Anthropic Messages API 串流實作 |
| `src/keyboard_executor/core/ai/openai_provider.py` | OpenAI Chat Completions 串流實作 |
| `src/keyboard_executor/core/ai/factory.py` | `make_provider(name, api_key, model)` |
| `src/keyboard_executor/core/ai/manual.py` | 內建使用手冊＋行為界線＋`build_system_prompt` |
| `src/keyboard_executor/core/ai/tools.py` | 兩個工具 schema＋`as_anthropic()`/`as_openai()` |
| `src/keyboard_executor/core/ai/script_gen.py` | 提案 → 既有驗證 → `Script` |
| `src/keyboard_executor/app/settings.py` | Settings 加 4 欄位＋驗證 |
| `src/keyboard_executor/app/settings_page.py` | 設定頁 AI 區塊 |
| `src/keyboard_executor/app/ai_worker.py` | `build_chat_job`：stream_chat → Worker job 契約 |
| `src/keyboard_executor/app/ai_panel.py` | 聊天面板（氣泡、串流、提案卡片、套用/復原） |
| `src/keyboard_executor/app/main_window.py` | 掛 QDockWidget、標題列「AI 助手」鈕、接線 |
| `src/keyboard_executor/app/theme.py` | 氣泡與卡片 QSS |

---

### Task 1: `core/ai/provider.py` — 型別、例外、ABC、共用 SSE/HTTP

**Files:**
- Create: `src/keyboard_executor/core/ai/__init__.py`（空檔）
- Create: `src/keyboard_executor/core/ai/provider.py`
- Test: `tests/core/test_ai_provider.py`

**Interfaces:**
- Consumes: 無（純 stdlib）。
- Produces（後續所有 task 依賴，簽名固定）:
  - `@dataclass(frozen=True) ToolCall(name: str, args: dict)`
  - `@dataclass(frozen=True) ChatResult(text: str, tool_call: ToolCall | None = None)`
  - `class AiProviderError(Exception)`（訊息繁中）、`class AiAborted(Exception)`
  - `class ChatProvider(ABC)` 帶抽象方法 `stream_chat(self, messages: list[dict], *, system: str, tools: list[dict], on_delta, should_abort) -> ChatResult`
  - `build_request(url: str, body: bytes, headers: dict) -> urllib.request.Request`
  - `open_streaming(opener, req, timeout: float = 60.0)`（HTTP 錯誤 → AiProviderError 繁中）
  - `iter_sse_data(resp, should_abort) -> Iterator[str]`（每個 `data:` 行的 payload；行間檢查 abort → 拋 AiAborted）

- [ ] **Step 0: 建分支**

```bash
git checkout -b feat/ai-script-assistant
```

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_ai_provider.py`：

```python
"""core/ai/provider.py：型別、SSE 讀取、HTTP 錯誤轉譯（純 stdlib，無 Qt）。"""
import io
import urllib.error

import pytest

from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatResult,
    ToolCall,
    build_request,
    iter_sse_data,
    open_streaming,
)


def _sse(*lines: str) -> io.BytesIO:
    return io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def test_chat_result_defaults_no_tool_call():
    r = ChatResult(text="hi")
    assert r.text == "hi" and r.tool_call is None
    tc = ToolCall(name="propose_new_script", args={"name": "x"})
    assert tc.args["name"] == "x"


def test_build_request_sets_user_agent_and_headers():
    req = build_request("https://api.example.com/v1", b"{}",
                        {"x-api-key": "k"})
    assert req.get_header("User-agent", "").startswith("KeyboardExecutor/")
    assert req.get_header("X-api-key") == "k"
    assert req.get_header("Content-type") == "application/json"
    assert req.data == b"{}"


def test_iter_sse_data_yields_data_lines_only():
    resp = _sse("event: ping", "", "data: {\"a\": 1}", "data: [DONE]")
    got = list(iter_sse_data(resp, should_abort=lambda: False))
    assert got == ['{"a": 1}', "[DONE]"]


def test_iter_sse_data_abort_raises():
    resp = _sse("data: 1", "data: 2")
    it = iter_sse_data(resp, should_abort=lambda: True)
    with pytest.raises(AiAborted):
        next(it)


def test_open_streaming_maps_http_401_to_key_error():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO())
    with pytest.raises(AiProviderError, match="金鑰無效或無權限"):
        open_streaming(opener, build_request("https://x/", b"", {}))


def test_open_streaming_maps_429_to_rate_limit():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO())
    with pytest.raises(AiProviderError, match="速率上限"):
        open_streaming(opener, build_request("https://x/", b"", {}))


def test_open_streaming_maps_urlerror_to_connect_error():
    def opener(req, timeout):
        raise urllib.error.URLError("dns fail")
    with pytest.raises(AiProviderError, match="連線失敗"):
        open_streaming(opener, build_request("https://x/", b"", {}))


def test_open_streaming_other_http_code_in_message():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO())
    with pytest.raises(AiProviderError, match="HTTP 500"):
        open_streaming(opener, build_request("https://x/", b"", {}))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_provider.py -q`
Expected: FAIL（ModuleNotFoundError: keyboard_executor.core.ai）

- [ ] **Step 3: 實作**

`src/keyboard_executor/core/ai/__init__.py`：空檔。

`src/keyboard_executor/core/ai/provider.py`：

```python
"""AI 供應商抽象層（純 stdlib：urllib/json，無 Qt、不新增依賴）。

ChatProvider.stream_chat 是唯一介面：messages 用內部通用格式
[{"role": "user"|"assistant", "content": str}, ...]，各實作自行轉自家 payload。
SSE 逐行讀取，on_delta 即時回吐文字；should_abort 於行間檢查（True → AiAborted）。
傳輸/HTTP 例外一律包成 AiProviderError（繁中訊息），由呼叫端（Worker job）隔離。"""
from __future__ import annotations

import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

_USER_AGENT = "KeyboardExecutor/1.0"


class AiProviderError(Exception):
    """AI 供應商呼叫失敗（訊息為繁中、可直接顯示）。"""


class AiAborted(Exception):
    """使用者中止串流。"""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_call: ToolCall | None = None


class ChatProvider(ABC):
    @abstractmethod
    def stream_chat(self, messages: list[dict], *, system: str,
                    tools: list[dict], on_delta: Callable[[str], None],
                    should_abort: Callable[[], bool]) -> ChatResult: ...


def build_request(url: str, body: bytes, headers: dict) -> urllib.request.Request:
    merged = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    merged.update(headers)
    return urllib.request.Request(url, data=body, headers=merged)


def open_streaming(opener, req: urllib.request.Request, timeout: float = 60.0):
    """開啟串流回應；HTTP/網路錯誤 → AiProviderError（繁中）。"""
    try:
        return opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        if code in (401, 403):
            raise AiProviderError("API 金鑰無效或無權限，請檢查設定") from e
        if code == 429:
            raise AiProviderError("已達供應商速率上限，請稍後再試") from e
        raise AiProviderError(f"AI 服務回應錯誤（HTTP {code}）") from e
    except urllib.error.URLError as e:
        raise AiProviderError(f"連線失敗：{e.reason}") from e
    except OSError as e:
        raise AiProviderError(f"連線失敗：{e}") from e


def iter_sse_data(resp, should_abort: Callable[[], bool]) -> Iterator[str]:
    """逐行讀 SSE，yield 每個 `data:` 行的 payload 字串；行間檢查 abort。"""
    for raw in iter(resp.readline, b""):
        if should_abort():
            raise AiAborted()
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith("data:"):
            yield line[5:].strip()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_provider.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/ai/ tests/core/test_ai_provider.py
git commit -m "feat(ai): provider 抽象層與共用 SSE/HTTP（純 stdlib）"
```

---

### Task 2: `core/ai/anthropic_provider.py`

**Files:**
- Create: `src/keyboard_executor/core/ai/anthropic_provider.py`
- Test: `tests/core/test_ai_anthropic.py`

**Interfaces:**
- Consumes: Task 1 的 `ChatProvider`、`ChatResult`、`ToolCall`、`AiProviderError`、`build_request`、`open_streaming`、`iter_sse_data`。
- Produces: `AnthropicProvider(api_key: str, model: str, opener=None)`，實作 `stream_chat`。tools 參數格式＝Anthropic 原生（`{"name","description","input_schema"}`，Task 4 的 `as_anthropic()` 輸出）。

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_ai_anthropic.py`：

```python
"""AnthropicProvider：payload 組裝與 SSE 解析（fake opener，不打網路）。"""
import io
import json

import pytest

from keyboard_executor.core.ai.anthropic_provider import AnthropicProvider
from keyboard_executor.core.ai.provider import AiAborted, AiProviderError


class FakeOpener:
    def __init__(self, sse_lines):
        self.requests = []
        self._body = ("\n".join(sse_lines) + "\n").encode("utf-8")

    def __call__(self, req, timeout):
        self.requests.append(req)
        return io.BytesIO(self._body)


def _event(obj) -> str:
    return "data: " + json.dumps(obj)


def _provider(lines):
    opener = FakeOpener(lines)
    return AnthropicProvider(api_key="sk-test", model="claude-sonnet-5",
                             opener=opener), opener


def test_payload_has_model_system_messages_tools_stream():
    p, opener = _provider([_event({"type": "message_stop"})])
    p.stream_chat([{"role": "user", "content": "hi"}], system="SYS",
                  tools=[{"name": "t", "description": "d", "input_schema": {}}],
                  on_delta=lambda t: None, should_abort=lambda: False)
    req = opener.requests[0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "claude-sonnet-5"
    assert body["system"] == "SYS"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["tools"][0]["name"] == "t"
    assert body["stream"] is True and body["max_tokens"] == 4096
    assert req.get_header("X-api-key") == "sk-test"
    assert req.get_header("Anthropic-version") == "2023-06-01"


def test_text_deltas_stream_and_accumulate():
    p, _ = _provider([
        _event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你"}}),
        _event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "好"}}),
        _event({"type": "message_stop"}),
    ])
    deltas = []
    r = p.stream_chat([{"role": "user", "content": "hi"}], system="s", tools=[],
                      on_delta=deltas.append, should_abort=lambda: False)
    assert deltas == ["你", "好"] and r.text == "你好" and r.tool_call is None


def test_tool_use_args_accumulate_across_partial_json():
    p, _ = _provider([
        _event({"type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "propose_new_script"}}),
        _event({"type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '{"name": "打'}}),
        _event({"type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": '怪"}'}}),
        _event({"type": "message_stop"}),
    ])
    r = p.stream_chat([{"role": "user", "content": "做腳本"}], system="s", tools=[],
                      on_delta=lambda t: None, should_abort=lambda: False)
    assert r.tool_call.name == "propose_new_script"
    assert r.tool_call.args == {"name": "打怪"}


def test_invalid_tool_json_raises_provider_error():
    p, _ = _provider([
        _event({"type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "propose_new_script"}}),
        _event({"type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": "{oops"}}),
        _event({"type": "message_stop"}),
    ])
    with pytest.raises(AiProviderError, match="不是合法 JSON"):
        p.stream_chat([{"role": "user", "content": "x"}], system="s", tools=[],
                      on_delta=lambda t: None, should_abort=lambda: False)


def test_abort_mid_stream_raises_aborted():
    p, _ = _provider([_event({"type": "content_block_delta",
                              "delta": {"type": "text_delta", "text": "a"}})] * 5)
    calls = {"n": 0}

    def should_abort():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(AiAborted):
        p.stream_chat([{"role": "user", "content": "x"}], system="s", tools=[],
                      on_delta=lambda t: None, should_abort=should_abort)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_anthropic.py -q`
Expected: FAIL（ModuleNotFoundError: anthropic_provider）

- [ ] **Step 3: 實作**

`src/keyboard_executor/core/ai/anthropic_provider.py`：

```python
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
                   "stream": True, "system": system, "messages": messages}
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_anthropic.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/ai/anthropic_provider.py tests/core/test_ai_anthropic.py
git commit -m "feat(ai): AnthropicProvider（Messages API SSE + tool use）"
```

---

### Task 3: `core/ai/openai_provider.py` ＋ `factory.py`

**Files:**
- Create: `src/keyboard_executor/core/ai/openai_provider.py`
- Create: `src/keyboard_executor/core/ai/factory.py`
- Test: `tests/core/test_ai_openai.py`

**Interfaces:**
- Consumes: Task 1 同上。
- Produces:
  - `OpenAiProvider(api_key: str, model: str, opener=None)`，tools 格式＝OpenAI 原生（`{"type":"function","function":{...}}`，Task 4 的 `as_openai()` 輸出）。
  - `factory.make_provider(provider: str, api_key: str, model: str) -> ChatProvider | None`（`""`/未知 → None）。

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_ai_openai.py`：

```python
"""OpenAiProvider：payload 組裝與 SSE 解析；make_provider 工廠。"""
import io
import json

from keyboard_executor.core.ai.anthropic_provider import AnthropicProvider
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.openai_provider import OpenAiProvider


class FakeOpener:
    def __init__(self, sse_lines):
        self.requests = []
        self._body = ("\n".join(sse_lines) + "\n").encode("utf-8")

    def __call__(self, req, timeout):
        self.requests.append(req)
        return io.BytesIO(self._body)


def _chunk(delta) -> str:
    return "data: " + json.dumps({"choices": [{"delta": delta}]})


def _provider(lines):
    opener = FakeOpener(lines)
    return OpenAiProvider(api_key="sk-test", model="gpt-5-mini",
                          opener=opener), opener


def test_payload_prepends_system_and_sets_bearer():
    p, opener = _provider(["data: [DONE]"])
    p.stream_chat([{"role": "user", "content": "hi"}], system="SYS",
                  tools=[{"type": "function", "function": {"name": "t"}}],
                  on_delta=lambda t: None, should_abort=lambda: False)
    req = opener.requests[0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gpt-5-mini" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}
    assert body["tools"][0]["function"]["name"] == "t"
    assert req.get_header("Authorization") == "Bearer sk-test"


def test_content_deltas_stream_and_done_terminates():
    p, _ = _provider([_chunk({"content": "你"}), _chunk({"content": "好"}),
                      "data: [DONE]"])
    deltas = []
    r = p.stream_chat([{"role": "user", "content": "hi"}], system="s", tools=[],
                      on_delta=deltas.append, should_abort=lambda: False)
    assert deltas == ["你", "好"] and r.text == "你好" and r.tool_call is None


def test_tool_call_name_and_arguments_accumulate():
    p, _ = _provider([
        _chunk({"tool_calls": [{"index": 0, "function":
                                {"name": "propose_edit_current", "arguments": '{"acti'}}]}),
        _chunk({"tool_calls": [{"index": 0, "function":
                                {"arguments": 'ons": []}'}}]}),
        "data: [DONE]",
    ])
    r = p.stream_chat([{"role": "user", "content": "x"}], system="s", tools=[],
                      on_delta=lambda t: None, should_abort=lambda: False)
    assert r.tool_call.name == "propose_edit_current"
    assert r.tool_call.args == {"actions": []}


def test_make_provider_dispatch():
    assert isinstance(make_provider("anthropic", "k", "m"), AnthropicProvider)
    assert isinstance(make_provider("openai", "k", "m"), OpenAiProvider)
    assert make_provider("", "k", "m") is None
    assert make_provider("unknown", "k", "m") is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_openai.py -q`
Expected: FAIL（ModuleNotFoundError: openai_provider）

- [ ] **Step 3: 實作**

`src/keyboard_executor/core/ai/openai_provider.py`：

```python
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

_URL = "https://api.openai.com/v1/chat/completions"


class OpenAiProvider(ChatProvider):
    def __init__(self, api_key: str, model: str, opener=None):
        self._api_key = api_key
        self._model = model
        self._opener = opener or urllib.request.urlopen

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        payload = {"model": self._model, "stream": True,
                   "messages": [{"role": "system", "content": system}] + messages}
        if tools:
            payload["tools"] = tools
        req = build_request(_URL, json.dumps(payload).encode("utf-8"),
                            {"Authorization": f"Bearer {self._api_key}"})
        resp = open_streaming(self._opener, req)
        text_parts: list[str] = []
        tool_name: str | None = None
        tool_json_parts: list[str] = []
        try:
            for data in iter_sse_data(resp, should_abort):
                if data == "[DONE]":
                    break
                event = json.loads(data)
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
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
```

`src/keyboard_executor/core/ai/factory.py`：

```python
"""依設定建立 ChatProvider；providers 不互相 import，工廠獨立一檔避免循環。"""
from __future__ import annotations

from keyboard_executor.core.ai.anthropic_provider import AnthropicProvider
from keyboard_executor.core.ai.openai_provider import OpenAiProvider
from keyboard_executor.core.ai.provider import ChatProvider


def make_provider(provider: str, api_key: str, model: str) -> ChatProvider | None:
    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if provider == "openai":
        return OpenAiProvider(api_key=api_key, model=model)
    return None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_openai.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/ai/openai_provider.py src/keyboard_executor/core/ai/factory.py tests/core/test_ai_openai.py
git commit -m "feat(ai): OpenAiProvider（Chat Completions SSE）與 make_provider 工廠"
```

---

### Task 4: `core/ai/manual.py` ＋ `core/ai/tools.py`

**Files:**
- Create: `src/keyboard_executor/core/ai/manual.py`
- Create: `src/keyboard_executor/core/ai/tools.py`
- Test: `tests/core/test_ai_manual_tools.py`

**Interfaces:**
- Consumes: 無。
- Produces:
  - `manual.build_system_prompt(current_script_json: str | None) -> str`
  - `tools.as_anthropic() -> list[dict]`、`tools.as_openai() -> list[dict]`
  - 工具名稱常數：`TOOL_NEW = "propose_new_script"`、`TOOL_EDIT = "propose_edit_current"`（Task 9 面板依名稱分派）。

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_ai_manual_tools.py`：

```python
"""manual/tools：system prompt 內容與雙供應商工具格式。"""
from keyboard_executor.core.ai.manual import build_system_prompt
from keyboard_executor.core.ai.tools import TOOL_EDIT, TOOL_NEW, as_anthropic, as_openai


def test_system_prompt_contains_manual_and_boundary():
    p = build_system_prompt(None)
    for needle in ("key_combo", "wait_text", "loop", "監看規則",
                   "反偵測", "驗證碼", "婉拒"):
        assert needle in p
    assert "目前沒有選中的腳本" in p


def test_system_prompt_embeds_current_script_json():
    p = build_system_prompt('{"name": "打怪"}')
    assert '{"name": "打怪"}' in p and "目前選中的腳本" in p


def test_anthropic_tools_shape():
    tools = as_anthropic()
    names = {t["name"] for t in tools}
    assert names == {TOOL_NEW, TOOL_EDIT}
    for t in tools:
        assert set(t) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
    new = next(t for t in tools if t["name"] == TOOL_NEW)
    assert set(new["input_schema"]["required"]) == {"name", "target_title_regex", "actions"}


def test_openai_tools_shape():
    tools = as_openai()
    for t in tools:
        assert t["type"] == "function"
        assert set(t["function"]) == {"name", "description", "parameters"}
    edit = next(t for t in tools if t["function"]["name"] == TOOL_EDIT)
    assert edit["function"]["parameters"]["required"] == ["actions"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_manual_tools.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 實作**

`src/keyboard_executor/core/ai/manual.py`：

```python
"""內建使用手冊（App cheat-sheet）＋行為界線 → system prompt。

手冊描述功能與腳本 JSON 格式（給模型引導用）；嚴格驗證在 script_gen 走
既有 script_from_dict，這裡的描述不是安全網。功能變動時同步維護本檔。"""
from __future__ import annotations

APP_MANUAL = """\
你是「Keyboard Executor」桌面自動化工具內建的 AI 助手。請一律用繁體中文回答。

# App 功能總覽
- 腳本（Script）：一連串動作（按鍵/滑鼠/等待/迴圈…），對指定視窗回放。
- 錄製：全域熱鍵開始/停止錄製操作，自動存成腳本。
- 監看規則（Rule）：獨立輪詢畫面（OCR 文字/圖像模板/顏色），命中即觸發執行腳本、
  全部停止或 Discord 通知。監看與腳本執行彼此獨立。
- 每個腳本可設啟動快捷鍵（設定於腳本編輯器）；緊急停止熱鍵可在設定頁改。
- 主視窗左側是腳本清單、右側是規則清單；腳本編輯器可視覺化編輯動作與迴圈。

# 腳本 JSON 格式
{"name": 名稱, "target_window": {"title_pattern": 視窗標題regex, "app_name": 可選},
 "settings": 可省略, "actions": [動作...]}

## 動作類型與欄位（type + 參數）
- key_press: {"key": 按鍵名, "hold_ms": 可選 >=0}
- key_combo: {"keys": [按鍵名...], "hold_ms": 可選 >=0（按住毫秒，0=點按）}
- text_input: {"text": 字串}
- mouse_move: {"x", "y"}（視窗相對座標）
- mouse_click: {"x", "y", "button": "left"/"right"/"middle", "count": 可選 >=1}
- mouse_drag: {"from": [x,y], "to": [x,y], "button": 同上}
- scroll: {"x", "y", "dx": 可選, "dy": 可選}
- delay: {"ms": 毫秒整數 或 [min,max] 隨機區間}
- loop: {"count": -1（無限）或 >=1, "actions": [動作...]}
- run_script: {"script_name": 名稱}
- wait_text: {"pattern", "mode": "contains"/"regex", "region": 可選 [x,y,w,h],
  "timeout_ms": 可選, "on_timeout": "abort"/"continue"/"goto", "goto_index": goto 時必填}
- wait_image: {"template": 模板名, "threshold": 可選 0~1, 其餘同 wait_text}
- if_text: {"pattern", "mode", "region": 可選, "then": [動作...], "else": 可選 [動作...]}
- if_image: {"template", "threshold": 可選, "then", "else": 可選}
- click_text: {"pattern", "mode", "region": 可選}
- click_image: {"template", "threshold": 可選, "region": 可選}

按鍵名一律小寫英文，例如 a、b、1、enter、space、tab、esc、shift、ctrl、alt、
up、down、left、right、f1～f12。座標為目標視窗相對座標。

# 工具使用
- 使用者要「建立新腳本」→ 呼叫 propose_new_script（name、target_title_regex、actions）。
- 使用者要「修改目前選中的腳本」→ 呼叫 propose_edit_current（actions＝改完的完整動作清單）。
- 提案只是預覽，使用者按「套用」才會儲存；不確定的參數先問清楚再提案。
- 圖像類動作（wait_image/if_image/click_image）需要使用者先在「模板管理」擷取模板，
  提案前請確認模板名稱。
"""

BOUNDARY = """\
# 行為界線（必須遵守）
只協助本工具的合法自動化用途（辦公重複作業、一般遊戲腳本操作等）。
以下請求一律婉拒並簡短說明原因，不提供替代作法：
- 反偵測、反外掛/反作弊繞過、隱匿自動化痕跡
- 驗證碼（CAPTCHA）辨識或繞過
- 對背景（非前景）視窗注入輸入等規避類手法
"""


def build_system_prompt(current_script_json: str | None) -> str:
    parts = [APP_MANUAL, BOUNDARY]
    if current_script_json:
        parts.append("# 目前選中的腳本\n```json\n" + current_script_json + "\n```")
    else:
        parts.append("（目前沒有選中的腳本；使用者若要修改腳本，請先請他在清單中選取。）")
    return "\n\n".join(parts)
```

`src/keyboard_executor/core/ai/tools.py`：

```python
"""AI 工具（function calling）schema：單一來源，輸出雙供應商格式。"""
from __future__ import annotations

TOOL_NEW = "propose_new_script"
TOOL_EDIT = "propose_edit_current"

_ACTIONS_SCHEMA = {
    "type": "array",
    "description": "動作清單；每個元素是 {\"type\": 動作類型, ...參數}，"
                   "類型與欄位見 system prompt 的動作說明。",
    "items": {"type": "object"},
}

_TOOLS = [
    {
        "name": TOOL_NEW,
        "description": "提案建立一個新腳本。使用者會先預覽、按「套用」才會儲存。",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "腳本名稱（不含 / 與 \\）"},
                "target_title_regex": {"type": "string",
                                       "description": "目標視窗標題的 regex"},
                "actions": _ACTIONS_SCHEMA,
            },
            "required": ["name", "target_title_regex", "actions"],
        },
    },
    {
        "name": TOOL_EDIT,
        "description": "提案修改目前選中的腳本：以 actions 整份取代其動作清單。"
                       "使用者會先預覽、按「套用」才會儲存。",
        "schema": {
            "type": "object",
            "properties": {"actions": _ACTIONS_SCHEMA},
            "required": ["actions"],
        },
    },
]


def as_anthropic() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["schema"]} for t in _TOOLS]


def as_openai() -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["schema"]}} for t in _TOOLS]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_manual_tools.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/ai/manual.py src/keyboard_executor/core/ai/tools.py tests/core/test_ai_manual_tools.py
git commit -m "feat(ai): 內建使用手冊/行為界線 system prompt 與工具 schema"
```

---

### Task 5: `core/ai/script_gen.py` — 提案驗證

**Files:**
- Create: `src/keyboard_executor/core/ai/script_gen.py`
- Test: `tests/core/test_ai_script_gen.py`

**Interfaces:**
- Consumes: 既有 `core.models`：`Script`、`script_from_dict`、`script_to_dict`、`ScriptValidationError`。
- Produces:
  - `script_from_proposal(name: str, target_title_regex: str, actions: list) -> Script`
  - `actions_for_edit(current: Script, actions: list) -> Script`（保留 name/target/settings，只換 actions，整份重驗）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_ai_script_gen.py`：

```python
"""script_gen：AI 提案 → 既有 script_from_dict 全套驗證（安全網）。"""
import pytest

from keyboard_executor.core.ai.script_gen import actions_for_edit, script_from_proposal
from keyboard_executor.core.models import ScriptValidationError, script_from_dict


def test_valid_proposal_builds_script():
    s = script_from_proposal("打怪", "遊戲.*", [
        {"type": "key_press", "key": "a"},
        {"type": "delay", "ms": 500},
        {"type": "loop", "count": 3, "actions": [{"type": "key_press", "key": "b"}]},
    ])
    assert s.name == "打怪"
    assert s.target_window.title_pattern == "遊戲.*"
    assert len(s.actions) == 3
    assert s.settings.speed == 1.0   # 預設 settings


def test_unknown_action_type_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "t", [{"type": "hack_the_game"}])


def test_missing_field_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "t", [{"type": "key_press"}])   # 缺 key


def test_bad_name_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("a/b", "t", [{"type": "key_press", "key": "a"}])


def test_bad_regex_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "[", [{"type": "key_press", "key": "a"}])


def _current():
    return script_from_dict({
        "name": "原本", "target_window": {"title_pattern": "app"},
        "settings": {"speed": 2.0, "repeat": 5, "hotkey": "f6"},
        "actions": [{"type": "key_press", "key": "a"}],
    })


def test_edit_replaces_actions_keeps_everything_else():
    edited = actions_for_edit(_current(), [{"type": "delay", "ms": 100},
                                           {"type": "key_press", "key": "b"}])
    assert edited.name == "原本"
    assert edited.settings.speed == 2.0 and edited.settings.repeat == 5
    assert edited.settings.hotkey == "f6"
    assert [str(a.type) for a in edited.actions] == ["delay", "key_press"]


def test_edit_invalid_actions_rejected():
    with pytest.raises(ScriptValidationError):
        actions_for_edit(_current(), [])
    with pytest.raises(ScriptValidationError):
        actions_for_edit(_current(), [{"type": "nope"}])
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_script_gen.py -q`
Expected: FAIL（ModuleNotFoundError: script_gen）

- [ ] **Step 3: 實作**

`src/keyboard_executor/core/ai/script_gen.py`：

```python
"""AI 提案 → Script。安全網：一律走既有 script_from_dict 全套驗證，
不支援的動作類型、缺欄位、型別錯誤全數 ScriptValidationError（繁中）。"""
from __future__ import annotations

from keyboard_executor.core.models import Script, script_from_dict, script_to_dict


def script_from_proposal(name: str, target_title_regex: str,
                         actions: list) -> Script:
    """propose_new_script 的 args → Script（settings 用預設值）。"""
    return script_from_dict({
        "name": name,
        "target_window": {"title_pattern": target_title_regex},
        "actions": actions,
    })


def actions_for_edit(current: Script, actions: list) -> Script:
    """propose_edit_current：保留 current 的 name/target/settings，只換 actions。"""
    data = script_to_dict(current)
    data["actions"] = actions
    return script_from_dict(data)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_ai_script_gen.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/ai/script_gen.py tests/core/test_ai_script_gen.py
git commit -m "feat(ai): script_gen 提案驗證（走既有 script_from_dict 安全網）"
```

---

### Task 6: Settings 四欄位 ＋ 設定頁 AI 區塊

**Files:**
- Modify: `src/keyboard_executor/app/settings.py`（`Settings` dataclass ＋ `validate_settings`）
- Modify: `src/keyboard_executor/app/settings_page.py`（AI 區塊 ＋ `_on_save`）
- Test: `tests/app/test_ai_settings.py`（新檔）

**Interfaces:**
- Consumes: 既有 `Settings`、`validate_settings`、`SettingsStore`、`SettingsPage`。
- Produces: `Settings` 新欄位 `ai_provider: str = ""`、`ai_model: str = ""`、`ai_api_key: str = ""`、`ai_privacy_ack: bool = False`。`SettingsPage` 新屬性 `ai_provider_combo`（QComboBox，userData 為 `""`/`"anthropic"`/`"openai"`）、`ai_model_edit`、`ai_key_edit`（Password echo）。

- [ ] **Step 1: 寫失敗測試**

`tests/app/test_ai_settings.py`：

```python
"""Settings AI 欄位驗證與設定頁 AI 區塊。"""
import pytest

from keyboard_executor.app.settings import Settings, SettingsStore, validate_settings
from keyboard_executor.core.models import ScriptValidationError


def test_defaults_ai_disabled():
    s = Settings()
    assert s.ai_provider == "" and s.ai_model == "" and s.ai_api_key == ""
    assert s.ai_privacy_ack is False
    validate_settings(s)   # 預設值必須合法


def test_provider_whitelist():
    with pytest.raises(ScriptValidationError, match="ai_provider"):
        validate_settings(Settings(ai_provider="gemini", ai_model="m", ai_api_key="k"))


def test_provider_set_requires_model_and_key():
    with pytest.raises(ScriptValidationError, match="ai_model"):
        validate_settings(Settings(ai_provider="anthropic", ai_model="", ai_api_key="k"))
    with pytest.raises(ScriptValidationError, match="ai_api_key"):
        validate_settings(Settings(ai_provider="openai", ai_model="m", ai_api_key=""))


def test_values_normalized_stripped():
    s = validate_settings(Settings(ai_provider="anthropic",
                                   ai_model=" claude-sonnet-5 ",
                                   ai_api_key=" sk-x "))
    assert s.ai_model == "claude-sonnet-5" and s.ai_api_key == "sk-x"


def test_round_trip_through_store(tmp_path):
    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_model="gpt-5-mini",
                        ai_api_key="sk-1", ai_privacy_ack=True))
    loaded = store.load()
    assert loaded.ai_provider == "openai" and loaded.ai_privacy_ack is True


def test_settings_page_has_ai_fields_and_saves(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_privacy_ack=True))   # 既有 ack 不可被頁面存檔洗掉
    page = SettingsPage(store, permission_checks={})
    idx = page.ai_provider_combo.findData("anthropic")
    page.ai_provider_combo.setCurrentIndex(idx)
    page.ai_model_edit.setText("claude-sonnet-5")
    page.ai_key_edit.setText("sk-test")
    page._on_save()
    loaded = store.load()
    assert loaded.ai_provider == "anthropic"
    assert loaded.ai_model == "claude-sonnet-5"
    assert loaded.ai_api_key == "sk-test"
    assert loaded.ai_privacy_ack is True   # 保留，不被重設


def test_settings_page_key_field_password_echo(qapp, tmp_path):
    from PySide6.QtWidgets import QLineEdit

    from keyboard_executor.app.settings_page import SettingsPage

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert page.ai_key_edit.echoMode() == QLineEdit.EchoMode.Password
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_settings.py -q`
Expected: FAIL（Settings 無 ai_provider 欄位）

- [ ] **Step 3: 實作**

`src/keyboard_executor/app/settings.py` — `Settings` 加欄位：

```python
@dataclass(frozen=True)
class Settings:
    toggle_key: str = "f9"
    stop_key: str = "f10"
    ocr_language: str = "auto"
    log_level: str = "INFO"
    discord_webhook_url: str = ""
    corner_failsafe: bool = True
    ai_provider: str = ""        # ""=停用 / "anthropic" / "openai"
    ai_model: str = ""
    ai_api_key: str = ""         # 明文存本機 settings.json（設定頁如實標示）
    ai_privacy_ack: bool = False  # 首次送出的隱私告知已確認
```

`validate_settings` 在 `corner_failsafe` 檢查之後、`return` 之前加：

```python
    ai_provider = settings.ai_provider.strip()
    if ai_provider not in ("", "anthropic", "openai"):
        raise ScriptValidationError(
            f"設定 ai_provider 必須是空白、anthropic 或 openai: {ai_provider!r}")
    ai_model = settings.ai_model.strip()
    ai_key = settings.ai_api_key.strip()
    if ai_provider:
        if not ai_model:
            raise ScriptValidationError("設定 ai_model 不可空白（已選擇 AI 供應商）")
        if not ai_key:
            raise ScriptValidationError("設定 ai_api_key 不可空白（已選擇 AI 供應商）")
    if not isinstance(settings.ai_privacy_ack, bool):
        raise ScriptValidationError(
            f"設定 ai_privacy_ack 必須是布林值: {settings.ai_privacy_ack!r}")
```

並把 `return replace(...)` 擴為：

```python
    return replace(settings, toggle_key=toggle, stop_key=stop,
                   discord_webhook_url=webhook, ai_provider=ai_provider,
                   ai_model=ai_model, ai_api_key=ai_key)
```

`src/keyboard_executor/app/settings_page.py` — `corner_failsafe_check` 那個 `addRow` 之後、權限列之前加 AI 區塊（記得 import `QComboBox` 已在、`QLineEdit` 已在）：

```python
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("停用", "")
        self.ai_provider_combo.addItem("Anthropic Claude", "anthropic")
        self.ai_provider_combo.addItem("OpenAI GPT", "openai")
        idx = self.ai_provider_combo.findData(settings.ai_provider)
        self.ai_provider_combo.setCurrentIndex(max(0, idx))
        layout.addRow("AI 助手供應商", self.ai_provider_combo)
        self.ai_model_edit = QLineEdit(settings.ai_model)
        self.ai_model_edit.setPlaceholderText("如 claude-sonnet-5（Anthropic）/ gpt-5-mini（OpenAI）")
        layout.addRow("AI model", self.ai_model_edit)
        self.ai_key_edit = QLineEdit(settings.ai_api_key)
        self.ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("AI API 金鑰", self.ai_key_edit)
        ai_note = QLabel("金鑰以明文儲存於本機 settings.json")
        ai_note.setWordWrap(True)
        layout.addRow("", ai_note)
```

`_on_save` 的 `Settings(...)` 建構加（注意保留 ack —— 從 `self._store.load()` 帶）：

```python
    def _on_save(self) -> None:
        current = self._store.load()   # 保留頁面沒編輯的欄位（ai_privacy_ack）
        try:
            self._store.save(Settings(
                toggle_key=self.toggle_edit.text().strip(),
                stop_key=self.stop_edit.text().strip(),
                ocr_language=self.ocr_edit.text().strip(),
                log_level=self.level_combo.currentText(),
                discord_webhook_url=self.discord_edit.text().strip(),
                corner_failsafe=self.corner_failsafe_check.isChecked(),
                ai_provider=self.ai_provider_combo.currentData(),
                ai_model=self.ai_model_edit.text().strip(),
                ai_api_key=self.ai_key_edit.text().strip(),
                ai_privacy_ack=current.ai_privacy_ack))
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")
            return
        self.status_label.setText("已儲存，已即時套用（執行中的維持原設定）")
        self.saved.emit(self._store.load())
        self.accept()
```

- [ ] **Step 4: 跑測試確認通過（含既有設定測試不破）**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_settings.py tests/app -q -k "settings"`
Expected: 新測試 7 passed；既有 settings 相關測試全過。

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings.py src/keyboard_executor/app/settings_page.py tests/app/test_ai_settings.py
git commit -m "feat(ai): Settings AI 欄位（provider/model/key/privacy_ack）與設定頁區塊"
```

---

### Task 7: `app/ai_worker.py` — stream_chat → Worker job

**Files:**
- Create: `src/keyboard_executor/app/ai_worker.py`
- Test: `tests/app/test_ai_worker.py`

**Interfaces:**
- Consumes: Task 1 `ChatProvider`/`ChatResult`/`AiAborted`；既有 `app/worker.py` 的 `Worker`（job 契約：`job(progress) -> Any`；例外 → `failed`）。
- Produces: `build_chat_job(provider, messages: list[dict], *, system: str, tools: list[dict], abort_event: threading.Event) -> Callable`。job 回傳 `ChatResult`；使用者中止 → 回傳 `None`（不是 failed）；`AiProviderError` 原樣拋出（Worker 轉 failed）。

- [ ] **Step 1: 寫失敗測試**

`tests/app/test_ai_worker.py`：

```python
"""build_chat_job：delta → progress、結果/中止/錯誤的 Worker 契約。"""
import threading

import pytest

from keyboard_executor.app.ai_worker import build_chat_job
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatProvider,
    ChatResult,
)


class FakeProvider(ChatProvider):
    def __init__(self, result=None, deltas=(), error=None):
        self.result = result or ChatResult(text="done")
        self.deltas = deltas
        self.error = error
        self.seen = None

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.seen = {"messages": messages, "system": system, "tools": tools}
        for d in self.deltas:
            on_delta(d)
        if should_abort():
            raise AiAborted()
        if self.error:
            raise self.error
        return self.result


def _run(job):
    """用 Worker 同步跑 job（run() 直接呼叫＝當前執行緒執行）。"""
    events = {"progress": [], "finished": [], "failed": []}
    w = Worker(job)
    w.progress.connect(events["progress"].append)
    w.finished.connect(events["finished"].append)
    w.failed.connect(events["failed"].append)
    w.run()
    return events


def test_deltas_flow_through_progress(qapp):
    p = FakeProvider(result=ChatResult(text="你好"), deltas=["你", "好"])
    ev = _run(build_chat_job(p, [{"role": "user", "content": "hi"}],
                             system="s", tools=[], abort_event=threading.Event()))
    assert ev["progress"] == [{"kind": "delta", "text": "你"},
                              {"kind": "delta", "text": "好"}]
    assert ev["finished"][0].text == "你好"
    assert ev["failed"] == []


def test_abort_returns_none_not_failed(qapp):
    p = FakeProvider()
    abort = threading.Event()
    abort.set()
    ev = _run(build_chat_job(p, [], system="s", tools=[], abort_event=abort))
    assert ev["finished"] == [None] and ev["failed"] == []


def test_provider_error_goes_to_failed(qapp):
    p = FakeProvider(error=AiProviderError("連線失敗：測試"))
    ev = _run(build_chat_job(p, [], system="s", tools=[],
                             abort_event=threading.Event()))
    assert ev["finished"] == []
    assert "連線失敗：測試" in ev["failed"][0]


def test_job_passes_messages_system_tools(qapp):
    p = FakeProvider()
    msgs = [{"role": "user", "content": "做腳本"}]
    tools = [{"name": "t"}]
    _run(build_chat_job(p, msgs, system="SYS", tools=tools,
                        abort_event=threading.Event()))
    assert p.seen == {"messages": msgs, "system": "SYS", "tools": tools}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_worker.py -q`
Expected: FAIL（ModuleNotFoundError: ai_worker）

- [ ] **Step 3: 實作**

`src/keyboard_executor/app/ai_worker.py`：

```python
"""AI 聊天 job：把 ChatProvider.stream_chat 包成 Worker 的 job 契約。

delta → progress({"kind": "delta", "text": ...})；使用者中止（AiAborted）→
回傳 None（走 finished，不是 failed）；AiProviderError 原樣拋出，由 Worker
轉成 failed（繁中訊息）。"""
from __future__ import annotations

import threading
from collections.abc import Callable

from keyboard_executor.core.ai.provider import AiAborted, ChatProvider, ChatResult


def build_chat_job(provider: ChatProvider, messages: list[dict], *,
                   system: str, tools: list[dict],
                   abort_event: threading.Event) -> Callable:
    def job(progress) -> ChatResult | None:
        try:
            return provider.stream_chat(
                messages, system=system, tools=tools,
                on_delta=lambda text: progress({"kind": "delta", "text": text}),
                should_abort=abort_event.is_set)
        except AiAborted:
            return None
    return job
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_worker.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/ai_worker.py tests/app/test_ai_worker.py
git commit -m "feat(ai): build_chat_job（stream_chat 包成 Worker job 契約）"
```

---

### Task 8: `app/ai_panel.py` 骨架 — 聊天流（氣泡/串流/停止/清除/隱私 ack）＋ QSS

**Files:**
- Create: `src/keyboard_executor/app/ai_panel.py`
- Modify: `src/keyboard_executor/app/theme.py`（檔尾 QMenu 區塊後加 QSS）
- Test: `tests/app/test_ai_panel.py`（新檔；Task 9 續用）

**Interfaces:**
- Consumes: Task 3 `make_provider`、Task 4 `build_system_prompt`/`as_anthropic`/`as_openai`、Task 7 `build_chat_job`、既有 `Worker`、`Settings`、`ScriptStorage`（`load`/`save`/`list_names`）、`script_to_dict`。
- Produces（Task 9/10 依賴）:
  - `class AiPanel(QWidget)`，Signals：`open_settings_requested = Signal()`、`scripts_changed = Signal()`。
  - 建構子：`AiPanel(get_settings, ack_privacy, storage, get_selected_script, worker_factory=Worker, provider_factory=make_provider, confirm_privacy=None, parent=None)`
    - `get_settings: Callable[[], Settings]`；`ack_privacy: Callable[[], None]`（持久化 ai_privacy_ack=True）；`get_selected_script: Callable[[], str | None]`（回選中腳本名稱）；`confirm_privacy: Callable[[], bool] | None`（None → 內建 QMessageBox；測試注入 lambda）。
  - 方法：`refresh_state()`（依設定切「未設定引導」/「聊天」頁）、`send_message(text: str)`（可測 seam；`_on_send` 讀輸入框後呼它）、`stop_streaming()`、`clear_conversation()`。
  - 屬性（測試用）：`input_edit`、`send_button`、`stop_button`、`clear_button`、`setup_button`（未設定頁的「開啟設定」）、`bubbles_layout`（訊息容器 QVBoxLayout）、`_messages`（對話歷史 list[dict]）。
  - 氣泡：`QLabel`，objectName `aiBubbleUser` / `aiBubbleAssistant`，wordWrap。

- [ ] **Step 1: 寫失敗測試**

`tests/app/test_ai_panel.py`：

```python
"""AiPanel 聊天流：未設定引導、送出/串流/停止/清除、隱私 ack。"""
import threading

import pytest

from keyboard_executor.app.settings import Settings
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatProvider,
    ChatResult,
)
from keyboard_executor.storage.scripts import ScriptStorage


class SyncWorker(Worker):
    """start() 直接同步 run()（Worker.run 支援同步呼叫）。"""
    def start(self):
        self.run()


class FakeProvider(ChatProvider):
    def __init__(self, result=None, deltas=(), error=None):
        self.result = result or ChatResult(text="回答")
        self.deltas = deltas
        self.error = error
        self.calls = []

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.calls.append({"messages": list(messages), "system": system,
                           "tools": tools})
        for d in self.deltas:
            on_delta(d)
        if self.error:
            raise self.error
        return self.result


AI_ON = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=True)


def _panel(tmp_path, provider, settings=AI_ON, acks=None, confirm=True):
    from keyboard_executor.app.ai_panel import AiPanel

    acks = acks if acks is not None else []
    return AiPanel(get_settings=lambda: settings,
                   ack_privacy=lambda: acks.append(True),
                   storage=ScriptStorage(tmp_path),
                   get_selected_script=lambda: None,
                   worker_factory=SyncWorker,
                   provider_factory=lambda *a: provider,
                   confirm_privacy=lambda: confirm)


def _bubble_texts(panel):
    lay = panel.bubbles_layout
    out = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None and w.objectName().startswith("aiBubble"):
            out.append((w.objectName(), w.text()))
    return out


def test_unconfigured_shows_setup_page(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider(), settings=Settings())
    assert panel.setup_button.isVisible() or not panel.input_edit.isEnabled()


def test_send_adds_user_and_assistant_bubbles(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(text="你好！"), deltas=["你好", "！"])
    panel = _panel(tmp_path, provider)
    panel.send_message("怎麼錄製腳本？")
    texts = _bubble_texts(panel)
    assert ("aiBubbleUser", "怎麼錄製腳本？") in texts
    assert ("aiBubbleAssistant", "你好！") in texts
    # 對話歷史累積（下一輪帶上下文）
    assert panel._messages == [{"role": "user", "content": "怎麼錄製腳本？"},
                               {"role": "assistant", "content": "你好！"}]


def test_system_prompt_and_anthropic_tools_passed(qapp, tmp_path):
    provider = FakeProvider()
    panel = _panel(tmp_path, provider)
    panel.send_message("hi")
    call = provider.calls[0]
    assert "行為界線" in call["system"]
    assert call["tools"][0].get("input_schema") is not None   # anthropic 格式


def test_openai_settings_use_openai_tool_format(qapp, tmp_path):
    provider = FakeProvider()
    s = Settings(ai_provider="openai", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=True)
    panel = _panel(tmp_path, provider, settings=s)
    panel.send_message("hi")
    assert provider.calls[0]["tools"][0]["type"] == "function"


def test_privacy_ack_asked_once_then_persisted(qapp, tmp_path):
    acks = []
    s = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=False)
    panel = _panel(tmp_path, FakeProvider(), settings=s, acks=acks)
    panel.send_message("hi")
    assert acks == [True]           # 確認後呼叫 ack_privacy


def test_privacy_declined_blocks_send(qapp, tmp_path):
    provider = FakeProvider()
    s = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=False)
    panel = _panel(tmp_path, provider, settings=s, confirm=False)
    panel.send_message("hi")
    assert provider.calls == []     # 未送出


def test_provider_error_shows_error_bubble(qapp, tmp_path):
    provider = FakeProvider(error=AiProviderError("連線失敗：x"))
    panel = _panel(tmp_path, provider)
    panel.send_message("hi")
    assert any("連線失敗" in t for _, t in _bubble_texts(panel))


def test_clear_conversation_resets(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    panel.send_message("hi")
    panel.clear_conversation()
    assert panel._messages == [] and _bubble_texts(panel) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_panel.py -q`
Expected: FAIL（ModuleNotFoundError: ai_panel）

- [ ] **Step 3: 實作**

`src/keyboard_executor/app/ai_panel.py`：

```python
"""AI 助手聊天面板（QDockWidget 內容）。

依賴全部由建構子注入（get_settings/ack_privacy/storage/get_selected_script/
worker_factory/provider_factory/confirm_privacy），面板不碰 SettingsStore 與
MainWindow —— 可 offscreen 測試。串流走 Worker（背景 QThread），delta 經
progress signal 回 UI 執行緒即時追加。"""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.ai_worker import build_chat_job
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.manual import build_system_prompt
from keyboard_executor.core.ai.tools import as_anthropic, as_openai
from keyboard_executor.core.models import ScriptValidationError, script_to_dict


def _confirm_privacy_dialog(parent) -> bool:
    """首次送出的隱私告知（繁中自建按鈕，比照 confirm.py 慣例）。"""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("傳送資料給 AI 供應商")
    box.setText("你的訊息與目前選中腳本的內容，會傳送給你在設定頁選擇的\n"
                "AI 供應商（Anthropic 或 OpenAI）處理。是否繼續？")
    ok = box.addButton("繼續", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is ok


class AiPanel(QWidget):
    open_settings_requested = Signal()
    scripts_changed = Signal()

    def __init__(self, get_settings, ack_privacy, storage, get_selected_script,
                 worker_factory=Worker, provider_factory=make_provider,
                 confirm_privacy=None, parent=None):
        super().__init__(parent)
        self._get_settings = get_settings
        self._ack_privacy = ack_privacy
        self._storage = storage
        self._get_selected_script = get_selected_script
        self._worker_factory = worker_factory
        self._provider_factory = provider_factory
        self._confirm_privacy = confirm_privacy or (
            lambda: _confirm_privacy_dialog(self))
        self._messages: list[dict] = []
        self._worker = None
        self._abort = threading.Event()
        self._streaming_bubble: QLabel | None = None
        self._edit_target: str | None = None   # 送出當下選中的腳本（edit 提案用）
        self._build_ui()
        self.refresh_state()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self._stack = QStackedLayout(self)
        # 頁 0：未設定引導
        setup = QWidget()
        s_lay = QVBoxLayout(setup)
        hint = QLabel("尚未設定 AI 供應商。\n請到「設定」選擇供應商並填入 model 與 API 金鑰。")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setup_button = QPushButton("開啟設定")
        self.setup_button.setProperty("variant", "primary")
        self.setup_button.clicked.connect(self.open_settings_requested.emit)
        s_lay.addStretch(1)
        s_lay.addWidget(hint)
        s_lay.addWidget(self.setup_button, alignment=Qt.AlignmentFlag.AlignCenter)
        s_lay.addStretch(1)
        self._stack.addWidget(setup)
        # 頁 1：聊天
        chat = QWidget()
        c_lay = QVBoxLayout(chat)
        head = QHBoxLayout()
        head.addStretch(1)
        self.clear_button = QPushButton("清除對話")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.clicked.connect(self.clear_conversation)
        head.addWidget(self.clear_button)
        c_lay.addLayout(head)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        bubbles_host = QWidget()
        self.bubbles_layout = QVBoxLayout(bubbles_host)
        self.bubbles_layout.addStretch(1)
        self._scroll.setWidget(bubbles_host)
        c_lay.addWidget(self._scroll, stretch=1)
        row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("問使用方法，或請 AI 產生/修改腳本…")
        self.input_edit.returnPressed.connect(self._on_send)
        self.send_button = QPushButton("送出")
        self.send_button.setProperty("variant", "primary")
        self.send_button.clicked.connect(self._on_send)
        self.stop_button = QPushButton("停止")
        self.stop_button.setProperty("variant", "ghost")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_streaming)
        row.addWidget(self.input_edit, stretch=1)
        row.addWidget(self.send_button)
        row.addWidget(self.stop_button)
        c_lay.addLayout(row)
        self._stack.addWidget(chat)

    def refresh_state(self) -> None:
        s = self._get_settings()
        configured = bool(s.ai_provider and s.ai_model and s.ai_api_key)
        self._stack.setCurrentIndex(1 if configured else 0)

    def _add_bubble(self, object_name: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # 插在尾端 stretch 之前
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, label)
        return label

    # ---------- 聊天流 ----------

    def _on_send(self) -> None:
        text = self.input_edit.text().strip()
        if text:
            self.input_edit.clear()
            self.send_message(text)

    def send_message(self, text: str) -> None:
        if self._worker is not None:
            return   # 串流中不重入
        s = self._get_settings()
        provider = self._provider_factory(s.ai_provider, s.ai_api_key, s.ai_model)
        if provider is None:
            self.refresh_state()
            return
        if not s.ai_privacy_ack:
            if not self._confirm_privacy():
                return
            self._ack_privacy()
        self._add_bubble("aiBubbleUser", text)
        self._messages.append({"role": "user", "content": text})
        self._edit_target = self._get_selected_script()
        script_json = None
        if self._edit_target:
            try:
                script_json = json.dumps(
                    script_to_dict(self._storage.load(self._edit_target)),
                    ensure_ascii=False, indent=2)
            except ScriptValidationError:
                script_json = None
        system = build_system_prompt(script_json)
        tools = as_anthropic() if s.ai_provider == "anthropic" else as_openai()
        self._abort = threading.Event()
        self._streaming_bubble = self._add_bubble("aiBubbleAssistant", "")
        job = build_chat_job(provider, list(self._messages), system=system,
                             tools=tools, abort_event=self._abort)
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        worker = self._worker_factory(job)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.start()

    def _on_progress(self, payload: dict) -> None:
        if payload.get("kind") == "delta" and self._streaming_bubble is not None:
            self._streaming_bubble.setText(
                self._streaming_bubble.text() + payload["text"])
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_finished(self, result) -> None:
        self._teardown_worker()
        bubble = self._streaming_bubble
        self._streaming_bubble = None
        if result is None:   # 使用者中止
            if bubble is not None:
                bubble.setText(bubble.text() + "（已停止）")
            return
        if bubble is not None:
            bubble.setText(result.text)
            if not result.text and bubble.text() == "":
                bubble.setText("（已提出腳本提案）")
        # 空 assistant content 兩家 API 都可能拒收，補占位文字
        self._messages.append({"role": "assistant",
                               "content": result.text or "（已提出腳本提案）"})
        if result.tool_call is not None:
            self._handle_tool_call(result.tool_call)

    def _on_failed(self, message: str) -> None:
        self._teardown_worker()
        if self._streaming_bubble is not None and not self._streaming_bubble.text():
            self._streaming_bubble.setText(message)
        else:
            self._add_bubble("aiBubbleAssistant", message)
        self._streaming_bubble = None

    def _teardown_worker(self) -> None:
        self._worker = None
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def stop_streaming(self) -> None:
        self._abort.set()

    def clear_conversation(self) -> None:
        self._messages = []
        self._streaming_bubble = None
        while self.bubbles_layout.count() > 1:   # 留住尾端 stretch
            item = self.bubbles_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ---------- 提案卡片（Task 9 實作）----------

    def _handle_tool_call(self, tool_call) -> None:
        pass
```

`src/keyboard_executor/app/theme.py` — 檔尾 `QMenu` 區塊後加：

```python
QLabel#aiBubbleUser {
    background: #17324e; color: #e6edf3; border-radius: 10px; padding: 8px 10px;
}
QLabel#aiBubbleAssistant {
    background: #1b232d; color: #e6edf3; border-radius: 10px; padding: 8px 10px;
}
QFrame#aiProposalCard {
    background: #161c24; border: 1px solid #37434f; border-radius: 10px;
}
QLabel#aiCardTitle { color: #4c9aff; font-weight: 600; }
QLabel#aiCardError { color: #ff6b6b; }
QDockWidget::title { background: #1b232d; padding: 6px; }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_panel.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/ai_panel.py src/keyboard_executor/app/theme.py tests/app/test_ai_panel.py
git commit -m "feat(ai): AiPanel 聊天面板骨架（串流氣泡/停止/清除/隱私告知）"
```

---

### Task 9: `ai_panel.py` 提案卡片 — 驗證/預覽/套用/復原/修正

**Files:**
- Modify: `src/keyboard_executor/app/ai_panel.py`（`_handle_tool_call` 與卡片）
- Test: `tests/app/test_ai_panel.py`（追加）

**Interfaces:**
- Consumes: Task 4 `TOOL_NEW`/`TOOL_EDIT`、Task 5 `script_from_proposal`/`actions_for_edit`、既有 `action_label`、`unique` 命名（本 task 內建 `_numbered_name`）。
- Produces: 卡片 `QFrame` objectName `aiProposalCard`；panel 方法 `apply_proposal(card)` 經卡片按鈕觸發；`scripts_changed` Signal 在套用/復原後發出。測試可從 `bubbles_layout` 找到卡片（`findChild`）。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/app/test_ai_panel.py`）**

```python
from keyboard_executor.core.ai.provider import ToolCall
from keyboard_executor.core.models import script_from_dict


def _script_dict(name="既有"):
    return {"name": name, "target_window": {"title_pattern": "app"},
            "actions": [{"type": "key_press", "key": "a"}]}


def _cards(panel):
    from PySide6.QtWidgets import QFrame

    lay = panel.bubbles_layout
    return [lay.itemAt(i).widget() for i in range(lay.count())
            if lay.itemAt(i).widget() is not None
            and lay.itemAt(i).widget().objectName() == "aiProposalCard"]


def test_new_script_proposal_shows_card_and_applies(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "AI腳本", "target_title_regex": "遊戲",
            "actions": [{"type": "key_press", "key": "a"},
                        {"type": "delay", "ms": 100}]})))
    panel = _panel(tmp_path, provider)
    fired = []
    panel.scripts_changed.connect(lambda: fired.append(1))
    panel.send_message("做一個腳本")
    (card,) = _cards(panel)
    assert "AI腳本" in card.title_label.text()
    assert "按鍵 a" in card.body_label.text()      # 用 action_label 摘要
    card.apply_button.click()
    storage = ScriptStorage(tmp_path)
    assert "AI腳本" in storage.list_names() and fired == [1]


def test_new_script_name_conflict_gets_numbered(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("AI腳本")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "AI腳本", "target_title_regex": "t",
            "actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("再做一個")
    _cards(panel)[0].apply_button.click()
    assert "AI腳本 2" in storage.list_names()


def test_edit_proposal_applies_and_undoes(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("目標")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current", args={
            "actions": [{"type": "delay", "ms": 999}]})))
    from keyboard_executor.app.ai_panel import AiPanel

    panel = AiPanel(get_settings=lambda: AI_ON, ack_privacy=lambda: None,
                    storage=storage, get_selected_script=lambda: "目標",
                    worker_factory=SyncWorker,
                    provider_factory=lambda *a: provider,
                    confirm_privacy=lambda: True)
    panel.send_message("把動作改成等待 999ms")
    (card,) = _cards(panel)
    card.apply_button.click()
    assert str(storage.load("目標").actions[0].type) == "delay"
    card.undo_button.click()                       # 套用後卡片出現復原
    assert str(storage.load("目標").actions[0].type) == "key_press"


def test_edit_proposal_without_selection_shows_error(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current",
                                    args={"actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)   # get_selected_script → None
    panel.send_message("改腳本")
    (card,) = _cards(panel)
    assert "沒有選中" in card.body_label.text()


def test_invalid_proposal_shows_error_card_with_retry(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "x", "target_title_regex": "t",
            "actions": [{"type": "hack"}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("做腳本")
    (card,) = _cards(panel)
    assert "無效" in card.body_label.text()
    assert card.retry_button is not None
    # 按「請 AI 修正」→ 以錯誤訊息當一則 user 訊息重送
    provider.result = ChatResult(text="修好了")
    card.retry_button.click()
    assert provider.calls[-1]["messages"][-1]["role"] == "user"
    assert "無效" in provider.calls[-1]["messages"][-1]["content"]


def test_discard_removes_card(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "n", "target_title_regex": "t",
            "actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("做腳本")
    (card,) = _cards(panel)
    card.discard_button.click()
    assert card.apply_button is None or not card.apply_button.isEnabled()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_panel.py -q`
Expected: 新增 6 個測試 FAIL（卡片未實作），既有 8 個續過。

- [ ] **Step 3: 實作**

`ai_panel.py` 追加 import：

```python
from PySide6.QtWidgets import QFrame
from keyboard_executor.core.ai.script_gen import actions_for_edit, script_from_proposal
from keyboard_executor.core.ai.tools import TOOL_EDIT, TOOL_NEW
from keyboard_executor.core.models import Script, action_label
import dataclasses
```

卡片類（放 `AiPanel` 前）：

```python
class _ProposalCard(QFrame):
    """提案/錯誤卡片。按鈕由 AiPanel 接線；不存在的按鈕為 None。"""

    def __init__(self, title: str, body: str, *, apply_=False, discard=False,
                 retry=False, parent=None):
        super().__init__(parent)
        self.setObjectName("aiProposalCard")
        lay = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("aiCardTitle")
        self.body_label = QLabel(body)
        self.body_label.setObjectName("aiCardError" if retry else "aiCardBody")
        self.body_label.setWordWrap(True)
        lay.addWidget(self.title_label)
        lay.addWidget(self.body_label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.apply_button = self.discard_button = None
        self.retry_button = self.undo_button = None
        if apply_:
            self.apply_button = QPushButton("套用")
            self.apply_button.setProperty("variant", "primary")
            row.addWidget(self.apply_button)
        if discard:
            self.discard_button = QPushButton("捨棄")
            self.discard_button.setProperty("variant", "ghost")
            row.addWidget(self.discard_button)
        if retry:
            self.retry_button = QPushButton("請 AI 修正")
            row.addWidget(self.retry_button)
        lay.addLayout(row)
        self._button_row = row

    def mark_applied(self, undoable: bool) -> None:
        self.title_label.setText(self.title_label.text() + "　已套用 ✓")
        for b in (self.apply_button, self.discard_button):
            if b is not None:
                b.setEnabled(False)
        if undoable:
            self.undo_button = QPushButton("復原")
            self.undo_button.setProperty("variant", "ghost")
            self._button_row.addWidget(self.undo_button)
```

`_numbered_name`（模組層）：

```python
def _numbered_name(base: str, existing) -> str:
    """名稱衝突自動加序號：base、base 2、base 3…（spec §9）。"""
    existing = set(existing)
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"
```

`AiPanel._handle_tool_call` 與卡片流程（取代 Task 8 的 pass）：

```python
    def _add_card(self, card: "_ProposalCard") -> "_ProposalCard":
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, card)
        return card

    def _handle_tool_call(self, tool_call) -> None:
        if tool_call.name == TOOL_NEW:
            self._card_for_new(tool_call.args)
        elif tool_call.name == TOOL_EDIT:
            self._card_for_edit(tool_call.args)
        else:
            self._add_card(_ProposalCard("未知的提案", f"不認識的工具：{tool_call.name}",
                                         retry=True))._wire_retry(self)

    def _card_for_new(self, args: dict) -> None:
        try:
            script = script_from_proposal(args.get("name", ""),
                                          args.get("target_title_regex", ""),
                                          args.get("actions") or [])
        except ScriptValidationError as e:
            self._error_card(f"AI 產出無效：{e}")
            return
        body = "\n".join(f"{i + 1}. {action_label(a)}"
                         for i, a in enumerate(script.actions))
        card = self._add_card(_ProposalCard(f"新腳本提案：{script.name}", body,
                                            apply_=True, discard=True))
        card.apply_button.clicked.connect(
            lambda: self._apply_new(card, script))
        card.discard_button.clicked.connect(
            lambda: self._discard_card(card))

    def _card_for_edit(self, args: dict) -> None:
        target = self._edit_target
        if not target:
            self._error_card("AI 想修改腳本，但目前沒有選中的腳本。"
                             "請先在清單選取腳本後再試。")
            return
        try:
            current = self._storage.load(target)
            edited = actions_for_edit(current, args.get("actions") or [])
        except ScriptValidationError as e:
            self._error_card(f"AI 產出無效：{e}")
            return
        body = "\n".join(f"{i + 1}. {action_label(a)}"
                         for i, a in enumerate(edited.actions))
        card = self._add_card(_ProposalCard(f"修改腳本提案：{target}", body,
                                            apply_=True, discard=True))
        card.apply_button.clicked.connect(
            lambda: self._apply_edit(card, previous=current, edited=edited))
        card.discard_button.clicked.connect(
            lambda: self._discard_card(card))

    def _error_card(self, message: str) -> None:
        card = self._add_card(_ProposalCard("提案有問題", message, retry=True))
        card.retry_button.clicked.connect(
            lambda: self.send_message(message))

    def _apply_new(self, card, script: Script) -> None:
        final_name = _numbered_name(script.name, self._storage.list_names())
        if final_name != script.name:
            script = dataclasses.replace(script, name=final_name)
        try:
            self._storage.save(script)
        except ScriptValidationError as e:
            card.body_label.setText(f"套用失敗：{e}")
            return
        card.title_label.setText(f"新腳本提案：{final_name}")
        card.mark_applied(undoable=False)
        self.scripts_changed.emit()

    def _apply_edit(self, card, *, previous: Script, edited: Script) -> None:
        try:
            self._storage.save(edited)
        except ScriptValidationError as e:
            card.body_label.setText(f"套用失敗：{e}")
            return
        card.mark_applied(undoable=True)
        card.undo_button.clicked.connect(
            lambda: self._undo_edit(card, previous))
        self.scripts_changed.emit()

    def _undo_edit(self, card, previous: Script) -> None:
        try:
            self._storage.save(previous)
        except ScriptValidationError as e:
            card.body_label.setText(f"復原失敗：{e}")
            return
        card.undo_button.setEnabled(False)
        card.title_label.setText(card.title_label.text() + "（已復原）")
        self.scripts_changed.emit()

    def _discard_card(self, card) -> None:
        for b in (card.apply_button, card.discard_button):
            if b is not None:
                b.setEnabled(False)
        card.title_label.setText(card.title_label.text() + "　已捨棄")
```

（`_ProposalCard._wire_retry` 若未使用可省略——未知工具直接走 `_error_card` 即可，實作時擇一，測試只覆蓋 TOOL_NEW/TOOL_EDIT/無效三路。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_ai_panel.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/ai_panel.py tests/app/test_ai_panel.py
git commit -m "feat(ai): 提案卡片（預覽/套用/捨棄/復原/請 AI 修正）"
```

---

### Task 10: main_window 接線 ＋ README

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`
- Modify: `README.md`（功能清單加一條）
- Test: `tests/app/test_main_window.py`（追加）

**Interfaces:**
- Consumes: Task 8/9 `AiPanel`（Signals `open_settings_requested`/`scripts_changed`、方法 `refresh_state()`）、既有 `SettingsStore`、`ScriptListController.selected()`、`refresh_scripts()`、`_on_open_settings()`、`_apply_settings()`。
- Produces: `MainWindow.ai_button`（標題列）、`MainWindow._ai_dock`（QDockWidget，預設隱藏）、`MainWindow._ai_panel`。

- [ ] **Step 1: 寫失敗測試（追加到 `tests/app/test_main_window.py`，沿用該檔既有 fixture/建構慣例——實作者先讀該檔開頭的 window 建構 helper，用同一種方式建 MainWindow）**

```python
def test_ai_dock_hidden_by_default_and_toggles(main_window):
    w = main_window
    assert w._ai_dock.isHidden()
    w.ai_button.click()
    assert not w._ai_dock.isHidden()
    w.ai_button.click()
    assert w._ai_dock.isHidden()


def test_ai_panel_scripts_changed_refreshes_list(main_window, tmp_path):
    w = main_window
    from keyboard_executor.core.models import script_from_dict

    w._script_storage.save(script_from_dict(
        {"name": "AI新增", "target_window": {"title_pattern": "t"},
         "actions": [{"type": "delay", "ms": 1}]}))
    w._ai_panel.scripts_changed.emit()
    names = [w.script_list.item(i).data(0x0100)   # Qt.UserRole
             for i in range(w.script_list.count())]
    assert "AI新增" in names


def test_ai_privacy_ack_persists_via_callback(main_window):
    w = main_window
    w._ack_ai_privacy()
    assert w._settings.ai_privacy_ack is True
```

（`main_window` fixture：若該檔還沒有，實作者沿用檔內既有測試建 MainWindow 的方式——多數測試直接以 tmp dir 與 fake 依賴建構。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -q -k ai`
Expected: FAIL（無 _ai_dock / ai_button）

- [ ] **Step 3: 實作**

`main_window.py`：

1. import 區加：

```python
from keyboard_executor.app.ai_panel import AiPanel
```

（`QDockWidget` 加入既有 QtWidgets import 清單；`dataclasses.replace` 若未 import 則 `import dataclasses`。）

2. `_build_titlebar` 中 `template_manage_button` 之前加：

```python
        self.ai_button = QPushButton("AI 助手")
        self.ai_button.setProperty("variant", "ghost")
        lay.addWidget(self.ai_button)
```

3. 建 UI 完（`setCentralWidget(central)` 之後）加 dock：

```python
        self._ai_panel = AiPanel(
            get_settings=lambda: self._settings,
            ack_privacy=self._ack_ai_privacy,
            storage=self._script_storage,
            get_selected_script=self._scripts.selected,
            worker_factory=self._worker_factory)
        self._ai_dock = QDockWidget("AI 助手", self)
        self._ai_dock.setObjectName("aiDock")
        self._ai_dock.setWidget(self._ai_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._ai_dock)
        self._ai_dock.hide()
```

4. signal 接線區（`settings_button.clicked.connect` 附近）加：

```python
        self.ai_button.clicked.connect(
            lambda: self._ai_dock.setVisible(self._ai_dock.isHidden()))
        self._ai_panel.open_settings_requested.connect(self._on_open_settings)
        self._ai_panel.scripts_changed.connect(self.refresh_scripts)
```

5. 方法（放 `_apply_settings` 附近）：

```python
    def _ack_ai_privacy(self) -> None:
        """AI 隱私告知確認：持久化並同步記憶體設定。"""
        self._settings = dataclasses.replace(self._settings, ai_privacy_ack=True)
        try:
            SettingsStore(self._data_dir).save(self._settings)
        except ScriptValidationError as e:
            logger.warning("儲存 AI 隱私確認失敗：%s", e)
```

6. `_apply_settings` 尾端加一行（設定變更後面板即時切換引導/聊天頁）：

```python
        self._ai_panel.refresh_state()
```

7. `ai_button` tooltip（`settings_button.setToolTip` 附近）：

```python
        self.ai_button.setToolTip("AI 助手：問使用方法、產生或修改腳本（需在設定填 API 金鑰）")
```

`README.md` 功能清單（「緊急停止」條目後）加：

```markdown
- **AI 助手**（可選）：自帶 Anthropic / OpenAI API 金鑰，在側欄聊天問使用方法、讓 AI 產生/修改腳本（先預覽、按套用才儲存、可復原）
```

- [ ] **Step 4: 跑全套測試**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 基線 739 ＋ 新增（約 47）全 passed、4 skipped，0 failed。

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/main_window.py README.md tests/app/test_main_window.py
git commit -m "feat(ai): 主視窗掛 AI 助手 dock 與標題列切換鈕"
```

---

## Self-Review 紀錄

- **Spec 覆蓋**：§4 provider（T1–T3）、§5 手冊/工具（T4）、§6 script_gen（T5）、§7 設定（T6）、§8 worker（T7）、§9 面板＋套用/復原（T8–T9）、主視窗掛載（T10）、§11 錯誤處理（T1 錯誤轉譯＋T8 failed 氣泡＋T9 錯誤卡片）、隱私 ack（T6 欄位＋T8 流程＋T10 持久化）。
- **佔位掃描**：無 TBD/TODO；每步含完整程式碼。
- **型別一致**：`stream_chat` 簽名（T1 定義、T2/T3 實作、T7 呼叫、T8 FakeProvider）一致；`make_provider(provider, api_key, model)`（T3 定義、T8 `provider_factory(s.ai_provider, s.ai_api_key, s.ai_model)`）一致；`TOOL_NEW`/`TOOL_EDIT` 字串與 T2/T3 測試中 tool 名稱一致；`actions_for_edit(current, actions)`（T5 定義、T9 呼叫）一致。
