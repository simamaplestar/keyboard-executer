import pytest

from keyboard_executor.core.models import (
    Action,
    ActionType,
    ScriptValidationError,
    action_from_dict,
    action_to_dict,
)


def test_key_press_minimal():
    a = action_from_dict({"type": "key_press", "key": "enter"})
    assert a.type is ActionType.KEY_PRESS
    assert a.params == {"key": "enter", "hold_ms": 0}


def test_key_press_with_hold():
    a = action_from_dict({"type": "key_press", "key": "w", "hold_ms": 500})
    assert a.params["hold_ms"] == 500


def test_unknown_type_raises():
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        action_from_dict({"type": "fly"})


def test_unknown_field_raises():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        action_from_dict({"type": "key_press", "key": "a", "cout": 2})


def test_missing_required_field_raises():
    with pytest.raises(ScriptValidationError, match="缺少欄位"):
        action_from_dict({"type": "key_press"})


def test_wrong_type_raises():
    with pytest.raises(ScriptValidationError, match="型別"):
        action_from_dict({"type": "key_press", "key": 123})


def test_bool_is_not_int():
    with pytest.raises(ScriptValidationError, match="型別"):
        action_from_dict({"type": "mouse_move", "x": True, "y": 0})


def test_key_combo():
    a = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"]})
    assert a.params == {"keys": ["ctrl", "s"], "hold_ms": 0}


def test_key_combo_empty_list_raises():
    with pytest.raises(ScriptValidationError, match="至少"):
        action_from_dict({"type": "key_combo", "keys": []})


def test_mouse_click_defaults():
    a = action_from_dict({"type": "mouse_click", "x": 10, "y": 20})
    assert a.params == {"x": 10, "y": 20, "button": "left", "count": 1}


def test_mouse_click_invalid_button_raises():
    with pytest.raises(ScriptValidationError, match="button"):
        action_from_dict({"type": "mouse_click", "x": 1, "y": 2, "button": "side"})


def test_mouse_drag_normalizes_points():
    a = action_from_dict({"type": "mouse_drag", "from": [1, 2], "to": [3, 4]})
    assert a.params == {"from": [1, 2], "to": [3, 4], "button": "left"}


def test_mouse_drag_bad_point_raises():
    with pytest.raises(ScriptValidationError, match="兩個整數"):
        action_from_dict({"type": "mouse_drag", "from": [1], "to": [3, 4]})


def test_delay_fixed_and_range():
    assert action_from_dict({"type": "delay", "ms": 100}).params == {"ms": 100}
    assert action_from_dict({"type": "delay", "ms": [50, 150]}).params == {"ms": [50, 150]}


def test_delay_bad_range_raises():
    with pytest.raises(ScriptValidationError, match="delay"):
        action_from_dict({"type": "delay", "ms": [150, 50]})


def test_loop_recursively_validates():
    a = action_from_dict({
        "type": "loop", "count": 3,
        "actions": [{"type": "key_press", "key": "a"}],
    })
    assert a.type is ActionType.LOOP
    inner = a.params["actions"][0]
    assert isinstance(inner, Action)
    assert inner.type is ActionType.KEY_PRESS


def test_loop_invalid_count_raises():
    with pytest.raises(ScriptValidationError, match="count"):
        action_from_dict({"type": "loop", "count": 0,
                          "actions": [{"type": "key_press", "key": "a"}]})


def test_loop_bad_inner_action_raises():
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        action_from_dict({"type": "loop", "count": 1, "actions": [{"type": "nope"}]})


def test_run_script():
    a = action_from_dict({"type": "run_script", "script_name": "子腳本"})
    assert a.params == {"script_name": "子腳本"}


def test_round_trip():
    src = {
        "type": "loop", "count": 2,
        "actions": [
            {"type": "mouse_click", "x": 5, "y": 6, "button": "right", "count": 2},
            {"type": "delay", "ms": [10, 20]},
        ],
    }
    assert action_to_dict(action_from_dict(src)) == {
        "type": "loop", "count": 2,
        "actions": [
            {"type": "mouse_click", "x": 5, "y": 6, "button": "right", "count": 2},
            {"type": "delay", "ms": [10, 20]},
        ],
    }


def test_unknown_field_message_has_action_prefix():
    with pytest.raises(ScriptValidationError, match="動作 key_press 不支援的欄位: cout"):
        action_from_dict({"type": "key_press", "key": "a", "cout": 2})


def test_key_press_typo_rejected_at_load():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "key_press", "key": "entr"})


def test_key_press_accepts_alias_and_single_char():
    assert action_from_dict({"type": "key_press", "key": "return"}).params["key"] == "return"
    assert action_from_dict({"type": "key_press", "key": "A"}).params["key"] == "A"


def test_key_combo_invalid_key_name_rejected():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "key_combo", "keys": ["ctrl", "sift"]})


def test_delay_accepts_tuple_range():
    a = action_from_dict({"type": "delay", "ms": (50, 150)})
    assert a.params == {"ms": [50, 150]}


