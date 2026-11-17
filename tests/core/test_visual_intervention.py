import threading
from types import SimpleNamespace
import pytest
from keyboard_executor.core.models import script_from_dict, action_from_dict
from keyboard_executor.core.player import Player
from tests.core.test_player_flow import make_platform, make_script, DictStorage
from tests.core.test_sequence_input_config import script_data


def test_enabled_requires_actual_runtime_capability():
    platform, backend = make_platform()
    result = Player(platform, on_action_boundary=lambda *_: None).play(script_from_dict(script_data()))
    assert not result.ok
    assert "圖片順序輸入" in result.error
    assert not backend.calls


def test_takeover_during_chat_finishes_before_next_script_action():
    from keyboard_executor.core.visual_intervention import VisualIntervention
    platform, backend = make_platform()
    requested = threading.Event()
    events = []
    class Chat:
        def set_input_preempted(self, check): self.check = check
        def __call__(self, *args):
            events.append("chat")
            requested.set()
        def suspend(self): events.append("suspend")
        def resume(self): events.append("resume")
        def close(self): pass
    watcher = SimpleNamespace(requested=requested, start=lambda _: None,
        snapshot=lambda: SimpleNamespace(round_id=1), rearm=lambda _: requested.clear(), close=lambda: None)
    def submit(win):
        events.append("submit")
        backend.type_text("HDP")
        return True
    runtime = VisualIntervention(watcher, SimpleNamespace(run=submit), Chat())
    child = make_script([{"type":"key_press","key":"b"}], name="child")
    main = make_script([{"type":"loop","count":2,"actions":[{"type":"run_script","script_name":"child"}]}])
    result = Player(platform, storage=DictStorage([child]), on_action_boundary=runtime).play(main)
    assert result.ok
    assert [c[1] for c in backend.calls if c[0] == "key_press"] == ["b","b"]
    assert events[:4] == ["chat","suspend","submit","resume"]


def test_interrupted_chat_draft_stops_after_sequence_instead_of_typing_game_keys():
    from keyboard_executor.core.visual_intervention import VisualIntervention
    platform, backend = make_platform()
    stop, requested = threading.Event(), threading.Event()
    requested.set()
    chat = SimpleNamespace(set_input_preempted=lambda _: None, suspend=lambda: None,
                           can_resume_after_intervention=False)
    watcher = SimpleNamespace(requested=requested, start=lambda _: None,
        snapshot=lambda: SimpleNamespace(round_id=1), fail=lambda _: stop.set())
    runtime = VisualIntervention(watcher, SimpleNamespace(run=lambda _: True), chat)
    result = Player(platform, stop_event=stop, on_action_boundary=runtime).play(
        make_script([{"type":"key_press","key":"z"}]))
    assert not result.ok and stop.is_set()
    assert backend.calls == []


def test_chat_preempt_after_text_cannot_send_enter_or_restore_focus():
    from tests.core.test_chat_reply import make_session
    from keyboard_executor.core.ai.provider import AiAborted
    session, _, win, backend, _, _, _ = make_session()
    requested = threading.Event()
    session.set_input_preempted(requested.is_set)
    original = backend.type_text_literal
    def type_and_preempt(text):
        original(text)
        requested.set()
    backend.type_text_literal = type_and_preempt
    actions = [action_from_dict({"type":"text_input","text":"{reply}"}),
               action_from_dict({"type":"key_press","key":"enter"})]
    try:
        with pytest.raises(AiAborted): session._send(actions, win, "draft", "friend")
        count = len(session._platform.window_manager.activated)
        session._restore_window(win)
        assert len(session._platform.window_manager.activated) == count
        assert not any(c[:2] == ("key_press", "enter") for c in backend.calls)
        assert not session.can_resume_after_intervention
        session.suspend()
        requested.clear()
        session.resume()
        assert session._scan is None and session._ai_result is None
        assert session._observer.history == []
    finally:
        session.close()
