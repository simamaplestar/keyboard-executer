"""慢速 OCR 不得拖住播放器啟動、迴圈或停止。"""
import threading

import pytest

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from tests.core.test_chat_reply import Provider, make_session


@pytest.mark.parametrize("blocked_scan", [1, 2], ids=["cold-start", "loop-poll"])
@pytest.mark.parametrize("operation", ["keep-playing", "stop"])
def test_slow_chat_ocr_does_not_block_player(blocked_scan, operation):
    session, _, win, backend, _, clock, stop = make_session()
    entered, release, key_after_scan = (threading.Event() for _ in range(3))
    scans = 0

    def recognize(_):
        nonlocal scans
        scans += 1
        if scans == blocked_scan:
            entered.set()
            assert release.wait(5)
        return []

    session._platform.ocr_engine.recognize = recognize
    original_press = backend.key_press

    def press(*args, **kwargs):
        original_press(*args, **kwargs)
        clock[0] += 4
        if entered.is_set():
            key_after_scan.set()

    backend.key_press = press
    script = script_from_dict({
        "name": "慢速聊天辨識", "target_window": {"title_pattern": win.title},
        "actions": [{"type": "loop", "count": -1, "actions": [
            {"type": "key_press", "key": "a"}, {"type": "delay", "ms": 5}]}],
    })
    player = Player(session._platform, stop_event=stop, on_action_boundary=session)
    worker = threading.Thread(target=player.play, args=(script,))
    worker.start()
    try:
        assert entered.wait(2), "必須真的執行到被卡住的 OCR"
        if operation == "keep-playing":
            assert key_after_scan.wait(.3), "OCR 尚未完成時，腳本仍應持續執行"
        else:
            stop.set()
            worker.join(.3)
            assert not worker.is_alive(), "停止不應等待 OCR 完成"
    finally:
        stop.set()
        release.set()
        worker.join(3)


def test_script_keeps_playing_until_background_reply_is_ready():
    entered, release, key_after_wait, sent = (threading.Event() for _ in range(4))

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().stream_chat(*args, **kwargs)

    provider = SlowProvider()
    session, _, win, backend, _, clock, stop = make_session(provider)
    press, type_text = backend.key_press, backend.type_text
    input_threads = []

    def key_press(*args, **kwargs):
        press(*args, **kwargs)
        clock[0] += 4
        if entered.is_set():
            key_after_wait.set()

    def reply(text):
        input_threads.append(threading.get_ident())
        type_text(text)
        if text == "收到，謝謝":
            sent.set()

    backend.key_press, backend.type_text = key_press, reply
    script = script_from_dict({
        "name": "背景產生回覆", "target_window": {"title_pattern": win.title},
        "actions": [{"type": "loop", "count": -1, "actions": [
            {"type": "key_press", "key": "a"}, {"type": "delay", "ms": 5}]}],
    })
    player = Player(session._platform, stop_event=stop, on_action_boundary=session)
    worker = threading.Thread(target=player.play, args=(script,))
    worker.start()
    try:
        assert entered.wait(2), "必須真的到達慢速 AI"
        assert key_after_wait.wait(.3), "等待回覆準備時，腳本仍應持續按鍵"
        assert not sent.is_set()
        release.set()
        assert sent.wait(2)
        assert len(provider.calls) == 1
        assert input_threads and set(input_threads) == {worker.ident}
    finally:
        stop.set()
        release.set()
        session.close()
        worker.join(3)
