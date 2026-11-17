import json
import sys
import threading
import time
from concurrent.futures import wait
from dataclasses import replace

import numpy as np
import cv2
import pytest

from keyboard_executor.core.ai.provider import ChatResult
from keyboard_executor.core.chat_reply_config import chat_config_from_dict
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.factory import Platform
from tests.core.test_chat_reply_config import config_data, script_data
from tests.core.test_player_flow import make_window
from tests.fakes import FakeInputBackend, FakeWindowManager, FakeScreenCapture, FakeOcrEngine


_sessions = []


@pytest.fixture(autouse=True)
def close_sessions():
    yield
    for session in _sessions:
        session._stop.set()
        session.close()
    _sessions.clear()


class Provider:
    def __init__(self, respond=None):
        self.calls = []
        self.respond = respond or (lambda payload: {"replies": [
            {"message_id": payload["new_messages"][0]["id"], "text": "收到，謝謝"}]})

    def stream_chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        payload = json.loads(messages[0]["content"])
        return ChatResult(text=json.dumps(self.respond(payload), ensure_ascii=False))


def make_session(provider=None, stop=None, config=None, *, visual_delivery=False):
    from keyboard_executor.core.chat_reply import ChatReplySession
    cfg = config or config_data()
    cfg["region"] = [0, 0, 90, 60]
    script = script_from_dict(script_data(cfg))
    image = np.zeros((60, 90, 3), dtype=np.uint8)
    cv2.putText(image, "Chat", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, .5,
                (0, 255, 0), 1, cv2.LINE_AA)
    old = TextBox("朋友[CH.301]>>早安", 0, 0, 85, 20, .99)
    new = TextBox("朋友[CH.301]>>你好", 0, 0, 85, 20, .99)
    backend = FakeInputBackend()
    window = replace(make_window("遊戲"), is_active=True)
    platform = Platform(backend, FakeWindowManager([window]),
                        screen_capture=FakeScreenCapture(image),
                        ocr_engine=FakeOcrEngine([[old], [new], [new]]))
    capture = platform.screen_capture.capture

    def changing_frame(region):
        # 佇列 OCR 模擬不同畫面；即使只改聊天外一個像素也必須重新辨識。
        image = capture(region).copy()
        image[-1, -1, 0] = len(platform.screen_capture.captures) % 256
        return image

    platform.screen_capture.capture = changing_frame
    records = []
    clock = [0.0]
    stop = stop or threading.Event()
    session = ChatReplySession(platform, script.settings.chat_reply, provider or Provider(),
                               stop, records.append, clock=lambda: clock[0])
    if not visual_delivery:
        # These tests isolate OCR/AI scheduling with a chat-log-only image. The
        # channel tests provide a complete game form and use the built-in route.
        session._config = script.settings.chat_reply
    _sessions.append(session)
    return session, script, window, backend, records, clock, stop


def scan(session, script, win):
    """測試輔助：推進一次掃描／AI／確認流程，每階段模擬下一個動作邊界。"""
    def completed(future):
        deadline = time.monotonic() + 2
        while not future.done():
            if session._aborted():
                return False
            assert time.monotonic() < deadline
            wait([future], timeout=.01)
        return not session._aborted()

    session(script, win)
    pending = session._scan
    if pending is not None and completed(pending):
        session(script, win)
    pending = session._ai_result
    if pending is not None and completed(pending):
        session(script, win)


def trigger(session, script, win, clock):
    scan(session, script, win)  # baseline
    clock[0] = 4.0
    scan(session, script, win)


def test_identical_frame_reuses_ocr_without_retriggering_ai():
    session, script, win, backend, _, clock, _ = make_session()
    capture = session._platform.screen_capture
    capture.capture = lambda _: capture.image.copy()
    scan(session, script, win)
    clock[0] = 4
    scan(session, script, win)
    assert len(session._platform.ocr_engine.calls) == 1
    assert session._provider.calls == []
    assert backend.calls == []


def test_chat_uses_literal_text_for_recipient_and_reply():
    session, script, win, backend, _, clock, _ = make_session()
    typed = []
    backend.type_text_literal = typed.append
    trigger(session, script, win, clock)
    assert typed == ['收到，謝謝']   # 名字由 H 帶入
    assert not any(call[0] == 'type_text' for call in backend.calls)


