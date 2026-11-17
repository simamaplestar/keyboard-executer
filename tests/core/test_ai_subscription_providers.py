import json
import subprocess

import pytest

from keyboard_executor.core.ai.auth.models import AuthProfile
from keyboard_executor.core.ai.claude_subscription_provider import (
    ClaudeSubscriptionProvider,
)
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.openai_subscription_provider import (
    OpenAiSubscriptionProvider,
)
from keyboard_executor.core.ai.provider import AiAborted, AiProviderError
from keyboard_executor.core.ai.subscription_protocol import (
    SubscriptionStreamDecoder,
    TOOL_MARKER_CLOSE,
    TOOL_MARKER_OPEN,
)


def _plain_output(text="回答", call=None):
    if call is None:
        return text
    return (text + TOOL_MARKER_OPEN
            + json.dumps(call, ensure_ascii=False) + TOOL_MARKER_CLOSE)


def _claude_result(text="回答", call=None):
    return json.dumps({"type": "result", "subtype": "success",
                       "result": _plain_output(text, call)}, ensure_ascii=False)


def test_subscription_stream_decoder_hides_split_tool_marker():
    deltas = []
    decoder = SubscriptionStreamDecoder(deltas.append)
    call = {"name": "propose_edit_current", "args": {"actions": []}}
    full_output = _plain_output("逐段回答", call)
    for chunk in ("逐", "段回答\n<keyboard_", "executor_tool>",
                  json.dumps(call), TOOL_MARKER_CLOSE):
        decoder.feed(chunk)
    result = decoder.finish(full_output)
    assert "".join(deltas) == "逐段回答"
    assert result.text == "逐段回答"
    assert result.tool_call.name == "propose_edit_current"


def test_subscription_stream_decoder_uses_final_output_without_duplication():
    deltas = []
    decoder = SubscriptionStreamDecoder(deltas.append)
    decoder.feed("即時")
    result = decoder.finish("即時補完")
    assert deltas == ["即時", "補完"] and result.text == "即時補完"


