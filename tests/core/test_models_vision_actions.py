import pytest

from keyboard_executor.core.models import (
    ActionType,
    ScriptValidationError,
    action_from_dict,
    action_to_dict,
)


def test_wait_text_minimal_defaults():
    a = action_from_dict({"type": "wait_text", "pattern": "完成"})
    assert a.type is ActionType.WAIT_TEXT
    assert a.params == {"region": None, "pattern": "完成", "mode": "contains",
                        "timeout_ms": 5000, "on_timeout": "abort", "goto_index": None}


def test_wait_text_region_four_ints():
    a = action_from_dict({"type": "wait_text", "pattern": "x",
                          "region": [10, 20, 100, 40]})
    assert a.params["region"] == [10, 20, 100, 40]


def test_wait_text_region_bad_length_rejected():
    with pytest.raises(ScriptValidationError, match="region"):
        action_from_dict({"type": "wait_text", "pattern": "x", "region": [1, 2, 3]})


def test_wait_text_mode_must_be_contains_or_regex():
    with pytest.raises(ScriptValidationError, match="mode"):
        action_from_dict({"type": "wait_text", "pattern": "x", "mode": "glob"})


def test_wait_text_on_timeout_goto_requires_index():
    with pytest.raises(ScriptValidationError, match="goto_index"):
        action_from_dict({"type": "wait_text", "pattern": "x", "on_timeout": "goto"})
    a = action_from_dict({"type": "wait_text", "pattern": "x",
                          "on_timeout": "goto", "goto_index": 3})
    assert a.params["on_timeout"] == "goto" and a.params["goto_index"] == 3


def test_wait_text_goto_index_forbidden_without_goto():
    with pytest.raises(ScriptValidationError, match="goto_index"):
        action_from_dict({"type": "wait_text", "pattern": "x",
                          "on_timeout": "continue", "goto_index": 1})


def test_wait_text_on_timeout_bad_value():
    with pytest.raises(ScriptValidationError, match="on_timeout"):
        action_from_dict({"type": "wait_text", "pattern": "x", "on_timeout": "die"})


def test_wait_text_missing_pattern():
    with pytest.raises(ScriptValidationError, match="pattern"):
        action_from_dict({"type": "wait_text"})


def test_wait_image_minimal_defaults():
    a = action_from_dict({"type": "wait_image", "template": "按鈕"})
    assert a.type is ActionType.WAIT_IMAGE
    assert a.params == {"region": None, "template": "按鈕", "threshold": 0.85,
                        "timeout_ms": 5000, "on_timeout": "abort", "goto_index": None}


def test_wait_image_threshold_out_of_range():
    with pytest.raises(ScriptValidationError, match="threshold"):
        action_from_dict({"type": "wait_image", "template": "x", "threshold": 1.5})


def test_wait_image_missing_template():
    with pytest.raises(ScriptValidationError, match="template"):
        action_from_dict({"type": "wait_image"})


def test_wait_image_threshold_zero_rejected():
    """Minor #2：threshold 的合法範圍是 (0, 1]，邊界值 0 必須被拒絕。"""
    with pytest.raises(ScriptValidationError, match="threshold"):
        action_from_dict({"type": "wait_image", "template": "x", "threshold": 0})


def test_wait_text_regex_mode_bad_pattern_rejected_eagerly():
    """Minor #2：mode=regex 時應在驗證階段（action_from_dict）就 re.compile 一次，
    不合法 regex 立刻拋 ScriptValidationError，而非留到動作真正執行時才炸開。"""
    with pytest.raises(ScriptValidationError, match="不是合法 regex"):
        action_from_dict({"type": "wait_text", "pattern": "(", "mode": "regex"})


def test_if_text_regex_mode_bad_pattern_rejected_eagerly():
    with pytest.raises(ScriptValidationError, match="不是合法 regex"):
        action_from_dict({"type": "if_text", "pattern": "(", "mode": "regex",
                          "then": [{"type": "key_press", "key": "a"}]})


def test_click_text_regex_mode_bad_pattern_rejected_eagerly():
    with pytest.raises(ScriptValidationError, match="不是合法 regex"):
        action_from_dict({"type": "click_text", "pattern": "(", "mode": "regex"})


def test_if_text_then_else_recursively_validated():
    a = action_from_dict({
        "type": "if_text", "pattern": "勝利",
        "then": [{"type": "key_press", "key": "a"}],
        "else": [{"type": "key_press", "key": "b"}],
    })
    assert a.type is ActionType.IF_TEXT
    assert [x.type for x in a.params["then"]] == [ActionType.KEY_PRESS]
    assert [x.type for x in a.params["else"]] == [ActionType.KEY_PRESS]


def test_if_text_then_required_else_optional():
    a = action_from_dict({"type": "if_text", "pattern": "x",
                          "then": [{"type": "key_press", "key": "a"}]})
    assert a.params["else"] == []
    with pytest.raises(ScriptValidationError, match="then"):
        action_from_dict({"type": "if_text", "pattern": "x", "then": []})


def test_if_text_nested_invalid_action_rejected():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "if_text", "pattern": "x",
                          "then": [{"type": "key_press", "key": "entr"}]})


def test_if_image_valid():
    a = action_from_dict({"type": "if_image", "template": "圖",
                          "then": [{"type": "delay", "ms": 100}]})
    assert a.params["template"] == "圖" and a.params["threshold"] == 0.85


def test_click_text_minimal():
    a = action_from_dict({"type": "click_text", "pattern": "登入"})
    assert a.type is ActionType.CLICK_TEXT
    assert a.params == {"region": None, "pattern": "登入", "mode": "contains"}


def test_click_image_minimal():
    a = action_from_dict({"type": "click_image", "template": "確定鈕"})
    assert a.type is ActionType.CLICK_IMAGE
    assert a.params == {"region": None, "template": "確定鈕", "threshold": 0.85}


def test_click_text_rejects_timeout_fields():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        action_from_dict({"type": "click_text", "pattern": "x", "timeout_ms": 100})


def test_action_to_dict_roundtrips_wait_text():
    src = {"type": "wait_text", "pattern": "完成", "region": [0, 0, 10, 10],
           "mode": "regex", "timeout_ms": 3000, "on_timeout": "goto", "goto_index": 2}
    assert action_to_dict(action_from_dict(src)) == {
        "type": "wait_text", "region": [0, 0, 10, 10], "pattern": "完成",
        "mode": "regex", "timeout_ms": 3000, "on_timeout": "goto", "goto_index": 2}


def test_action_to_dict_roundtrips_if_text_then_else():
    src = {"type": "if_text", "pattern": "x",
           "then": [{"type": "key_press", "key": "a", "hold_ms": 0}],
           "else": [{"type": "loop", "count": 2,
                     "actions": [{"type": "key_press", "key": "b", "hold_ms": 0}]}]}
    out = action_to_dict(action_from_dict(src))
    assert out["then"] == [{"type": "key_press", "key": "a", "hold_ms": 0}]
    assert out["else"][0]["type"] == "loop"
    assert out["else"][0]["actions"] == [{"type": "key_press", "key": "b", "hold_ms": 0}]
