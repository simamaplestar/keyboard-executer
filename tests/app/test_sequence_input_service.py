from dataclasses import replace
import json
import threading
import pytest
from keyboard_executor.app.settings import Settings
from keyboard_executor.core.ai.provider import ChatResult
from keyboard_executor.core.models import script_from_dict, ScriptValidationError
from tests.core.test_sequence_input_config import script_data
from tests.core.test_chat_reply_config import config_data as chat_data
from tests.core.test_player_flow import make_platform
from tests.fakes import FakeOcrEngine, FakeScreenCapture


class ProbeProvider:
    def stream_chat(self, messages, **kwargs):
        ids = json.loads(messages[0]["content"])["sample_ids"]
        return ChatResult(json.dumps({"readings":[{"sample_id":i,"index":1,"char":"A"} for i in ids]}))


def test_both_services_share_one_engine_with_single_owner():
    from keyboard_executor.app.sequence_input_service import build_sequence_runtime
    platform, backend = make_platform()
    class Engine(FakeOcrEngine):
        closes = 0
        def close(self): self.closes += 1
    engine = Engine()
    platform = replace(platform, ocr_engine=engine, screen_capture=FakeScreenCapture())
    data = script_data()
    data["settings"]["chat_reply"] = chat_data()
    runtime = build_sequence_runtime(Settings(ai_provider="openai", ai_model="custom", ai_api_key="key"),
        None, script_from_dict(data), platform, threading.Event(), None,
        provider_factory=lambda *a, **kw: ProbeProvider())
    assert runtime.watcher._platform.ocr_engine is engine
    assert runtime.chat._platform.ocr_engine is engine
    assert not backend.calls
    runtime.chat.suspend()
    assert engine.closes == 0
    runtime.close()
    runtime.close()
    assert engine.closes == 1


def test_preflight_failure_leaves_no_input():
    from keyboard_executor.app.sequence_input_service import build_sequence_runtime
    platform, backend = make_platform()
    platform = replace(platform, ocr_engine=FakeOcrEngine(), screen_capture=FakeScreenCapture())
    class BadProvider:
        def stream_chat(self, *a, **kw): return ChatResult("text only")
    with pytest.raises(ScriptValidationError):
        build_sequence_runtime(Settings(ai_provider="openai", ai_model="custom", ai_api_key="key"),
            None, script_from_dict(script_data()), platform, threading.Event(), None,
            provider_factory=lambda *a, **kw: BadProvider())
    assert backend.calls == []


def test_preflight_can_be_cancelled_while_provider_blocks():
    from keyboard_executor.app.sequence_input_service import preflight
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    class Recognizer:
        def recognize(self, *a, **kw):
            entered.set()
            release.wait(3)
            return []
    timer = threading.Thread(target=lambda: (entered.wait(2), stop.set()), daemon=True)
    timer.start()
    try:
        with pytest.raises(ScriptValidationError): preflight(Recognizer(), stop)
    finally:
        release.set()
        timer.join(2)
