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


def test_payload_converts_image_attachment_to_base64_block():
    p, opener = _provider([_event({"type": "message_stop"})])
    p.stream_chat([{"role": "user", "content": "看圖", "images": [{
        "name": "x.png", "media_type": "image/png", "data": "YWJj",
        "path": "/tmp/x.png"}]}], system="SYS", tools=[],
        on_delta=lambda _t: None, should_abort=lambda: False)
    content = json.loads(opener.requests[0].data)["messages"][0]["content"]
    assert content[0]["source"] == {
        "type": "base64", "media_type": "image/png", "data": "YWJj"}
    assert content[-1] == {"type": "text", "text": "看圖"}


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