class FakeRpc:
    def __init__(self, on_notification):
        self.on_notification = on_notification
        self.calls = []
        self.closed = False

    def request(self, method, params=None, timeout=30.0):
        self.calls.append((method, params))
        if method == "initialize":
            return {}
        if method == "account/read":
            return {"account": {"type": "chatgpt", "email": "x@y",
                                "planType": "plus"},
                    "requiresOpenaiAuth": True}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            self.on_notification("item/agentMessage/delta", {
                "threadId": "thread-1", "turnId": "turn-1",
                "itemId": "item-1", "delta": "Codex 回答"})
            self.on_notification("turn/completed", {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"}})
            return {"turn": {"id": "turn-1"}}
        return {}

    def notify(self, method, params=None):
        self.calls.append((method, params))

    def close(self):
        self.closed = True


def test_openai_subscription_uses_codex_events():
    holder = {}

    def factory(*, on_notification):
        holder["rpc"] = FakeRpc(on_notification)
        return holder["rpc"]

    deltas = []
    provider = OpenAiSubscriptionProvider("gpt-test", rpc_factory=factory)
    result = provider.stream_chat(
        [{"role": "user", "content": "hi"}], system="sys", tools=[],
        on_delta=deltas.append, should_abort=lambda: False)
    assert result.text == "Codex 回答" and deltas == ["Codex 回答"]
    assert holder["rpc"].closed
    thread_call = next(p for m, p in holder["rpc"].calls if m == "thread/start")
    assert thread_call["sandbox"] == "read-only" and thread_call["ephemeral"] is True
    assert not any(m == 'model/list' for m, _ in holder['rpc'].calls)
    assert 'effort' not in next(p for m, p in holder['rpc'].calls if m == 'turn/start')


@pytest.mark.parametrize('model,available,want', [
    ('gpt-test', ['low', 'medium'], 'low'),
    ('gpt-test', ['medium', 'high'], None),
    ('custom-unknown', ['low', 'medium'], None),
    ('', ['low', 'medium'], None),
])
def test_chat_effort_uses_only_options_supported_by_the_selected_model(model, available, want):
    instances = []

    class ModelRpc(FakeRpc):
        def request(self, method, params=None, timeout=30):
            if method == 'model/list':
                self.calls.append((method, params))
                return {'data': [{'model': 'gpt-test', 'isDefault': True,
                                  'supportedReasoningEfforts': [
                                      {'reasoningEffort': value} for value in available]}],
                        'nextCursor': None}
            return super().request(method, params, timeout)

    def factory(**kwargs):
        rpc = ModelRpc(kwargs['on_notification'])
        instances.append(rpc)
        return rpc

    provider = OpenAiSubscriptionProvider(model, rpc_factory=factory, reasoning_effort='low')
    for _ in range(2):
        result = provider.stream_chat([], system='s', tools=[], on_delta=lambda _: None,
                                      should_abort=lambda: False)
        assert result.text == 'Codex 回答'
    turns = [p for rpc in instances for m, p in rpc.calls if m == 'turn/start']
    assert all(turn.get('effort') == want for turn in turns)
    assert sum(m == 'model/list' for rpc in instances for m, _ in rpc.calls) == (1 if model else 0)


@pytest.mark.parametrize('catalog', ['timeout', None, [None, {'model': 'gpt-test'}]])
def test_unavailable_effort_catalog_preserves_normal_replies(catalog):
    from keyboard_executor.core.ai.auth.models import AuthError
    class CatalogRpc(FakeRpc):
        def request(self, method, params=None, timeout=30):
            if method == 'model/list':
                if catalog == 'timeout':
                    raise AuthError('catalog timeout')
                return {'data': catalog}
            return super().request(method, params, timeout)
    provider = OpenAiSubscriptionProvider('gpt-test', reasoning_effort='low',
                                         rpc_factory=lambda **kw: CatalogRpc(kw['on_notification']))
    assert provider.stream_chat([], system='s', tools=[], on_delta=lambda _: None,
                                should_abort=lambda: False).text == 'Codex 回答'


def test_openai_subscription_attaches_local_images(tmp_path):
    holder = {}
    image = tmp_path / "畫面.png"
    image.write_bytes(b"png")

    def factory(*, on_notification):
        holder["rpc"] = FakeRpc(on_notification)
        return holder["rpc"]

    OpenAiSubscriptionProvider("", rpc_factory=factory).stream_chat(
        [{"role": "user", "content": "看圖", "images": [{
            "name": image.name, "media_type": "image/png", "data": "cG5n",
            "path": str(image)}]}], system="s", tools=[],
        on_delta=lambda _x: None, should_abort=lambda: False)
    turn = next(p for m, p in holder["rpc"].calls if m == "turn/start")
    local = next(item for item in turn["input"] if item["type"] == "localImage")
    assert local["path"] == str(image.resolve())


def test_openai_subscription_streams_plain_text_deltas_before_finish():
    class ChunkedRpc(FakeRpc):
        def request(self, method, params=None, timeout=30.0):
            if method == "turn/start":
                self.calls.append((method, params))
                for chunk in ("逐", "段顯示"):
                    self.on_notification("item/agentMessage/delta", {
                        "threadId": "thread-1", "turnId": "turn-1",
                        "itemId": "item-1", "delta": chunk})
                self.on_notification("turn/completed", {
                    "threadId": "thread-1",
                    "turn": {"id": "turn-1", "status": "completed"}})
                return {"turn": {"id": "turn-1"}}
            return super().request(method, params, timeout)

    deltas = []
    result = OpenAiSubscriptionProvider(
        "", rpc_factory=lambda **kw: ChunkedRpc(kw["on_notification"])
    ).stream_chat([], system="s", tools=[], on_delta=deltas.append,
                  should_abort=lambda: False)
    assert deltas == ["逐", "段顯示"]
    assert result.text == "逐段顯示"


def test_openai_subscription_uses_linux_temp_for_wsl_app_server():
    holder = {}

    def factory(*, on_notification):
        rpc = FakeRpc(on_notification)
        rpc.runs_in_wsl = True
        holder["rpc"] = rpc
        return rpc

    OpenAiSubscriptionProvider("", rpc_factory=factory).stream_chat(
        [], system="s", tools=[], on_delta=lambda _x: None,
        should_abort=lambda: False)
    thread_call = next(p for m, p in holder["rpc"].calls if m == "thread/start")
    assert thread_call["cwd"] == "/tmp"


def test_openai_subscription_requires_chatgpt_login():
    class LoggedOut(FakeRpc):
        def request(self, method, params=None, timeout=30.0):
            if method == "account/read":
                return {"account": None, "requiresOpenaiAuth": True}
            return super().request(method, params, timeout)

    with pytest.raises(AiProviderError, match="尚未登入"):
        OpenAiSubscriptionProvider(
            "m", rpc_factory=lambda **kw: LoggedOut(kw["on_notification"])
        ).stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                      should_abort=lambda: False)


def test_openai_subscription_interrupts_active_turn():
    holder = {}

    def factory(*, on_notification):
        holder["rpc"] = FakeRpc(on_notification)
        return holder["rpc"]

    with pytest.raises(AiAborted):
        OpenAiSubscriptionProvider(
            "m", rpc_factory=factory
        ).stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                      should_abort=lambda: any(method == 'turn/start'
                                               for method, _ in holder['rpc'].calls))
    assert any(method == "turn/interrupt" for method, _ in holder["rpc"].calls)


def test_claude_subscription_uses_official_cli_and_setup_token():
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command, 0, stdout=_claude_result("Claude 回答"), stderr="")

    deltas = []
    provider = ClaudeSubscriptionProvider(
        "sonnet", oauth_token="oauth-secret", run=run,
        command_factory=lambda: ["claude"])
    result = provider.stream_chat(
        [{"role": "user", "content": "hi"}], system="sys", tools=[],
        on_delta=deltas.append, should_abort=lambda: False)
    assert result.text == "Claude 回答" and deltas == ["Claude 回答"]
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-secret"
    assert "--safe-mode" in seen["command"] and "--tools" in seen["command"]
    assert "stream-json" in seen["command"]
    assert "--include-partial-messages" in seen["command"]


