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


class _FlakyResp:
    """模擬連線在收到第一行後被對端中斷（readline 拋 OSError）。"""

    def __init__(self):
        self.calls = 0

    def readline(self):
        self.calls += 1
        if self.calls == 1:
            return b"data: partial\n"
        raise OSError("Connection reset by peer")


def test_iter_sse_data_readline_oserror_becomes_zh_disconnect_error():
    it = iter_sse_data(_FlakyResp(), should_abort=lambda: False)
    assert next(it) == "partial"
    with pytest.raises(AiProviderError, match="連線中斷"):
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