@pytest.mark.parametrize("recognize", [True, False])
def test_scan_accepts_unhashable_native_window(recognize):
    # pywinctl.Win32Window implements equality but is not hashable.
    session, _, win, backend, _, _, _ = make_session()
    win = replace(win, handle=[])
    session._platform.window_manager.windows = [win]
    capture = session._platform.screen_capture
    capture.capture = lambda _: capture.image.copy()
    for _ in range(2):
        image, boxes = session._read_frame(win, recognize=recognize)
        assert np.array_equal(image, capture.image)
        assert [box.text for box in boxes] == (["朋友[CH.301]>>早安"] if recognize else [])
    assert len(session._platform.ocr_engine.calls) == int(recognize)
    assert backend.calls == []


def test_ocr_cache_does_not_cross_window_objects_with_identical_pixels():
    session, _, win, _, _, _, _ = make_session()
    first, second = replace(win, handle=[1]), replace(win, handle=[2])
    session._platform.window_manager.windows = [first, second]
    capture = session._platform.screen_capture
    capture.capture = lambda _: capture.image.copy()
    _, first_boxes = session._read_frame(first)
    _, second_boxes = session._read_frame(second)
    assert first_boxes[0].text == "朋友[CH.301]>>早安"
    assert second_boxes[0].text == "朋友[CH.301]>>你好"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows window contract")
def test_scan_accepts_real_win32_window():
    import ctypes
    import pywinctl

    desktop = ctypes.windll.user32.GetDesktopWindow
    desktop.restype = ctypes.c_void_p
    session, _, win, backend, _, _, _ = make_session()
    win = replace(win, handle=pywinctl.Window(desktop()))
    session._platform.window_manager.windows = [win]
    capture = session._platform.screen_capture
    capture.capture = lambda _: capture.image.copy()
    for recognize in (False, True, True):
        image, boxes = session._read_frame(win, recognize=recognize)
        assert np.array_equal(image, capture.image)
        assert bool(boxes) == recognize
    assert len(session._platform.ocr_engine.calls) == 1
    assert backend.calls == []


def test_ai_completion_timing_is_logged_before_waiting_for_next_action(caplog):
    import logging
    caplog.set_level(logging.INFO, logger='keyboard_executor.core.chat_reply')
    session, script, win, backend, _, clock, _ = make_session()
    scan(session, script, win)
    clock[0] = 4
    session(script, win)
    assert wait([session._scan], timeout=2).done
    session(script, win)
    assert wait([session._ai_result], timeout=2).done
    assert backend.calls == []
    assert any('AI 產生耗時' in record.message for record in caplog.records)
    session(script, win)
    assert any('等待動作結束' in record.message for record in caplog.records)


def test_ready_ai_reply_confirms_and_sends_at_the_same_action_boundary():
    session, script, win, backend, _, clock, _ = make_session()
    scan(session, script, win)
    clock[0] = 4
    session(script, win)
    assert wait([session._scan], timeout=2).done
    session(script, win)
    assert wait([session._ai_result], timeout=2).done
    # 背景完成不能自己打字；必須等下一個動作邊界。
    assert backend.calls == []
    session(script, win)
    # 已到動作邊界且 AI 完成，就在此確認並送出，不能先跑下一個長按，
    # 讓背景確認的截圖跨過 6～15 秒後才被使用。
    assert ("type_text", "收到，謝謝") in backend.calls


def test_close_while_ai_is_waiting_discards_reply_without_stopping_other_session():
    entered, release = threading.Event(), threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)
            return super().stream_chat(*args, **kwargs)

    session, script, win, backend, _, clock, stop = make_session(SlowProvider())
    scan(session, script, win)
    clock[0] = 4
    session(script, win)
    assert wait([session._scan], timeout=2).done
    session(script, win)
    pending = session._ai_result
    try:
        assert entered.wait(2)
        session.close()
        assert wait([pending], timeout=.3).done
        assert not stop.is_set()
        release.set()
        session(script, win)
        assert backend.calls == []
    finally:
        release.set()


def test_unchanged_confirmation_frame_sends_without_second_ocr():
    session, script, win, backend, _, clock, _ = make_session()
    capture = session._platform.screen_capture
    count = 0

    def frames(_):
        nonlocal count
        count += 1
        image = capture.image.copy()
        image[-1, -1, 0] = min(count, 2)
        return image

    capture.capture = frames
    trigger(session, script, win, clock)
    assert len(session._platform.ocr_engine.calls) == 2
    assert [c[1] for c in backend.calls] == ["h", "enter", "收到，謝謝", "enter"]