def test_claude_subscription_enables_read_for_image_and_lists_path(tmp_path):
    seen = {}
    image = tmp_path / "畫面.png"
    image.write_bytes(b"png")

    def run(command, **kwargs):
        seen["command"] = command
        seen["prompt"] = kwargs["input"]
        return subprocess.CompletedProcess(
            command, 0, stdout=_claude_result("看到了"), stderr="")

    ClaudeSubscriptionProvider(
        "", run=run, command_factory=lambda: ["claude"]
    ).stream_chat([{"role": "user", "content": "看圖", "images": [{
        "name": image.name, "media_type": "image/png", "data": "cG5n",
        "path": str(image)}]}], system="s", tools=[],
        on_delta=lambda _x: None, should_abort=lambda: False)
    tools_at = seen["command"].index("--tools")
    assert seen["command"][tools_at + 1] == "Read"
    add_dir_at = seen["command"].index("--add-dir")
    assert seen["command"][add_dir_at + 1] == str(image.parent.resolve())
    assert str(image.resolve()) in seen["prompt"]


def test_claude_subscription_streams_partial_plain_text():
    lines = [
        {"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "逐"}}},
        {"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "段顯示"}}},
        {"type": "result", "subtype": "success",
         "result": "逐段顯示"},
    ]

    def run(command, **_kwargs):
        stdout = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    deltas = []
    result = ClaudeSubscriptionProvider(
        "sonnet", run=run, command_factory=lambda: ["claude"]
    ).stream_chat([], system="s", tools=[], on_delta=deltas.append,
                  should_abort=lambda: False)
    assert deltas == ["逐", "段顯示"]
    assert result.text == "逐段顯示"


def test_claude_production_popen_path_forwards_each_jsonl_delta():
    lines = [
        json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "A"}}}) + "\n",
        json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "B"}}}) + "\n",
        json.dumps({"type": "result", "subtype": "success",
                    "result": "AB"}) + "\n",
    ]

    class Stdin:
        def write(self, _value): return None
        def close(self): return None

    class Stdout:
        def __iter__(self): return iter(lines)

    class Stderr:
        def read(self): return ""

    class Process:
        def __init__(self):
            self.stdin, self.stdout, self.stderr = Stdin(), Stdout(), Stderr()
            self.returncode = 0
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def kill(self): return None
        def terminate(self): return None

    deltas = []
    result = ClaudeSubscriptionProvider(
        "", popen=lambda *_a, **_k: Process(),
        command_factory=lambda: ["claude"]
    ).stream_chat([], system="s", tools=[], on_delta=deltas.append,
                  should_abort=lambda: False)
    assert deltas == ["A", "B"] and result.text == "AB"


def test_claude_setup_token_is_forwarded_when_cli_runs_in_wsl():
    seen = {}

    def run(command, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command, 0, stdout=_claude_result("ok"), stderr="")

    ClaudeSubscriptionProvider(
        "", oauth_token="oauth-secret", run=run,
        command_factory=lambda: [r"C:\Windows\System32\wsl.exe", "-e", "bash",
                                 "-lc", 'exec claude "$@"', "claude"]
    ).stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                  should_abort=lambda: False)
    assert "CLAUDE_CODE_OAUTH_TOKEN" in seen["env"]["WSLENV"].split(":")


def test_claude_subscription_removes_api_billing_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "paid-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "paid-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "stale-oauth")
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(
            command, 0, stdout=_claude_result("ok"), stderr="")

    ClaudeSubscriptionProvider(
        "", run=run, command_factory=lambda: ["claude"]
    ).stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                  should_abort=lambda: False)
    assert "ANTHROPIC_API_KEY" not in seen
    assert "ANTHROPIC_AUTH_TOKEN" not in seen
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in seen


def test_claude_subscription_aborts_before_starting_process():
    called = []
    provider = ClaudeSubscriptionProvider(
        "", run=lambda *a, **k: called.append(1),
        command_factory=lambda: ["claude"])
    with pytest.raises(AiAborted):
        provider.stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                             should_abort=lambda: True)
    assert called == []


def test_factory_selects_subscription_providers():
    assert isinstance(make_provider("openai", "", "m", auth_mode="subscription"),
                      OpenAiSubscriptionProvider)
    profile = AuthProfile("anthropic", "default", "oauth", source="setup-token")
    provider = make_provider("anthropic", "", "m", auth_mode="subscription",
                             auth_profile=profile)
    assert isinstance(provider, ClaudeSubscriptionProvider)


def test_claude_model_is_inserted_after_wrapped_windows_command():
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(
            command, 0, stdout=_claude_result("ok"), stderr="")

    prefix = ["cmd.exe", "/d", "/s", "/c", "claude.cmd"]
    ClaudeSubscriptionProvider(
        "sonnet", run=run, command_factory=lambda: prefix
    ).stream_chat([], system="s", tools=[], on_delta=lambda _x: None,
                  should_abort=lambda: False)
    assert seen["command"][:5] == prefix
    assert seen["command"][5:7] == ["--model", "sonnet"]
