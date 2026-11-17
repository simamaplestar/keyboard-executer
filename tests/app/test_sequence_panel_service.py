from dataclasses import replace
import threading
from unittest.mock import Mock
import pytest
from keyboard_executor.app.settings import Settings
from keyboard_executor.core.models import script_from_dict, ScriptValidationError
from tests.core.test_sequence_input_config import script_data
from tests.core.test_chat_reply_config import config_data as chat_data
from tests.core.test_player_flow import make_platform
from tests.fakes import FakeOcrEngine, FakeScreenCapture


def setup(chat=False):
    from keyboard_executor.app.sequence_input_service import build_sequence_runtime
    platform, backend = make_platform()
    class Engine(FakeOcrEngine):
        closes = 0
        def close(self): self.closes += 1
    engine = Engine()
    platform = replace(platform, ocr_engine=engine, screen_capture=FakeScreenCapture())
    data = script_data()
    data['settings']['sequence_input'] = dict(enabled=True, mode='panel', panel_region=[0, 0, 400, 300])
    if chat: data['settings']['chat_reply'] = chat_data()
    return build_sequence_runtime, platform, backend, engine, script_from_dict(data)


@pytest.mark.parametrize('chat', [False, True])
def test_zero_startup_ai_and_shared_ocr(chat):
    build, platform, backend, engine, script = setup(chat)
    provider = Mock()
    provider.stream_chat.side_effect = AssertionError('must not preflight')
    runtime = build(Settings(ai_provider='openai', ai_model='custom', ai_api_key='key'),
        None, script, platform, threading.Event(), None, provider_factory=lambda *a, **kw: provider)
    try:
        assert provider.stream_chat.call_count == 0
        assert not backend.calls
        assert runtime.watcher._platform.ocr_engine is engine
        if chat: assert runtime.chat._platform.ocr_engine is engine
    finally: runtime.close(); runtime.close()
    assert engine.closes == 1


def test_missing_ocr_fails_without_ai():
    build, platform, backend, engine, script = setup()
    provider = Mock()
    with pytest.raises(ScriptValidationError):
        build(Settings(ai_provider='openai', ai_model='custom', ai_api_key='key'), None,
            script, replace(platform, ocr_engine=None), threading.Event(), None,
            provider_factory=lambda *a, **kw: provider)
    assert provider.stream_chat.call_count == 0
    assert not backend.calls


def test_service_wires_detection_to_configured_discord(monkeypatch):
    build, platform, backend, engine, script = setup()
    from keyboard_executor.core import sequence_discord
    calls = []
    monkeypatch.setattr(sequence_discord, 'post_discord', lambda *a, **kw: calls.append((a, kw)))
    url = 'https://discord.com/api/webhooks/test/token'
    runtime = build(Settings(ai_provider='openai', ai_model='custom', ai_api_key='key', discord_webhook_url=url),
        None, script, platform, threading.Event(), None, provider_factory=lambda *a, **kw: Mock())
    try:
        runtime.watcher._on_detected(1)
        assert len(calls) == 1
        assert calls[0][0][0] == url
    finally: runtime.close()
