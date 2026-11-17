import base64
from dataclasses import replace
import json
import threading
import time
import cv2
import numpy as np
import pytest
from keyboard_executor.core.ai.provider import ChatResult
from keyboard_executor.core.ai.sequence_recognizer import SequenceRecognizer
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from keyboard_executor.core.sequence_watcher import SequenceWatcher
from keyboard_executor.core.sequence_submitter import SequenceSubmitter
from keyboard_executor.core.visual_intervention import VisualIntervention
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager, FakeScreenCapture, FakeOcrEngine
from tests.core.test_sequence_input_config import config_data, script_data


@pytest.mark.parametrize("prompt_stays", [False, True])
def test_real_capture_ocr_ai_submit_and_resume_pipeline(prompt_stays):
    started = time.monotonic()
    clock = lambda: (time.monotonic() - started) * 10
    stop = threading.Event()
    confirmed = []
    backend = FakeInputBackend()
    win = WindowInfo(1, "記事本", "app", 0, 0, 500, 500, True)
    original_click = backend.mouse_click
    def click(x, y, button, count):
        original_click(x, y, button, count)
        if (x,y) == (330,220): confirmed.append(clock())
    backend.mouse_click = click
    cap = FakeScreenCapture()
    def capture(rect):
        if rect.width == 300: marker = 1 if not confirmed or prompt_stays else 0
        else: marker = int(clock()) % 3 + 1
        return np.full((rect.height, rect.width, 3), marker, np.uint8)
    cap.capture = capture
    ocr = FakeOcrEngine()
    ocr.recognize = lambda image: [TextBox("請按照號碼順序輸入文字",0,0,100,20,.99)] if image[0,0,0] else []
    class Provider:
        def stream_chat(self, messages, **kwargs):
            rows = []
            ids = json.loads(messages[0]["content"])["sample_ids"]
            for sid, image in zip(ids, messages[0]["images"]):
                raw = cv2.imdecode(np.frombuffer(base64.b64decode(image["data"]), np.uint8), cv2.IMREAD_COLOR)
                marker = int(raw[0,0,0])
                index, char = {1:(3,"P"),2:(1,"H"),3:(2,"D")}[marker]
                rows.append(dict(sample_id=sid,index=index,char=char))
            return ChatResult(json.dumps({"readings":rows}))
    platform = Platform(backend, FakeWindowManager([win]), cap, ocr)
    config = sequence_config_from_dict(config_data())
    watcher = SequenceWatcher(platform, config, SequenceRecognizer(Provider()), stop, clock=clock)
    submitter = SequenceSubmitter(platform, config, watcher, stop, clock=clock)
    runtime = VisualIntervention(watcher, submitter)
    data = script_data()
    data["actions"] = [{"type":"delay","ms":600}, {"type":"key_press","key":"z"}]
    try:
        result = Player(platform, stop_event=stop, on_action_boundary=runtime).play(script_from_dict(data))
        assert "".join(c[1] for c in backend.calls if c[0] == "type_text") == "HDP"
        assert len(confirmed) == 1
        assert confirmed[0] < 30
        if prompt_stays:
            assert not result.ok and stop.is_set()
            assert ("key_press","z",0) not in backend.calls
            assert not any(c[:2] in {("key_press", "z"), ("key_down", "z")} for c in backend.calls)
        else:
            assert result.ok
            assert backend.calls[-2:] == [("key_down", "z"), ("key_up", "z")]
            assert clock() < 30
    finally:
        runtime.close()