def test_empty_ocr_result_is_retried_even_when_pixels_are_unchanged():
    session, script, win, _, _, clock, _ = make_session()
    capture = session._platform.screen_capture
    capture.capture = lambda _: capture.image.copy()
    session._platform.ocr_engine._boxes.insert(0, [])
    scan(session, script, win)
    clock[0] = 4
    scan(session, script, win)
    assert len(session._platform.ocr_engine.calls) == 2
    assert session._observer.history


def test_scan_interval_includes_ocr_and_current_action_time():
    session, script, win, _, _, clock, _ = make_session()
    session(script, win)
    assert wait([session._scan], timeout=2).done
    # 第一次辨識與目前的長按花了 9 秒，不應再多等完整檢查間隔。
    clock[0] = 9
    session(script, win)
    assert session._scan is not None
    assert wait([session._scan], timeout=2).done
    assert len(session._platform.ocr_engine.calls) == 2


def test_fast_scan_still_respects_configured_interval():
    session, script, win, _, _, clock, _ = make_session()
    scan(session, script, win)
    clock[0] = 1
    scan(session, script, win)
    assert len(session._platform.ocr_engine.calls) == 1
    clock[0] = session._config.interval_sec
    session(script, win)
    assert session._scan is not None


@pytest.mark.parametrize("channel", ["map", "whisper"])
def test_disabled_channel_stays_in_context_without_calling_ai(channel):
    cfg = config_data()
    cfg[f"reply_{channel}"] = False
    session, script, win, backend, _, clock, _ = make_session(config=cfg)
    if channel == "map":
        image = session._platform.screen_capture.image
        image[:] = 0
        cv2.putText(image, "Chat", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, .5,
                    (255, 255, 255), 1, cv2.LINE_AA)
        session._platform.ocr_engine._boxes = [
            [TextBox(f"朋友：{text}", 0, 0, 85, 20, .99)] for text in ("早安", "你好")]
    trigger(session, script, win, clock)
    assert session._provider.calls == []
    assert backend.calls == []
    assert session._observer.history[-1].text == "你好"


def test_new_disabled_channel_during_ai_does_not_delay_enabled_whisper():
    cfg = config_data()
    cfg["reply_map"] = False
    session, script, win, backend, _, clock, _ = make_session(config=cfg)
    image = session._platform.screen_capture.image
    cv2.putText(image, "Map", (2, 46), cv2.FONT_HERSHEY_SIMPLEX, .5,
                (255, 255, 255), 1, cv2.LINE_AA)
    session._platform.ocr_engine._boxes[-1] += [TextBox("路人：新對話", 0, 30, 85, 20, .99)]
    trigger(session, script, win, clock)
    assert len(session._provider.calls) == 1
    assert ("type_text", "收到，謝謝") in backend.calls
    assert session._ai_result is None


def test_both_channels_disabled_never_capture_or_call_ai():
    cfg = config_data()
    cfg.update(reply_map=False, reply_whisper=False)
    session, script, win, backend, _, _, _ = make_session(config=cfg)
    session(script, win)
    assert session._scan is None
    assert session._platform.screen_capture.captures == []
    assert session._provider.calls == []
    assert backend.calls == []


def test_whisper_uses_source_sender_and_history_then_deduplicates():
    provider = Provider()
    session, script, win, backend, records, clock, stop = make_session(provider)
    trigger(session, script, win, clock)
    assert [c[1] for c in backend.calls] == ["h", "enter", "收到，謝謝", "enter"]
    payload = json.loads(provider.calls[0][0][0]["content"])
    assert "早安" in json.dumps(payload["history"], ensure_ascii=False)
    assert not ({m["id"] for m in payload["history"]}
                & {m["id"] for m in payload["new_messages"]})
    assert provider.calls[0][0][0]["images"][0]["data"]
    clock[0] = 8
    scan(session, script, win)
    assert len(provider.calls) == 1


