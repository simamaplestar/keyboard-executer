import pytest

from keyboard_executor.app.script_editor_model import ScriptEditorModel
from keyboard_executor.core.models import (
    ScriptValidationError,
    script_from_dict,
    script_to_dict,
)


def make_script():
    return script_from_dict({
        "name": "編輯我", "target_window": {"title_pattern": "記事本"},
        "settings": {"speed": 2.0, "repeat": 3},
        "actions": [{"type": "key_press", "key": "a"},
                    {"type": "delay", "ms": 100},
                    {"type": "mouse_click", "x": 5, "y": 6}]})


def test_rows_reflect_script_with_labels():
    model = ScriptEditorModel(make_script())
    rows = model.rows()
    assert [r["type"] for r in rows] == ["key_press", "delay", "mouse_click"]
    assert rows[0]["label"] == "按鍵 a"
    assert len(model) == 3


def test_insert_valid_action_at_index():
    model = ScriptEditorModel(make_script())
    model.insert(1, {"type": "text_input", "text": "哈囉"})
    assert [r["type"] for r in model.rows()] == [
        "key_press", "text_input", "delay", "mouse_click"]


def test_insert_invalid_action_raises_and_keeps_state():
    model = ScriptEditorModel(make_script())
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        model.insert(0, {"type": "fly"})
    with pytest.raises(ScriptValidationError, match="缺少欄位"):
        model.insert(0, {"type": "key_press"})
    assert len(model) == 3


def test_update_invalid_keeps_original():
    model = ScriptEditorModel(make_script())
    with pytest.raises(ScriptValidationError):
        model.update(0, {"type": "key_press", "key": "不是按鍵名稱"})
    assert model.action_at(0) == {"type": "key_press", "key": "a", "hold_ms": 0}
    model.update(0, {"type": "key_press", "key": "b"})
    assert model.action_at(0)["key"] == "b"


def test_remove_and_duplicate():
    model = ScriptEditorModel(make_script())
    model.duplicate(0)
    assert [r["type"] for r in model.rows()] == [
        "key_press", "key_press", "delay", "mouse_click"]
    model.remove(1)
    assert len(model) == 3


def test_move_up_down_with_bounds():
    model = ScriptEditorModel(make_script())
    assert model.move(2, -1) == 1
    assert [r["type"] for r in model.rows()] == ["key_press", "mouse_click", "delay"]
    assert model.move(0, -1) == 0            # 上邊界夾住
    assert model.move(2, +5) == 2            # 下邊界夾住
    assert model.move(0, +1) == 1
    assert [r["type"] for r in model.rows()] == ["mouse_click", "key_press", "delay"]


def test_to_script_round_trip():
    original = make_script()
    model = ScriptEditorModel(original)
    model.insert(len(model), {"type": "wait_text", "pattern": "完成"})
    rebuilt = model.to_script()
    assert rebuilt.name == "編輯我"
    assert rebuilt.settings.speed == 2.0 and rebuilt.settings.repeat == 3
    assert len(rebuilt.actions) == 4
    # 前三個動作與原腳本完全一致（round-trip 不變形）
    assert script_to_dict(rebuilt)["actions"][:3] == script_to_dict(original)["actions"]


def test_every_action_type_accepted():
    samples = [
        {"type": "key_press", "key": "a"},
        {"type": "key_combo", "keys": ["ctrl", "s"]},
        {"type": "text_input", "text": "哈囉"},
        {"type": "mouse_move", "x": 1, "y": 2},
        {"type": "mouse_click", "x": 1, "y": 2},
        {"type": "mouse_drag", "from": [0, 0], "to": [5, 5]},
        {"type": "scroll", "x": 1, "y": 2, "dy": -3},
        {"type": "delay", "ms": 100},
        {"type": "loop", "count": 2, "actions": [{"type": "delay", "ms": 1}]},
        {"type": "run_script", "script_name": "子腳本"},
        {"type": "wait_text", "pattern": "好"},
        {"type": "wait_image", "template": "鈕"},
        {"type": "if_text", "pattern": "好", "then": [{"type": "delay", "ms": 1}]},
        {"type": "if_image", "template": "鈕", "then": [{"type": "delay", "ms": 1}]},
        {"type": "click_text", "pattern": "好"},
        {"type": "click_image", "template": "鈕"},
    ]
    model = ScriptEditorModel(make_script())
    for action in samples:
        model.insert(len(model), action)
    assert len(model) == 3 + 16
    assert model.to_script()                 # 整份仍通過權威驗證


def test_set_name_and_empty_name_rejected_on_to_script():
    model = ScriptEditorModel(make_script())
    model.set_name("另存名")
    assert model.to_script().name == "另存名"
    model.set_name("  ")
    with pytest.raises(ScriptValidationError, match="name"):
        model.to_script()


def test_new_script_defaults_to_game_input_mode():
    assert ScriptEditorModel.new("g").game_input_mode is True
    assert ScriptEditorModel.new("g").input_mode == "game"


def test_set_game_input_mode_writes_settings():
    model = ScriptEditorModel.new("g")
    model.set_target("Test", "")
    model.insert(0, {"type": "delay", "ms": 100})
    model.set_game_input_mode(False)
    assert model.game_input_mode is False
    assert model.to_script().settings.game_input_mode is False


def test_set_input_mode_supports_all_four_modes():
    model = ScriptEditorModel.new("g")
    model.set_target("Test", "")
    model.insert(0, {"type": "delay", "ms": 100})

    model.set_input_mode("window_message")
    assert model.input_mode == "window_message"
    assert model.game_input_mode is False
    assert model.to_script().settings.window_message_mode is True

    model.set_input_mode("normal")
    assert model.input_mode == "normal"
    assert model.to_script().settings.window_message_mode is False

    model.set_input_mode("game")
    assert model.input_mode == "game"
    assert model.game_input_mode is True

    model.set_input_mode("scan_pulse")
    assert model.input_mode == "scan_pulse"
    settings = model.to_script().settings
    assert settings.game_input_mode is False
    assert settings.window_message_mode is False
    assert settings.scan_pulse_mode is True


def test_new_script_hotkey_defaults_empty():
    assert ScriptEditorModel.new("g").hotkey == ""


def test_set_hotkey_writes_settings():
    model = ScriptEditorModel.new("g")
    model.set_target("Test", "")
    model.insert(0, {"type": "delay", "ms": 100})
    model.set_hotkey("ctrl+shift+a")
    assert model.hotkey == "ctrl+shift+a"
    assert model.to_script().settings.hotkey == "ctrl+shift+a"


def test_timed_keys_text_round_trip_and_validation():
    import pytest
    from keyboard_executor.app.script_editor_model import ScriptEditorModel
    from keyboard_executor.core.models import ScriptValidationError, TimedKey
    model = ScriptEditorModel.new("定時")
    model.set_target("", "msw.exe")
    model.set_timed_keys_text("1:120, 2:180:300")
    assert model.timed_keys_text == "1:120, 2:180:300"
    with pytest.raises(ScriptValidationError):
        model.set_timed_keys_text("1:abc")
    model.set_timed_keys_text("")
    assert model.timed_keys_text == ""
    model.set_timed_keys_text("3:60")
    model.insert(0, {"type": "delay", "ms": 0})
    assert model.to_script().settings.timed_keys == (TimedKey("3", 60.0),)
