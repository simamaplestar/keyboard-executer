import threading

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from tests.core.test_player_flow import DictStorage, make_platform, make_script


def test_chat_insertion_preserves_loop_and_child_script_position():
    platform, backend = make_platform()
    child = make_script([{"type": "key_press", "key": "b"},
                         {"type": "key_press", "key": "c"}], name="子")
    main = make_script([
        {"type": "loop", "count": 2, "actions": [
            {"type": "key_press", "key": "a"},
            {"type": "run_script", "script_name": "子"}]},
        {"type": "key_press", "key": "d"}])
    sent = False

    def chat(script, win):
        nonlocal sent
        if not sent and any(c[:2] == ("key_press", "b") for c in backend.calls):
            backend.type_text("回覆")
            sent = True

    result = Player(platform, storage=DictStorage([child]),
                    on_action_boundary=chat).play(main)
    assert result.ok
    assert [c[1] for c in backend.calls] == ["a", "b", "回覆", "c", "a", "b", "c", "d"]


def test_chat_boundary_happens_after_held_key_is_released():
    platform, backend = make_platform()
    script = make_script([{"type": "key_press", "key": "a", "hold_ms": 200},
                          {"type": "key_press", "key": "b"}])

    def chat(script, win):
        if backend.calls:
            assert backend.calls[-1] == ("key_up", "a")
            backend.type_text("回覆")

    assert Player(platform, sleep=lambda _: None, on_action_boundary=chat).play(script).ok
    assert [c[0] for c in backend.calls] == ["key_down", "key_up", "type_text", "key_press"]


def test_stop_during_chat_does_not_execute_next_action():
    platform, backend = make_platform()
    stop = threading.Event()
    result = Player(platform, stop_event=stop,
                    on_action_boundary=lambda *_: stop.set()).play(
                        make_script([{"type": "key_press", "key": "a"}]))
    assert not result.ok
    assert backend.calls == []


def test_chat_resumes_second_level_loop_without_resetting_either_counter():
    platform, backend = make_platform()
    script = make_script([{"type": "loop", "count": 2, "actions": [
        {"type": "key_press", "key": "a"},
        {"type": "loop", "count": 2, "actions": [{"type": "key_press", "key": "b"}]},
        {"type": "key_press", "key": "c"}]}])
    sent = False

    def chat(*_):
        nonlocal sent
        if not sent and [c[1] for c in backend.calls] == ["a", "b"]:
            backend.type_text("回覆")
            sent = True

    assert Player(platform, on_action_boundary=chat).play(script).ok
    assert [c[1] for c in backend.calls] == ["a", "b", "回覆", "b", "c", "a", "b", "b", "c"]


def test_child_chat_without_main_service_explains_configuration_scope():
    from tests.core.test_chat_reply_config import config_data, script_data
    platform, backend = make_platform()
    child = script_from_dict(script_data(config_data()))
    parent = make_script([{"type": "run_script", "script_name": child.name}])
    result = Player(platform, storage=DictStorage([child])).play(parent)
    assert not result.ok
    assert "主腳本" in result.error
    assert "子腳本沿用" in result.error
    assert not backend.calls


def test_both_chat_channels_disabled_can_play_without_chat_service():
    from tests.core.test_chat_reply_config import script_data
    platform, backend = make_platform()
    data = script_data({"enabled": True, "reply_map": False, "reply_whisper": False})
    data["target_window"]["title_pattern"] = "記事本"
    result = Player(platform).play(script_from_dict(data))
    assert result.ok
    assert [c[1] for c in backend.calls] == ["a"]
