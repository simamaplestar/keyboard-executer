"""A malformed AI answer gets one bounded correction before a whisper is lost."""
import json
import threading
import time
from dataclasses import replace

import pytest

from keyboard_executor.core.ai.provider import AiAborted, AiProviderError, ChatResult
from keyboard_executor.core.chat_observer import ChatMessage
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from tests.core.test_chat_reply import close_sessions, make_session, scan, trigger
from tests.core.test_chat_reply_monitor import background_session, eventually


VALID = '{"replies":[{"message_id":2,"text":"有喔"}]}'


class Answers:
    def __init__(self, *answers):
        self.answers = answers
        self.calls = []

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.calls.append({"payload": json.loads(messages[0]["content"]),
                           "image": [image["data"] for image in messages[0]["images"]],
                           "system": system, "should_abort": should_abort})
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if callable(answer):
            answer = answer()
        if isinstance(answer, Exception):
            raise answer
        return ChatResult(answer)


@pytest.mark.parametrize("first", [
    "PRIVATE_INVALID_ANSWER",
    '{"replies":[{"message_id":999,"text":"錯人"}]}',
    '{"replies":[{"message_id":2,"text":"第一則"},{"message_id":2,"text":"重複"}]}',
    '{"replies":[{"message_id":2,"text":"嗨","recipient":"別人"}]}',
])
def test_format_repair_keeps_candidate_and_history_then_sends_exactly_once(first):
    provider = Answers(first, VALID)
    session, script, win, backend, records, clock, _ = make_session(provider)
    trigger(session, script, win, clock)

    assert len(provider.calls) == 2
    assert [call[1] for call in backend.calls] == ["h", "enter", "有喔", "enter"]
    assert provider.calls[0]["payload"] == provider.calls[1]["payload"]
    assert provider.calls[0]["image"] == provider.calls[1]["image"]
    assert provider.calls[1]["payload"]["new_messages"] == [
        {"id": 2, "channel": "whisper", "sender": "朋友", "text": "你好", "incoming": True,
         "recipient": ""}]
    assert provider.calls[1]["payload"]["history"][0]["text"] == "早安"
    assert provider.calls[0]["system"] != provider.calls[1]["system"]
    assert "PRIVATE_INVALID_ANSWER" not in json.dumps(records, ensure_ascii=False)

    clock[0] = 8
    scan(session, script, win)
    assert len(provider.calls) == 2
    assert [call[1] for call in backend.calls].count("有喔") == 1


@pytest.mark.parametrize("second", [
    "STILL_INVALID",
    '{"replies":[{"message_id":999,"text":"錯人"}]}',
    '{"replies":[{"message_id":2,"text":"第一則"},{"message_id":2,"text":"重複"}]}',
    '{"replies":[{"message_id":2,"text":"/指令"}]}',
])
def test_second_invalid_answer_never_types_or_starts_a_third_request(second):
    provider = Answers("FIRST_INVALID", second)
    session, script, win, backend, records, clock, _ = make_session(provider)
    trigger(session, script, win, clock)
    clock[0] = 8
    scan(session, script, win)
    assert len(provider.calls) == 2
    assert not backend.calls
    assert any("本次未送出" in record["message"] for record in records)


@pytest.mark.parametrize("answer", [
    '{"replies":[]}', AiProviderError("連線失敗"), AiAborted(),
])
def test_skip_network_error_and_cancellation_do_not_trigger_format_repair(answer):
    provider = Answers(answer, VALID)
    session, script, win, backend, _, clock, _ = make_session(provider)
    trigger(session, script, win, clock)
    assert len(provider.calls) == 1
    assert not backend.calls


@pytest.mark.parametrize("operation", ["stop", "close", "suspend"])
def test_cancel_during_format_repair_discards_late_valid_reply(operation):
    entered, release = threading.Event(), threading.Event()

    def delayed_repair():
        entered.set()
        assert release.wait(3)
        return VALID

    provider = Answers("invalid", delayed_repair)
    session, script, win, backend, _, _, stop = make_session(provider)
    session._start_ai(session._platform.screen_capture.image,
                      [ChatMessage(2, "whisper", "朋友", "你好")])
    future = session._ai_result
    try:
        assert entered.wait(1)
        if operation == "stop":
            stop.set()
        else:
            getattr(session, operation)()
        assert future.result(timeout=.4) is None
        release.set()
        eventually(lambda: session._pending is None or not session._pending.is_alive())
        session(script, win)
        assert not backend.calls
        assert len(provider.calls) == 2
    finally:
        release.set()
        stop.set()
        session.close()


def test_format_repair_shares_original_timeout_instead_of_starting_a_new_budget():
    entered, release = threading.Event(), threading.Event()

    def first_answer():
        time.sleep(.65)
        return "invalid"

    def slow_repair():
        entered.set()
        assert release.wait(3)
        return VALID

    provider = Answers(first_answer, slow_repair)
    session, script, win, backend, _, _, stop = make_session(provider)
    session._config = replace(session._config, timeout_sec=1)
    started = time.monotonic()
    session._start_ai(session._platform.screen_capture.image,
                      [ChatMessage(2, "whisper", "朋友", "你好")])
    future = session._ai_result
    try:
        assert entered.wait(1)
        with pytest.raises(TimeoutError, match="AI 等待逾時"):
            future.result(timeout=1.25)
        assert .9 <= time.monotonic() - started < 1.4
        assert provider.calls[1]["should_abort"]()
        release.set()
        eventually(lambda: session._pending is None or not session._pending.is_alive())
        session(script, win)
        assert len(provider.calls) == 2 and not backend.calls
    finally:
        release.set()
        stop.set()
        session.close()


def test_player_continues_during_background_repair_and_only_delivers_valid_reply():
    repair_entered, repair_release = threading.Event(), threading.Event()
    action_entered, action_release = threading.Event(), threading.Event()

    def delayed_repair():
        repair_entered.set()
        assert repair_release.wait(5)
        return VALID

    provider = Answers("invalid", delayed_repair)
    session, _, win, backend, _, stop = background_session(provider, interval=.5)
    results = []

    def long_action(_):
        action_entered.set()
        assert action_release.wait(5)

    script = script_from_dict({"name": "背景修正", "target_window": {"title_pattern": win.title},
                               "actions": [{"type": "delay", "ms": 15000},
                                           {"type": "key_press", "key": "b"}]})
    player = Player(session._platform, stop_event=stop, sleep=long_action,
                    on_action_boundary=session)
    worker = threading.Thread(target=lambda: results.append(player.play(script)))
    worker.start()
    try:
        assert action_entered.wait(1)
        assert repair_entered.wait(2)
        assert worker.is_alive() and not backend.calls
        repair_release.set()
        eventually(lambda: session._ai_result is not None and session._ai_result.done())
        assert not backend.calls
        action_release.set()
        worker.join(3)
        assert not worker.is_alive() and results[0].ok
        assert [call[1] for call in backend.calls].count("有喔") == 1
        assert backend.calls[-1][1] == "b"
    finally:
        action_release.set()
        repair_release.set()
        stop.set()
        session.close()
        worker.join(3)
