"""script_gen：AI 提案 → 既有 script_from_dict 全套驗證（安全網）。"""
import pytest

from keyboard_executor.core.ai.script_gen import (
    actions_for_edit,
    automation_bundle_from_proposal,
    rule_from_proposal,
    script_from_proposal,
)
from keyboard_executor.core.models import ScriptValidationError, script_from_dict


def test_valid_proposal_builds_script():
    s = script_from_proposal("打怪", "遊戲.*", [
        {"type": "key_press", "key": "a"},
        {"type": "delay", "ms": 500},
        {"type": "loop", "count": 3, "actions": [{"type": "key_press", "key": "b"}]},
    ])
    assert s.name == "打怪"
    assert s.target_window.title_pattern == "遊戲.*"
    assert len(s.actions) == 3
    assert s.settings.speed == 1.0   # 預設 settings


def test_unknown_action_type_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "t", [{"type": "hack_the_game"}])


def test_missing_field_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "t", [{"type": "key_press"}])   # 缺 key


def test_bad_name_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("a/b", "t", [{"type": "key_press", "key": "a"}])


def test_bad_regex_rejected():
    with pytest.raises(ScriptValidationError):
        script_from_proposal("x", "[", [{"type": "key_press", "key": "a"}])


def _current():
    return script_from_dict({
        "name": "原本", "target_window": {"title_pattern": "app"},
        "settings": {"speed": 2.0, "repeat": 5, "hotkey": "f6"},
        "actions": [{"type": "key_press", "key": "a"}],
    })


def test_edit_replaces_actions_keeps_everything_else():
    edited = actions_for_edit(_current(), [{"type": "delay", "ms": 100},
                                           {"type": "key_press", "key": "b"}])
    assert edited.name == "原本"
    assert edited.settings.speed == 2.0 and edited.settings.repeat == 5
    assert edited.settings.hotkey == "f6"
    assert [str(a.type) for a in edited.actions] == ["delay", "key_press"]


def test_edit_invalid_actions_rejected():
    with pytest.raises(ScriptValidationError):
        actions_for_edit(_current(), [])
    with pytest.raises(ScriptValidationError):
        actions_for_edit(_current(), [{"type": "nope"}])


def _rule(name="看見文字", script="按確認"):
    return {
        "name": name,
        "target_window": {"title_pattern": "遊戲"},
        "region": [10, 20, 300, 80],
        "condition": {"type": "text", "pattern": "確認", "mode": "contains"},
        "triggers": [{"type": "run_script", "script_name": script}],
    }


def test_rule_proposal_uses_existing_validation():
    rule = rule_from_proposal(_rule())
    assert rule.name == "看見文字" and rule.region == [10, 20, 300, 80]


def test_bundle_validates_scripts_and_rules_together():
    scripts, rules = automation_bundle_from_proposal([{
        "name": "按確認", "target_window": {"title_pattern": "遊戲"},
        "actions": [{"type": "key_press", "key": "enter"}],
    }], [_rule()])
    assert scripts[0].name == "按確認" and rules[0].trigger.script_name == "按確認"


def test_bundle_rejects_duplicate_names():
    script = {"name": "同名", "target_window": {"title_pattern": "x"},
              "actions": [{"type": "delay", "ms": 1}]}
    with pytest.raises(ScriptValidationError, match="不可重複"):
        automation_bundle_from_proposal([script, script], [])
