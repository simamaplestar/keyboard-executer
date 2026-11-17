import pytest

from keyboard_executor.core.models import (
    Script,
    ScriptValidationError,
    script_from_dict,
    script_to_dict,
)


def minimal(**overrides):
    data = {
        "name": "測試腳本",
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}],
    }
    data.update(overrides)
    return data


def test_minimal_script_with_defaults():
    s = script_from_dict(minimal())
    assert isinstance(s, Script)
    assert s.name == "測試腳本"
    assert s.target_window.title_pattern == "記事本"
    assert s.target_window.app_name is None
    assert (s.settings.speed, s.settings.repeat) == (1.0, 1)
    assert s.settings.humanize_jitter_pct == 0
    assert s.settings.game_input_mode is True
    assert s.settings.window_message_mode is False
    assert s.settings.scan_pulse_mode is False
    assert (s.settings.window_retry, s.settings.window_retry_interval_ms) == (0, 1000)
    assert len(s.actions) == 1


def test_name_required_and_no_path_separators():
    with pytest.raises(ScriptValidationError, match="name"):
        script_from_dict(minimal(name=""))
    with pytest.raises(ScriptValidationError, match="name"):
        script_from_dict(minimal(name="a/b"))


def test_target_window_needs_at_least_one_condition():
    with pytest.raises(ScriptValidationError, match="target_window"):
        script_from_dict(minimal(target_window={}))


def test_target_window_invalid_regex_raises():
    with pytest.raises(ScriptValidationError, match="regex"):
        script_from_dict(minimal(target_window={"title_pattern": "["}))


def test_target_window_app_name_only_is_ok():
    s = script_from_dict(minimal(target_window={"app_name": "Notepad"}))
    assert s.target_window.app_name == "Notepad"
    assert s.target_window.title_pattern is None


def test_actions_must_be_nonempty():
    with pytest.raises(ScriptValidationError, match="actions"):
        script_from_dict(minimal(actions=[]))


def test_settings_validation():
    with pytest.raises(ScriptValidationError, match="speed"):
        script_from_dict(minimal(settings={"speed": 0}))
    with pytest.raises(ScriptValidationError, match="repeat"):
        script_from_dict(minimal(settings={"repeat": 0}))
    with pytest.raises(ScriptValidationError, match="humanize_jitter_pct"):
        script_from_dict(minimal(settings={"humanize_jitter_pct": 101}))
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        script_from_dict(minimal(settings={"speeed": 2}))


def test_settings_repeat_minus_one_is_infinite():
    s = script_from_dict(minimal(settings={"repeat": -1}))
    assert s.settings.repeat == -1


def test_unknown_top_level_field_raises():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        script_from_dict(minimal(extra=1))


def test_round_trip():
    data = minimal(settings={"speed": 2.0, "repeat": 3, "humanize_jitter_pct": 10})
    assert script_to_dict(script_from_dict(data)) == {
        "name": "測試腳本",
        "target_window": {"title_pattern": "記事本", "app_name": None},
        "settings": {"speed": 2.0, "repeat": 3, "humanize_jitter_pct": 10,
                     "game_input_mode": True,
                     "window_message_mode": False,
                     "scan_pulse_mode": False,
                     "window_retry": 0, "window_retry_interval_ms": 1000,
                     "hotkey": ""},
        "actions": [{"type": "key_press", "key": "a", "hold_ms": 0}],
    }


def test_unknown_field_messages_are_wellformed():
    with pytest.raises(ScriptValidationError, match="^腳本 不支援的欄位: extra$"):
        script_from_dict(minimal(extra=1))
    with pytest.raises(ScriptValidationError, match="^target_window 不支援的欄位: bogus$"):
        script_from_dict(minimal(target_window={"title_pattern": "x", "bogus": 1}))
    with pytest.raises(ScriptValidationError, match="^settings 不支援的欄位: speeed$"):
        script_from_dict(minimal(settings={"speeed": 2}))


def test_target_window_blank_strings_normalized_to_none():
    s = script_from_dict(minimal(target_window={"title_pattern": "   ", "app_name": "Notepad"}))
    assert s.target_window.title_pattern is None
    assert s.target_window.app_name == "Notepad"
    s2 = script_from_dict(minimal(target_window={"title_pattern": "記事本", "app_name": ""}))
    assert s2.target_window.app_name is None