def test_action_label_specific_strings():
    from keyboard_executor.core.models import action_label
    assert action_label(action_from_dict({"type": "key_press", "key": "enter"})) == "按鍵 enter"
    assert action_label(action_from_dict(
        {"type": "mouse_click", "x": 10, "y": 20})) == "滑鼠左鍵點擊 (10, 20) ×1"
    assert action_label(action_from_dict({"type": "delay", "ms": 300})) == "延遲 300ms"
    assert action_label(action_from_dict(
        {"type": "wait_text", "pattern": "完成"})) == "等待文字「完成」"


def test_action_label_covers_every_action_type():
    from keyboard_executor.core.models import action_label
    samples = {
        "key_press": {"key": "a"},
        "key_combo": {"keys": ["ctrl", "s"]},
        "text_input": {"text": "哈囉"},
        "mouse_move": {"x": 1, "y": 2},
        "mouse_click": {"x": 1, "y": 2},
        "mouse_drag": {"from": [0, 0], "to": [5, 5]},
        "scroll": {"x": 1, "y": 2, "dy": -3},
        "delay": {"ms": [100, 200]},
        "loop": {"count": 2, "actions": [{"type": "delay", "ms": 1}]},
        "run_script": {"script_name": "子腳本"},
        "wait_text": {"pattern": "好"},
        "wait_image": {"template": "鈕"},
        "if_text": {"pattern": "好", "then": [{"type": "delay", "ms": 1}]},
        "if_image": {"template": "鈕", "then": [{"type": "delay", "ms": 1}]},
        "click_text": {"pattern": "好"},
        "click_image": {"template": "鈕"},
        "minimap_move": {"region": [0, 0, 50, 50], "target": [10, 20]},
        "minimap_goto": {"region": [0, 0, 50, 50],
                         "branches": [{"area": [0, 0, 10, 10], "goto_index": 0}]},
        "goto": {"goto_index": 0},
    }
    assert set(samples) == {str(t) for t in ActionType}
    for atype, params in samples.items():
        label = action_label(action_from_dict({"type": atype, **params}))
        assert isinstance(label, str) and label


def test_minimap_move_defaults_and_round_trip():
    from keyboard_executor.core.models import action_label, action_to_dict
    a = action_from_dict({"type": "minimap_move", "region": [25, 165, 320, 390],
                          "target": [170, 330]})
    assert a.params == {"region": [25, 165, 320, 390], "target": [170, 330],
                        "method": "walk", "tolerance": 1, "jump_key": "space",
                        "path_key": None, "path_template": None, "path_region": None,
                        "path_threshold": 0.62, "path_step": 5, "hold_keys": [], "face_reverse": False,
                        "timeout_ms": 15000, "on_timeout": "abort", "goto_index": None}
    assert action_from_dict(action_to_dict(a)) == a
    assert action_label(a) == "走到小地圖 (170, 330)"
    rope = action_from_dict({"type": "minimap_move", "region": [0, 0, 50, 50],
                             "target": [10, 20], "method": "rope"})
    assert action_label(rope) == "爬繩到小地圖 (10, 20)"


@pytest.mark.parametrize("params", [
    {"target": [10, 20]},                                           # region 必填
    {"region": [0, 0, 50, 50]},                                     # target 必填
    {"region": [0, 0, 50, 50], "target": [60, 20]},                 # target 不在區域內
    {"region": [0, 0, 50, 50], "target": [10, 20], "method": "fly"},
    {"region": [0, 0, 50, 50], "target": [10, 20], "name": 3},
    {"region": [0, 0, 50, 50], "target": [10, 20], "tolerance": 41},
    {"region": [0, 0, 50, 50], "target": [10, 20], "jump_key": "notakey"},
    {"region": [0, 0, 50, 50], "target": [10, 20], "path_key": "left"},
    {"region": [0, 0, 50, 50], "target": [10, 20], "path_key": "notakey"},
    {"region": [0, 0, 50, 50], "target": [10, 20], "path_key": "x", "path_template": "怪"},
    {"region": [0, 0, 50, 50], "target": [10, 20], "path_key": "x", "path_step": 0},
    {"region": [0, 0, 50, 50], "target": [10, 20], "path_template": "怪",
     "path_region": [0, 500, 1900, 200]},
])
def test_minimap_move_rejects_invalid(params):
    with pytest.raises(ScriptValidationError):
        action_from_dict({"type": "minimap_move", **params})


def test_minimap_move_path_key_label():
    from keyboard_executor.core.models import action_label
    a = action_from_dict({"type": "minimap_move", "region": [0, 0, 50, 50],
                          "target": [10, 20], "path_key": "x"})
    assert a.params["path_key"] == "x"
    assert action_label(a) == "走到小地圖 (10, 20)（沿路按 x）"


def test_minimap_move_name_prefixes_label_and_round_trips():
    from keyboard_executor.core.models import action_label, action_to_dict
    a = action_from_dict({"type": "minimap_move", "region": [0, 0, 50, 50],
                          "target": [10, 20], "name": " 第一層 ", "path_key": "x"})
    assert a.params["name"] == "第一層"
    assert action_label(a) == "第一層：走到小地圖 (10, 20)（沿路按 x）"
    assert action_from_dict(action_to_dict(a)) == a
    blank = action_from_dict({"type": "minimap_move", "region": [0, 0, 50, 50],
                              "target": [10, 20], "name": "  "})
    assert "name" not in blank.params
    assert action_label(blank) == "走到小地圖 (10, 20)"