def test_new_whisper_above_fixed_input_footer_reaches_ai_and_reply_route():
    provider = Provider()
    session, script, win, backend, records, clock, _ = make_session(provider)
    image = session._platform.screen_capture.image
    cv2.putText(image, "Input", (2, 48), cv2.FONT_HERSHEY_SIMPLEX, .5,
                (255, 255, 255), 1, cv2.LINE_AA)
    footer = TextBox("對所有人7", 0, 30, 85, 20, .99)
    session._platform.ocr_engine._boxes = [row + [footer]
                                          for row in session._platform.ocr_engine._boxes]
    trigger(session, script, win, clock)
    assert [c[1] for c in backend.calls] == ["h", "enter", "收到，謝謝", "enter"]
    assert len(provider.calls) == 1
    assert any("監看已就緒" in r["message"] for r in records)
    clock[0] = 8
    scan(session, script, win)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("response", [
    {"replies": [{"message_id": 9999, "text": "錯人"}]},
    {"replies": [{"message_id": 2, "text": "第一行\n第二行"}]},
    {"replies": [{"message_id": 2, "text": "/指令"}]},
    {"replies": [{"message_id": 2, "text": "嗨", "recipient": "別人"}]},
])
def test_invalid_ai_output_never_types(response):
    session, script, win, backend, records, clock, _ = make_session(Provider(lambda _: response))
    trigger(session, script, win, clock)
    assert backend.calls == []
    assert any(r["kind"] == "notify" for r in records)


def test_ai_can_skip_irrelevant_chat():
    session, script, win, backend, _, clock, _ = make_session(Provider(lambda _: {"replies": []}))
    trigger(session, script, win, clock)
    assert not backend.calls


def test_white_map_chat_uses_map_route_without_whisper_recipient():
    session, script, win, backend, _, clock, _ = make_session()
    image = session._platform.screen_capture.image
    image[:] = 0
    cv2.putText(image, "Chat", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, .5,
                (255, 255, 255), 1, cv2.LINE_AA)
    old = TextBox("路人：早安", 0, 0, 85, 20, .99)
    new = TextBox("路人：你好", 0, 0, 85, 20, .99)
    session._platform.ocr_engine._boxes = [[old], [new], [new]]
    trigger(session, script, win, clock)
    assert [c[:2] for c in backend.calls] == [("type_text", "收到，謝謝"), ("key_press", "enter")]


def test_stop_while_provider_is_waiting_discards_late_reply():
    started = threading.Event()
    release = threading.Event()
    stop = threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            started.set()
            release.wait(3)
            return super().stream_chat(*args, **kwargs)

    session, script, win, backend, _, clock, _ = make_session(SlowProvider(), stop)
    scan(session, script, win)
    clock[0] = 4
    worker = threading.Thread(target=scan, args=(session, script, win))
    worker.start()
    try:
        assert started.wait(2)
        stop.set()
        worker.join(1)
        assert not worker.is_alive()
    finally:
        release.set()
        worker.join(3)
    assert backend.calls == []


def test_send_failure_aborts_instead_of_resuming_keys_in_chat_box():
    session, script, win, backend, _, clock, _ = make_session()
    backend.type_text = lambda _: (_ for _ in ()).throw(RuntimeError("輸入失敗"))
    scan(session, script, win)
    clock[0] = 4
    with pytest.raises(RuntimeError, match="回覆操作"):
        scan(session, script, win)


def test_timeout_does_not_send_late_response_or_start_another_request():
    release = threading.Event()
    finished = threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            try:
                release.wait(3)
                return super().stream_chat(*args, **kwargs)
            finally:
                finished.set()

    cfg = config_data()
    cfg["timeout_sec"] = 1
    provider = SlowProvider()
    session, script, win, backend, records, clock, _ = make_session(provider, config=cfg)
    try:
        trigger(session, script, win, clock)
        assert any("逾時" in r["message"] for r in records)
        clock[0] = 8
        scan(session, script, win)
        assert not backend.calls
    finally:
        release.set()
        assert finished.wait(2)
    assert len(provider.calls) == 1
    assert not backend.calls


def test_ai_skip_does_not_interrupt_script_or_activate_window():
    provider = Provider(lambda _: {"replies": []})
    session, script, win, backend, _, clock, _ = make_session(provider)
    wm = session._platform.window_manager
    during_ai = []

    def skip(_):
        during_ai.append(len(wm.activated))
        return {"replies": []}

    provider.respond = skip
    trigger(session, script, win, clock)
    assert len(wm.activated) == during_ai[0]
    assert backend.target_windows == []


