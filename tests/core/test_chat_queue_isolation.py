"""Pending players cannot evict each other or bypass a same-player refresh."""
import json
import threading

import pytest

from keyboard_executor.core.chat_observer import ChatMessage
from tests.core.test_chat_observer import frame
from tests.core.test_chat_reply import Provider, close_sessions, make_session
from tests.core.test_chat_reply_monitor import background_session, eventually


@pytest.mark.parametrize("background", [False, True], ids=["action-boundary", "background"])
def test_busy_player_cannot_evict_another_players_pending_request(background):
    provider = Provider(lambda _: {"replies": []})
    if background:
        session, script, win, backend, _, stop = background_session(provider)
        queued = lambda: session._queued_messages
    else:
        session, script, win, backend, _, _, stop = make_session(provider)
        queued = lambda: session._deferred_messages
    try:
        waiting = ChatMessage(1, "whisper", "乙", "請記得回我")
        session._defer_messages(None, [waiting])
        # The cap combines both channels and normalized forms of this one
        # player's name, while preserving another player's pending position.
        burst = [ChatMessage(index + 2, "map" if index % 2 else "whisper",
                             "Ａ" if index % 2 else "A", f"第{index}句")
                 for index in range(61)]
        session._defer_messages(None, burst)
        assert queued()[0] == waiting
        assert len(queued()) == 51
        assert [message.text for message in queued()[1:]] == [f"第{i}句" for i in range(11, 61)]
        session._defer_messages(None, [waiting])
        assert sum(message.id == waiting.id for message in queued()) == 1

        if background:
            session._refresh_ai()
        else:
            session(script, win)
        session._ai_result.result(timeout=2)
        data = json.loads(provider.calls[0][0][0]["content"])
        assert data["conversation_with"] == "乙"
        assert [message["id"] for message in data["new_messages"]] == [1]
        assert not backend.calls
    finally:
        stop.set()
        session.close()


def test_ready_reply_waits_for_same_player_update_while_prepare_thread_exits(monkeypatch):
    provider_entered, release_provider = threading.Event(), threading.Event()
    published, release_prepare = threading.Event(), threading.Event()

    class WaitingProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            provider_entered.set()
            assert release_provider.wait(4)
            return super().stream_chat(*args, **kwargs)

    provider = WaitingProvider(lambda data: {"replies": [
        {"message_id": data["new_messages"][-1]["id"], "text": "最新的回答"}]})
    session, script, win, backend, _, stop = background_session(provider)
    try:
        session._window = win  # Exercise the boundary without starting a monitor thread.
        session._observer.observe(*frame(("甲[CH.301]>>舊背景", "green")))
        first_image, first_boxes = frame(("甲[CH.301]>>第一個問題", "green"))
        first = session._observer.observe(first_image, first_boxes)
        session._on_chat_messages(first_image, first)
        session._refresh_ai()
        assert provider_entered.wait(1)
        ready = session._ai_result
        publish = ready.set_result

        def hold_after_publish(value):
            publish(value)
            published.set()
            assert release_prepare.wait(4)

        monkeypatch.setattr(ready, "set_result", hold_after_publish)
        release_provider.set()
        assert published.wait(2)
        second_image, second_boxes = frame(("甲[CH.301]>>補充的問題", "green"))
        second = session._observer.observe(second_image, second_boxes)
        session._on_chat_messages(second_image, second)
        sent = []
        # Delivery's final OCR sees the already-observed update. The pending
        # queue must retain its meaning after observer deduplication.
        monkeypatch.setattr(session, "_read_frame", lambda _: (second_image, second_boxes))
        monkeypatch.setattr(session, "_send_replies",
                            lambda replies, _: sent.extend((m.text, text) for m, text in replies))

        session(script, win)
        assert sent == []
        assert not backend.calls
        assert session._ai_result is ready

        release_prepare.set()
        eventually(lambda: not session._prepare_worker.is_alive())
        session._refresh_ai()
        session._ai_result.result(timeout=2)
        eventually(lambda: not session._prepare_worker.is_alive())
        session(script, win)
        assert sent == [("補充的問題", "最新的回答")]
        assert len(provider.calls) == 2
        updated = json.loads(provider.calls[1][0][0]["content"])
        assert [m["text"] for m in updated["new_messages"]] == ["第一個問題", "補充的問題"]
    finally:
        release_prepare.set()
        release_provider.set()
        stop.set()
        session.close()
