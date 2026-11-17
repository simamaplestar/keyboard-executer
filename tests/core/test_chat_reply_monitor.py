"""Exercise the GUI's actual chat service while the player cannot reach a boundary."""
import json
import threading
import time
from dataclasses import replace

import pytest

from keyboard_executor.app.chat_reply_service import build_chat_session
from keyboard_executor.app.settings import Settings
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import TextBox
from tests.core.test_chat_reply import Provider, make_session


def background_session(provider=None, interval=1):
    fixture, script, win, backend, records, _, stop = make_session(provider)
    script = replace(script, settings=replace(script.settings, chat_reply=replace(
        script.settings.chat_reply, interval_sec=interval)))
    session = build_chat_session(
        Settings(ai_provider="openai", ai_model="fake", ai_api_key="test"), None,
        script, fixture._platform, stop, records.append,
        provider_factory=lambda *_: fixture._provider)
    # The scheduling fixture has a transcript only, no game input form. Real
    # form/delivery guards are exercised by test_chat_reply_channel/pointer.
    session._config = script.settings.chat_reply
    return session, script, win, backend, records, stop


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        threading.Event().wait(.01)


@pytest.mark.parametrize("action", [
    {"type": "key_press", "key": "left", "hold_ms": 15000},
    {"type": "delay", "ms": 15000},
], ids=["held-key", "delay"])
def test_one_second_monitor_starts_ai_inside_long_action_and_sends_after_release(action):
    session, _, win, backend, _, stop = background_session()
    entered, release = threading.Event(), threading.Event()
    times, input_threads, results = [], [], []
    recognize = session._platform.ocr_engine.recognize
    type_text = backend.type_text

    def read(image):
        times.append(time.monotonic())
        return recognize(image)

    def type_reply(text):
        input_threads.append(threading.get_ident())
        type_text(text)

    def long_action(_):
        entered.set()
        assert release.wait(6)

    session._platform.ocr_engine.recognize = read
    backend.type_text = type_reply
    script = script_from_dict({"name": "long", "target_window": {"title_pattern": win.title},
                               "actions": [action, {"type": "key_press", "key": "b"}]})
    player = Player(session._platform, stop_event=stop, sleep=long_action,
                    on_action_boundary=session)
    worker = threading.Thread(target=lambda: results.append(player.play(script)))
    worker.start()
    try:
        assert entered.wait(1)
        eventually(lambda: session._ai_result is not None and session._ai_result.done(), 3)
        assert len(session._provider.calls) == 1
        assert .9 <= times[1] - times[0] < 1.6
        assert not input_threads, "AI may prepare during a held key, but never type"
        assert ("key_up", "left") not in backend.calls
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert results[0].ok
        assert input_threads and set(input_threads) == {worker.ident}
        calls = [call[1] for call in backend.calls]
        assert calls[-1] == "b"
        assert calls.count("收到，謝謝") == 1
        if action["type"] == "key_press":
            assert backend.calls[:2] == [("key_down", "left"), ("key_up", "left")]
    finally:
        stop.set()
        release.set()
        session.close()
        worker.join(3)


def test_monitor_keeps_new_messages_during_ai_and_refreshes_before_action_ends():
    entered, release = threading.Event(), threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            if not entered.is_set():
                entered.set()
                assert release.wait(6)
            return super().stream_chat(*args, **kwargs)

    provider = SlowProvider()
    session, script, win, backend, _, _ = background_session(provider, .5)
    ocr = session._platform.ocr_engine
    ocr._boxes = [[TextBox(f"朋友[CH.301]>>{text}", 0, 0, 85, 20, .99)]
                  for text in ("早安", "你好", "還在嗎")]
    try:
        session(script, win)  # The only boundary until both AI requests finish.
        assert entered.wait(2)
        eventually(lambda: any(m.text == "還在嗎" for m in session._observer.history), 2)
        assert not backend.calls
        release.set()
        eventually(lambda: len(provider.calls) == 2)
        payload = json.loads(provider.calls[1][0][0]["content"])
        assert [m["text"] for m in payload["new_messages"]] == ["你好", "還在嗎"]
        assert not backend.calls
        eventually(lambda: session._ai_result.done())
        session(script, win)
        assert [c[1] for c in backend.calls].count("收到，謝謝") == 1
    finally:
        release.set()
        session.close()


@pytest.mark.parametrize("phase", ["ocr", "ai"])
@pytest.mark.parametrize("operation", ["stop", "close", "suspend"])
def test_monitor_cancels_without_waiting_for_slow_work_or_typing_late(phase, operation):
    entered, release = threading.Event(), threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            if phase == "ai":
                entered.set()
                assert release.wait(5)
            return super().stream_chat(*args, **kwargs)

    session, script, win, backend, _, stop = background_session(SlowProvider(), .5)
    recognize = session._platform.ocr_engine.recognize

    def read(image):
        entered.set()
        assert release.wait(5)
        return recognize(image)

    if phase == "ocr":
        session._platform.ocr_engine.recognize = read
    try:
        session(script, win)
        assert entered.wait(2)
        started = time.monotonic()
        if operation == "stop":
            stop.set()
        else:
            getattr(session, operation)()
        assert time.monotonic() - started < .3
        release.set()
        session(script, win)
        if operation != "suspend":
            session._monitor.join(.3)
            assert not session._monitor.is_alive()
        eventually(lambda: session._pending is None or not session._pending.is_alive())
        assert not backend.calls
        if operation == "suspend":
            assert not session._observer.history or phase == "ai"
            session.resume()
            assert not session._observer.history
    finally:
        release.set()
        stop.set()
        session.close()