def test_target_window_blank_both_still_raises():
    with pytest.raises(ScriptValidationError, match="至少要提供"):
        script_from_dict(minimal(target_window={"title_pattern": " ", "app_name": ""}))


def test_settings_window_retry_validation():
    with pytest.raises(ScriptValidationError, match="window_retry"):
        script_from_dict(minimal(settings={"window_retry": -1}))
    with pytest.raises(ScriptValidationError, match="window_retry"):
        script_from_dict(minimal(settings={"window_retry": True}))


def test_settings_window_retry_interval_validation():
    with pytest.raises(ScriptValidationError, match="window_retry_interval_ms"):
        script_from_dict(minimal(settings={"window_retry_interval_ms": -1}))
    with pytest.raises(ScriptValidationError, match="window_retry_interval_ms"):
        script_from_dict(minimal(settings={"window_retry_interval_ms": 1.5}))


def test_game_input_mode_explicit_false_respected():
    data = minimal()
    data["settings"] = {"game_input_mode": False}
    assert script_from_dict(data).settings.game_input_mode is False


def test_window_message_mode_round_trip_and_is_mutually_exclusive_with_game_mode():
    data = minimal(settings={"game_input_mode": False, "window_message_mode": True})
    script = script_from_dict(data)
    assert script.settings.window_message_mode is True
    assert script_to_dict(script)["settings"]["window_message_mode"] is True

    with pytest.raises(ScriptValidationError, match="不能同時"):
        script_from_dict(minimal(settings={
            "game_input_mode": True, "window_message_mode": True}))


def test_window_message_mode_must_be_boolean():
    with pytest.raises(ScriptValidationError, match="window_message_mode"):
        script_from_dict(minimal(settings={"window_message_mode": "yes"}))


def test_scan_pulse_mode_round_trip_and_is_mutually_exclusive():
    data = minimal(settings={"scan_pulse_mode": True})
    script = script_from_dict(data)
    assert script.settings.game_input_mode is False
    assert script.settings.window_message_mode is False
    assert script.settings.scan_pulse_mode is True
    assert script_to_dict(script)["settings"]["scan_pulse_mode"] is True

    with pytest.raises(ScriptValidationError, match="不能同時"):
        script_from_dict(minimal(settings={
            "game_input_mode": False,
            "window_message_mode": True,
            "scan_pulse_mode": True,
        }))


def test_scan_pulse_mode_must_be_boolean():
    with pytest.raises(ScriptValidationError, match="scan_pulse_mode"):
        script_from_dict(minimal(settings={"scan_pulse_mode": "yes"}))


def test_settings_hotkey_default_empty():
    assert script_from_dict(minimal()).settings.hotkey == ""


def test_settings_hotkey_accepts_single_and_combo():
    assert script_from_dict(minimal(settings={"hotkey": "f5"})).settings.hotkey == "f5"
    assert script_from_dict(
        minimal(settings={"hotkey": "ctrl+shift+1"})).settings.hotkey == "ctrl+shift+1"
    assert script_from_dict(minimal(settings={"hotkey": "  "})).settings.hotkey == ""  # 空＝不設


def test_settings_hotkey_rejects_bad_key_and_type():
    with pytest.raises(ScriptValidationError, match="hotkey"):
        script_from_dict(minimal(settings={"hotkey": "ctrl+nope"}))
    with pytest.raises(ScriptValidationError, match="hotkey"):
        script_from_dict(minimal(settings={"hotkey": 5}))


def test_key_combo_hold_ms_default_and_validation():
    from keyboard_executor.core.models import action_from_dict, action_label
    a = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"]})
    assert a.params["hold_ms"] == 0
    a2 = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000})
    assert a2.params["hold_ms"] == 2000
    assert action_label(a2) == "組合鍵 ctrl+s（按住 2000ms）"
    assert action_label(a) == "組合鍵 ctrl+s"
    with pytest.raises(ScriptValidationError, match="hold_ms"):
        action_from_dict({"type": "key_combo", "keys": ["a"], "hold_ms": -1})
    with pytest.raises(ScriptValidationError, match="hold_ms"):
        action_from_dict({"type": "key_combo", "keys": ["a"], "hold_ms": 1.5})
