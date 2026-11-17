import pytest

from keyboard_executor.app.action_fields import FIELD_SPECS, parse_int_list, to_action_dict
from keyboard_executor.core.models import (
    ActionType,
    ScriptValidationError,
    action_from_dict,
)


def test_field_specs_cover_every_action_type():
    assert set(FIELD_SPECS) == {str(t) for t in ActionType}


def test_to_action_dict_parses_ints_and_strings():
    action = to_action_dict("mouse_click", {"x": "10", "y": "20",
                                            "button": "right", "count": "2"})
    assert action == {"type": "mouse_click", "x": 10, "y": 20,
                      "button": "right", "count": 2}
    assert action_from_dict(action).params["count"] == 2


def test_to_action_dict_parses_point_region_ms_keys_and_json():
    drag = to_action_dict("mouse_drag", {"from": "1, 2", "to": "[3, 4]",
                                         "button": "left"})
    assert drag["from"] == [1, 2] and drag["to"] == [3, 4]
    wait = to_action_dict("wait_text", {"region": "5, 6, 30, 40", "pattern": "好",
                                        "mode": "contains", "timeout_ms": "",
                                        "on_timeout": "abort", "goto_index": ""})
    assert wait["region"] == [5, 6, 30, 40]
    delay = to_action_dict("delay", {"ms": "100, 300"})
    assert delay["ms"] == [100, 300]
    combo = to_action_dict("key_combo", {"keys": "ctrl+shift+s"})
    assert combo["keys"] == ["ctrl", "shift", "s"]
    loop = to_action_dict("loop", {"count": "2",
                                   "actions": '[{"type": "delay", "ms": 1}]'})
    assert loop["actions"] == [{"type": "delay", "ms": 1}]


def test_to_action_dict_key_single():
    action = to_action_dict("key_press", {"key": "up", "hold_ms": "0"})
    assert action == {"type": "key_press", "key": "up", "hold_ms": 0}
    assert action_from_dict(action).params["key"] == "up"


def test_to_action_dict_blank_optional_omitted():
    wait = to_action_dict("wait_text", {"region": "", "pattern": "好", "mode": "contains",
                                        "timeout_ms": "", "on_timeout": "abort",
                                        "goto_index": ""})
    assert "region" not in wait and "timeout_ms" not in wait
    parsed = action_from_dict(wait)
    assert parsed.params["region"] is None            # models 預設補齊
    assert parsed.params["timeout_ms"] == 5000
    text = to_action_dict("text_input", {"text": ""})
    assert text["text"] == ""                          # text 欄位允許空字串、不省略


def test_key_combo_hold_ms_field_coerced():
    assert to_action_dict("key_combo", {"keys": "ctrl+s", "hold_ms": "2000"}) == {
        "type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000}
    # 空 hold_ms → 省略（讓 models 帶預設 0）
    assert to_action_dict("key_combo", {"keys": "ctrl+s", "hold_ms": ""}) == {
        "type": "key_combo", "keys": ["ctrl", "s"]}


def test_to_action_dict_bad_values_raise_chinese():
    with pytest.raises(ScriptValidationError, match="必須是整數"):
        to_action_dict("mouse_move", {"x": "abc", "y": "2"})
    with pytest.raises(ScriptValidationError, match="逗號分隔"):
        parse_int_list("region", "1, 2, 3", 4)
    with pytest.raises(ScriptValidationError, match="不是合法 JSON"):
        to_action_dict("loop", {"count": "2", "actions": "[不是json"})
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        to_action_dict("fly", {})


def test_bool_field_round_trips_to_real_bool():
    from keyboard_executor.core.models import action_from_dict
    d = to_action_dict("if_image", {"template": "怪", "mirror": "true",
                                    "then": '[{"type": "delay", "ms": 1}]'})
    assert d["mirror"] is True
    assert action_from_dict(d).params["mirror"] is True
    assert to_action_dict("if_image", {"template": "怪", "mirror": "false",
                                       "then": '[{"type": "delay", "ms": 1}]'})["mirror"] is False