def test_slow_monitor_scan_does_not_overlap_or_delay_loop_keys_and_stop():
    session, _, win, backend, _, stop = background_session(interval=.5)
    entered, release, kept_playing = (threading.Event() for _ in range(3))
    scans = 0

    def read(_):
        nonlocal scans
        scans += 1
        entered.set()
        assert release.wait(5)
        return []

    press = backend.key_press

    def key(*args):
        press(*args)
        if entered.is_set():
            kept_playing.set()

    session._platform.ocr_engine.recognize = read
    backend.key_press = key
    script = script_from_dict({"name": "loop", "target_window": {"title_pattern": win.title},
                               "actions": [{"type": "loop", "count": -1, "actions": [
                                   {"type": "key_press", "key": "a"},
                                   {"type": "delay", "ms": 10}]}]})
    player = Player(session._platform, stop_event=stop, on_action_boundary=session)
    worker = threading.Thread(target=player.play, args=(script,))
    worker.start()
    try:
        assert entered.wait(1)
        assert kept_playing.wait(.3)
        # Multiple checks become due while native OCR remains blocked.
        time.sleep(1.1)
        assert scans == 1
        stop.set()
        worker.join(.3)
        assert not worker.is_alive()
    finally:
        stop.set()
        release.set()
        session.close()
        worker.join(3)


def test_background_monitor_never_activates_or_reads_another_foreground_window():
    session, script, win, backend, _, _ = background_session(interval=.5)
    wm = session._platform.window_manager
    win = replace(win, is_active=False)
    wm.windows[:] = [win]
    try:
        session(script, win)
        time.sleep(.7)
        assert not session._platform.screen_capture.captures
        assert not session._provider.calls
        assert not wm.activated
        assert not backend.calls
    finally:
        session.close()


def test_ready_reply_is_not_postponed_another_action_by_monitor_state_lock():
    session, script, win, backend, _, _ = background_session(interval=.5)
    entered, release, boundary_done = (threading.Event() for _ in range(3))
    observe = session._observer.observe
    observed = 0

    def read_messages(*args):
        nonlocal observed
        observed += 1
        if observed == 3:
            entered.set()
            assert release.wait(5)
        return observe(*args)

    session._observer.observe = read_messages

    def boundary():
        try:
            session(script, win)
        finally:
            boundary_done.set()

    worker = threading.Thread(target=boundary)
    try:
        session(script, win)
        eventually(lambda: session._ai_result is not None and session._ai_result.done())
        assert entered.wait(2)
        worker.start()
        assert not boundary_done.wait(.1), "Ready reply must not skip this boundary"
        release.set()
        assert boundary_done.wait(6)
        assert ("type_text", "收到，謝謝") in backend.calls
    finally:
        release.set()
        session.close()
        if worker.ident is not None:
            worker.join(3)


@pytest.mark.parametrize("response", ["empty", "error"])
def test_ai_without_reply_never_waits_for_in_flight_ocr_at_action_boundary(response):
    def respond(_):
        if response == "error":
            raise RuntimeError("provider unavailable")
        return {"replies": []}

    session, script, win, backend, _, _ = background_session(Provider(respond), .5)
    entered, release, boundary_done = (threading.Event() for _ in range(3))
    recognize = session._platform.ocr_engine.recognize
    scans = 0

    def read(image):
        nonlocal scans
        scans += 1
        if scans == 3:
            entered.set()
            assert release.wait(5)
        return recognize(image)

    session._platform.ocr_engine.recognize = read

    def boundary():
        try:
            session(script, win)
        finally:
            boundary_done.set()

    worker = threading.Thread(target=boundary)
    try:
        session(script, win)
        eventually(lambda: session._ai_result is not None and session._ai_result.done())
        assert entered.wait(2)
        worker.start()
        assert boundary_done.wait(.3), "No reply must not pause the next script action"
        assert not backend.calls
    finally:
        release.set()
        session.close()
        if worker.ident is not None:
            worker.join(3)


def test_player_typing_nonstop_still_gets_a_reply_after_two_refreshes():
    # 實機：對方每 2 秒一句、AI 每次 3～4 秒，每句都重算就永遠停在「處理中」。
    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            threading.Event().wait(.3)
            return super().stream_chat(*args, **kwargs)

    provider = SlowProvider()
    session, script, win, backend, _, _ = background_session(provider, .05)
    count = iter(range(10_000))

    def recognize(_):
        n = next(count)
        text = chr(0x4e00 + n * 37 % 20000) + chr(0x5e00 + n * 91 % 9000)
        return [TextBox(f"朋友[CH.301]>>{text}", 0, 0, 85, 20, .99)]

    session._platform.ocr_engine.recognize = recognize
    try:
        session(script, win)
        deadline = time.monotonic() + 8
        while "收到，謝謝" not in [c[1] for c in backend.calls]:
            assert time.monotonic() < deadline, f"{len(provider.calls)} AI calls, never sent"
            session(script, win)
            threading.Event().wait(.05)
        assert len(provider.calls) <= 4
    finally:
        session.close()


def test_new_whisper_is_reread_quickly_to_confirm_name_before_spam_pushes_it_out():
    session, script, win, _, _, _ = background_session(interval=3)
    times = []
    recognize = session._platform.ocr_engine.recognize

    def read(image):
        times.append(time.monotonic())
        return recognize(image)

    session._platform.ocr_engine.recognize = read
    try:
        session(script, win)
        # 第 1 張是基準、第 2 張（3 秒後）出現新密語，第 3 張要馬上再讀。
        eventually(lambda: len(times) >= 3, 5)
        assert times[1] - times[0] > 2.5
        assert times[2] - times[1] < 1, "設定每 3 秒掃描，新密語後仍要 0.3 秒內再讀"
    finally:
        session.close()
