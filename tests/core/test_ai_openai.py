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
    p, opener = _provider([_chunk({"content": "ok"}), "data: [DONE]"])
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


def test_payload_converts_image_attachment_to_data_url():
    p, opener = _provider([_chunk({"content": "ok"}), "data: [DONE]"])
    p.stream_chat([{"role": "user", "content": "看圖", "images": [{
        "name": "x.png", "media_type": "image/png", "data": "YWJj",
        "path": "/tmp/x.png"}]}], system="SYS", tools=[],
        on_delta=lambda _t: None, should_abort=lambda: False)
    content = json.loads(opener.requests[0].data)["messages"][1]["content"]
    assert content[0]["image_url"]["url"] == "data:image/png;base64,YWJj"
    assert content[-1] == {"type": "text", "text": "看圖"}


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