def test_failed_foreground_restore_aborts_instead_of_resuming():
    provider = Provider()
    session, script, win, backend, _, clock, _ = make_session(provider)

    def lose_window(payload):
        session._platform.window_manager.activate_result = False
        return {"replies": [{"message_id": payload["new_messages"][0]["id"], "text": "收到"}]}

    provider.respond = lose_window
    scan(session, script, win)
    clock[0] = 4
    with pytest.raises(RuntimeError, match="視窗"):
        scan(session, script, win)
    assert backend.calls == []


def test_new_message_during_ai_discards_stale_reply_and_requeries_context():
    provider = Provider()
    session, script, win, backend, _, clock, _ = make_session(provider)
    boxes = [TextBox(text, 0, 0, 85, 20, .99)
             for text in ("朋友[CH.301]>>早安", "朋友[CH.301]>>請幫我", "朋友[CH.301]>>不用了")]
    session._platform.ocr_engine._boxes = [[boxes[0]], [boxes[1]], [boxes[2]], [boxes[2]]]
    trigger(session, script, win, clock)
    assert backend.calls == []
    clock[0] = 8
    scan(session, script, win)
    assert len(provider.calls) == 2
    payload = json.loads(provider.calls[1][0][0]["content"])
    assert [m["text"] for m in payload["new_messages"]] == ["請幫我", "不用了"]
    assert ("type_text", "收到，謝謝") in backend.calls


def test_background_scan_never_activates_an_inactive_window():
    session, script, win, backend, _, clock, _ = make_session()
    win = replace(win, is_active=False)
    session._platform.window_manager.windows = [win]
    scan(session, script, win)
    assert session._platform.window_manager.activated == []
    assert session._platform.screen_capture.captures == []
    assert backend.calls == []


def test_stop_during_final_ocr_check_discards_reply_without_waiting():
    session, script, win, backend, _, clock, stop = make_session()
    entered, release = threading.Event(), threading.Event()
    original = session._platform.ocr_engine.recognize
    scans = 0

    def recognize(image):
        nonlocal scans
        scans += 1
        if scans == 3:
            entered.set()
            assert release.wait(3)
        return original(image)

    session._platform.ocr_engine.recognize = recognize
    worker = threading.Thread(target=trigger, args=(session, script, win, clock))
    worker.start()
    try:
        assert entered.wait(2)
        stop.set()
        worker.join(.3)
        assert not worker.is_alive()
        assert backend.calls == []
    finally:
        release.set()
        worker.join(3)
        if session._scan is not None:
            assert wait([session._scan], timeout=2).done
    assert backend.calls == []


def test_restart_during_old_ocr_does_not_overlap_or_deliver_old_result():
    old, script, win, backend, _, clock, stop = make_session()
    entered, release = threading.Event(), threading.Event()

    def blocked(_):
        entered.set()
        assert release.wait(3)
        return []

    old._platform.ocr_engine.recognize = blocked
    old(script, win)
    old_scan = old._scan
    try:
        assert entered.wait(2)
        stop.set()
        old.close()
        new, new_script, new_win, new_backend, _, _, _ = make_session()
        new_entered = threading.Event()
        new._platform.ocr_engine.recognize = lambda _: (new_entered.set(), [])[1]
        new(new_script, new_win)
        assert not new_entered.wait(.1)
        release.set()
        assert new_entered.wait(2)
        assert wait([old_scan, new._scan], timeout=2).done
        old(script, win)
        assert old_scan.result() is None
        assert backend.calls == new_backend.calls == []
    finally:
        release.set()


def test_closed_session_does_not_launch_new_scan():
    session, script, win, _, _, _, _ = make_session()
    session.close()
    session(script, win)
    assert not session._platform.ocr_engine.calls
    assert session._scan is None


@pytest.mark.parametrize("change", ["focus", "position"])
def test_capture_discarded_when_window_changes_during_scan(change):
    session, script, win, _, _, _, _ = make_session()
    manager = session._platform.window_manager
    cap = session._platform.screen_capture
    capture = cap.capture

    def changed(region):
        image = capture(region)
        manager.refresh = lambda _: replace(win, **(
            {"is_active": False} if change == "focus" else {"x": 10}))
        return image

    cap.capture = changed
    scan(session, script, win)
    assert session._observer.history == []
    assert session._platform.ocr_engine.calls == []
