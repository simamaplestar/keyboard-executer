import io
import json

import pytest

from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.openai_provider import OpenAiProvider
from keyboard_executor.core.ai.openrouter_provider import OpenRouterProvider
from keyboard_executor.core.ai.provider import AiAborted, AiProviderError


def test_openrouter_sends_custom_model_images_tools_and_streams(monkeypatch):
    captured = []
    chunks = [
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
            "name": "propose_edit_current", "arguments": '{"actions":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
            "arguments": ' []}'}}]}}]},
    ]
    response = io.BytesIO((": OPENROUTER PROCESSING\n\n" + "".join(
        "data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        + "data: [DONE]\n\n").encode())

    def opener(request, timeout):
        captured.append(request)
        return response

    monkeypatch.setattr("urllib.request.urlopen", opener)
    provider = make_provider("openrouter", "router-key", "vendor/custom-model:free")
    assert provider is not None
    deltas = []
    result = provider.stream_chat(
        [{"role": "user", "content": "看圖", "images": [{
            "media_type": "image/png", "data": "YWJj", "path": "/private/x.png"}]}],
        system="SYS", tools=[{"type": "function", "function": {"name": "t"}}],
        on_delta=deltas.append, should_abort=lambda: False)
    request = captured[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer router-key"
    assert payload["model"] == "vendor/custom-model:free" and payload["stream"] is True
    assert payload["messages"][0] == {"role": "system", "content": "SYS"}
    assert payload["messages"][1]["content"][0] == {
        "type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    assert payload["tools"][0]["function"]["name"] == "t"
    assert deltas == ["你好"] and result.text == "你好"
    assert result.tool_call.name == "propose_edit_current"
    assert result.tool_call.args == {"actions": []}
    assert response.closed


def test_openrouter_reports_midstream_errors_and_closes_response(monkeypatch):
    response = io.BytesIO(b'data: {"error":{"code":503,"message":"Unavailable"},"choices":[]}\n')
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kw: response)
    provider = make_provider("openrouter", "key", "custom/model")
    assert provider is not None
    with pytest.raises(AiProviderError, match="Unavailable"):
        provider.stream_chat([], system="s", tools=[], on_delta=lambda _: None,
                             should_abort=lambda: False)
    assert response.closed


def test_openrouter_cancellation_closes_response(monkeypatch):
    response = io.BytesIO(b'data: [DONE]\n')
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kw: response)
    provider = make_provider("openrouter", "key", "custom/model")
    assert provider is not None
    with pytest.raises(AiAborted):
        provider.stream_chat([], system="s", tools=[], on_delta=lambda _: None,
                             should_abort=lambda: True)
    assert response.closed


def test_openrouter_has_no_subscription_provider():
    assert make_provider("openrouter", "", "custom/model", auth_mode="subscription") is None


@pytest.fixture(params=[OpenAiProvider, OpenRouterProvider], ids=["openai", "openrouter"])
def stream_provider(request):
    def make(lines):
        response = io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))
        provider = request.param("fake-credential-never-log", "test-model",
                                 opener=lambda *_args, **_kwargs: response)
        return provider, response

    return make


def _event(delta, finish_reason=None):
    return "data: " + json.dumps({"choices": [{"index": 0, "delta": delta,
                                                "finish_reason": finish_reason}]})


def _read(provider, *, on_delta=lambda _: None, should_abort=lambda: False):
    return provider.stream_chat([], system="test", tools=[], on_delta=on_delta,
                                should_abort=should_abort)


@pytest.mark.parametrize("data", ["", "private-upstream-body", "[]"])
def test_invalid_sse_is_a_provider_error_without_raw_content(stream_provider, data, caplog):
    provider, response = stream_provider(["data: " + data, "data: [DONE]"])
    with pytest.raises(AiProviderError, match="串流") as raised:
        _read(provider)
    assert response.closed
    assert "private-upstream-body" not in str(raised.value) + caplog.text
    assert "fake-credential-never-log" not in str(raised.value) + caplog.text


@pytest.mark.parametrize("finish_reason", [None, "stop", "length", "content_filter"])
def test_empty_response_reports_its_terminal_reason(stream_provider, finish_reason):
    provider, response = stream_provider([
        _event({"content": " \n", "reasoning": "private-reasoning"}),
        _event({}, finish_reason), "data: [DONE]",
    ])
    with pytest.raises(AiProviderError) as raised:
        _read(provider)
    assert response.closed
    assert (finish_reason or "未提供") in str(raised.value)
    assert "private-reasoning" not in str(raised.value)


def test_refusal_only_is_reported_without_echoing_refusal(stream_provider):
    provider, response = stream_provider([
        _event({"content": None, "refusal": "private-refusal"}),
        _event({}, "stop"), "data: [DONE]",
    ])
    with pytest.raises(AiProviderError, match="拒絕") as raised:
        _read(provider)
    assert response.closed
    assert "stop" in str(raised.value)
    assert "private-refusal" not in str(raised.value)


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
@pytest.mark.parametrize("kind", ["text", "tool"])
def test_incomplete_terminal_status_never_returns_partial_answer_or_tool(
        stream_provider, finish_reason, kind):
    # Even syntactically complete JSON can be only part of the intended answer.
    delta = ({"content": '{"replies":[]}'} if kind == "text" else {
        "tool_calls": [{"index": 0, "function": {
            "name": "propose_edit_current", "arguments": '{"actions": []}'}}]})
    provider, response = stream_provider([
        _event(delta), _event({}, finish_reason), "data: [DONE]",
    ])
    with pytest.raises(AiProviderError, match=finish_reason):
        _read(provider)
    assert response.closed


def test_tool_only_response_remains_valid_with_repeated_usage_finish_reason(stream_provider):
    provider, response = stream_provider([
        _event({"tool_calls": [{"index": 0, "function": {
            "name": "propose_edit_current", "arguments": '{"actions": []}'}}]}),
        _event({}, "tool_calls"),
        "data: " + json.dumps({"choices": [{"delta": {"content": ""},
                                             "finish_reason": "tool_calls"}],
                                "usage": {"completion_tokens": 10}}),
        "data: [DONE]",
    ])
    result = _read(provider)
    assert result.text == ""
    assert result.tool_call.name == "propose_edit_current"
    assert result.tool_call.args == {"actions": []}
    assert response.closed


def test_reasoning_then_valid_text_preserves_live_deltas(stream_provider):
    provider, response = stream_provider([
        ": OPENROUTER PROCESSING", _event({"reasoning": "private-reasoning"}),
        _event({"content": "有"}), _event({"content": "喔"}),
        _event({}, "stop"), "data: [DONE]",
    ])
    deltas = []
    result = _read(provider, on_delta=deltas.append)
    assert result.text == "有喔" and deltas == ["有", "喔"]
    assert response.closed


def test_cancellation_still_wins_before_terminal_status(stream_provider):
    provider, response = stream_provider([
        _event({"content": "partial"}), _event({}, "length"), "data: [DONE]",
    ])
    deltas = []
    with pytest.raises(AiAborted):
        _read(provider, on_delta=deltas.append, should_abort=lambda: bool(deltas))
    assert deltas == ["partial"]
    assert response.closed
