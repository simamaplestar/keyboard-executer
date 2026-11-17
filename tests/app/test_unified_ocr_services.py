from dataclasses import replace
import threading
from unittest.mock import Mock

import pytest

from keyboard_executor.app.sequence_input_service import build_sequence_runtime
from keyboard_executor.app.settings import Settings
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine
from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
from tests.app.test_sequence_panel_service import setup
from tests.core.test_sequence_input_config import config_data


@pytest.mark.parametrize('mode', ['panel', 'manual'])
@pytest.mark.parametrize('chat', [False, True])
def test_both_sequence_modes_wrap_rapid_and_share_only_one_process_with_chat(monkeypatch, mode, chat):
    from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
    _, platform, backend, _, script = setup(chat)
    if mode == 'manual':
        script = replace(script, settings=replace(script.settings,
            sequence_input=sequence_config_from_dict(config_data())))
    direct = RapidOcrEngine()
    platform = replace(platform, ocr_engine=direct)
    provider = Mock()
    provider.stream_chat.side_effect = AssertionError('no live provider in routing test')
    # Legacy synthetic-image preflight is covered separately, not part of OCR routing.
    monkeypatch.setattr('keyboard_executor.app.sequence_input_service.preflight', lambda *a: None)
    runtime = build_sequence_runtime(
        Settings(ai_provider='openai', ai_model='custom', ai_api_key='test'),
        None, script, platform, threading.Event(), None, provider_factory=lambda *a, **kw: provider)
    engine = runtime.watcher._platform.ocr_engine
    try:
        assert isinstance(engine, ProcessOcrEngine)
        assert platform.ocr_engine is direct
        assert direct._engine is None and engine._process is None
        if chat:
            assert runtime.chat._platform.ocr_engine is engine
        assert backend.calls == []
    finally:
        runtime.close()
        engine._reaper.join(3)