def test_every_action_type_accepts_name():
    from keyboard_executor.core.models import action_label, action_to_dict
    a = action_from_dict({"type": "key_press", "key": "n", "name": "回城"})
    assert action_label(a) == "回城：按鍵 n"
    assert action_to_dict(a) == {"type": "key_press", "name": "回城", "key": "n", "hold_ms": 0}
    loop = action_from_dict({"type": "loop", "count": 2, "name": "主循環",
                             "actions": [{"type": "delay", "ms": 5, "name": "等一下"}]})
    assert action_from_dict(action_to_dict(loop)) == loop
    assert action_label(loop.params["actions"][0]) == "等一下：延遲 5ms"
    with pytest.raises(ScriptValidationError):
        action_from_dict({"type": "delay", "ms": 5, "name": ["x"]})


def test_minimap_move_path_template_needs_key_and_region():
    a = action_from_dict({"type": "minimap_move", "region": [0, 0, 50, 50], "target": [10, 20],
                          "path_key": "x", "path_template": "綠帽怪",
                          "path_region": [0, 520, 1938, 200], "path_threshold": 0.7})
    assert a.params["path_template"] == "綠帽怪"
    assert a.params["path_region"] == [0, 520, 1938, 200]
    assert a.params["path_threshold"] == 0.7


def test_minimap_goto_defaults_and_validation():
    from keyboard_executor.core.models import action_label
    a = action_from_dict({"type": "minimap_goto", "region": [25, 165, 320, 390],
                          "branches": [{"area": [135, 240, 70, 15], "goto_index": 4},
                                       {"area": [60, 515, 240, 15], "goto_index": 25}]})
    assert a.params["otherwise"] == "continue" and a.params["otherwise_index"] is None
    assert action_label(a) == "依小地圖位置跳轉（2 個區域）"
    for bad in ([], [{"area": [0, 0, 10], "goto_index": 1}], [{"area": [0, 0, 10, 10]}],
                [{"area": [0, 0, 10, 10], "goto_index": -1}]):
        with pytest.raises(ScriptValidationError):
            action_from_dict({"type": "minimap_goto", "region": [0, 0, 50, 50], "branches": bad})
    with pytest.raises(ScriptValidationError):
        action_from_dict({"type": "minimap_goto", "region": [0, 0, 50, 50], "otherwise": "goto",
                          "branches": [{"area": [0, 0, 10, 10], "goto_index": 1}]})


def test_goto_action_round_trip_and_label():
    from keyboard_executor.core.models import action_from_dict, action_label, action_to_dict
    a = action_from_dict({"type": "goto", "goto_index": 0, "name": "回到判斷樓層"})
    assert action_to_dict(a) == {"type": "goto", "name": "回到判斷樓層", "goto_index": 0}
    assert action_label(a) == "回到判斷樓層：跳到動作 #0"
    import pytest
    from keyboard_executor.core.models import ScriptValidationError
    with pytest.raises(ScriptValidationError):
        action_from_dict({"type": "goto"})


def test_minimap_move_hold_keys_validation():
    from keyboard_executor.core.models import ScriptValidationError, action_from_dict
    base = {"type": "minimap_move", "region": [0, 0, 100, 100], "target": [50, 50]}
    assert action_from_dict(base | {"hold_keys": ["c"]}).params["hold_keys"] == ["c"]
    for bad in (["left"], "c", ["not-a-key"]):
        with pytest.raises(ScriptValidationError, match="hold_keys"):
            action_from_dict(base | {"hold_keys": bad})
    with pytest.raises(ScriptValidationError, match="hold_keys"):
        action_from_dict(base | {"method": "rope", "hold_keys": ["c"]})


def test_quick_flag_for_minimap_goto_and_down_jump():
    from keyboard_executor.core.models import action_from_dict, action_to_dict
    goto = {"type": "minimap_goto", "region": [0, 0, 50, 50],
            "branches": [{"area": [0, 0, 10, 10], "goto_index": 1}]}
    assert "quick" not in action_from_dict(goto).params           # 預設不加欄位，舊腳本不變
    assert "quick" not in action_from_dict({**goto, "quick": False}).params
    a = action_from_dict({**goto, "quick": True})
    assert a.params["quick"] is True and action_to_dict(a)["quick"] is True
    jump = {"type": "minimap_move", "region": [0, 0, 50, 50], "target": [10, 40],
            "method": "down_jump"}
    assert "quick" not in action_from_dict(jump).params
    assert action_from_dict({**jump, "quick": True}).params["quick"] is True
    with pytest.raises(ScriptValidationError):
        action_from_dict({**goto, "quick": "yes"})
    with pytest.raises(ScriptValidationError, match="down_jump"):
        action_from_dict({**jump, "method": "walk", "quick": True})
