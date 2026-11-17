import pytest

from keyboard_executor.app.rule_editor_model import RuleEditorModel
from keyboard_executor.core.models import ScriptValidationError, rule_from_dict, rule_to_dict


def make_rule():
    return rule_from_dict({
        "name": "斷線重連", "target_window": {"title_pattern": ".*遊戲.*"},
        "region": [5, 6, 30, 40],
        "condition": {"type": "text", "pattern": "連線中斷", "mode": "contains"},
        "interval_sec": 3, "cooldown_sec": 30,
        "trigger": {"type": "run_script", "script_name": "重連流程"},
        "enabled": False})


def test_from_rule_populates_fields():
    model = RuleEditorModel.from_rule(make_rule())
    assert model.name == "斷線重連"
    assert model.title_pattern == ".*遊戲.*"
    assert model.region_text == "5, 6, 30, 40"
    assert model.condition_type == "text" and model.pattern == "連線中斷"
    assert model.interval_sec == "3.0" and model.cooldown_sec == "30.0"
    assert model.run_script_enabled and model.script_name == "重連流程"
    assert model.enabled is False


def test_to_rule_text_condition_round_trip():
    model = RuleEditorModel.from_rule(make_rule())
    assert rule_to_dict(model.to_rule()) == rule_to_dict(make_rule())


def test_to_rule_image_condition():
    model = RuleEditorModel()
    model.name = "圖規則"
    model.title_pattern = "遊戲"
    model.condition_type = "image"
    model.template = "按鈕"
    model.threshold = "0.9"
    model.notify_enabled = True
    model.message = "出現了"
    rule = model.to_rule()
    assert rule.condition.type == "image"
    assert rule.condition.template == "按鈕" and rule.condition.threshold == 0.9
    assert rule.trigger.message == "出現了"
    assert rule.region is None                       # region_text 留空＝整個視窗


def test_to_rule_invalid_missing_pattern_uses_rule_condition_prefix():
    model = RuleEditorModel()
    model.name = "壞"
    model.title_pattern = "遊戲"
    model.pattern = ""                               # 文字條件缺 pattern
    model.stop_all_enabled = True
    model.notify_enabled = False
    with pytest.raises(ScriptValidationError, match="規則 condition"):
        model.to_rule()


def test_to_rule_bad_numbers_raise_chinese():
    model = RuleEditorModel()
    model.name = "壞"
    model.title_pattern = "遊戲"
    model.pattern = "x"
    model.stop_all_enabled = True
    model.notify_enabled = False
    model.interval_sec = "abc"
    with pytest.raises(ScriptValidationError, match="interval_sec 必須是數字"):
        model.to_rule()
    model.interval_sec = "5"
    model.region_text = "1, 2, 3"
    with pytest.raises(ScriptValidationError, match="逗號分隔"):
        model.to_rule()


def test_trigger_variants_round_trip():
    model = RuleEditorModel()
    model.name = "停" ; model.title_pattern = "遊戲" ; model.pattern = "x"
    model.stop_all_enabled = True
    model.notify_enabled = False
    assert model.to_rule().trigger.type == "stop_all"
    model.stop_all_enabled = False        # 只測 notify，先關掉前一段的 stop_all
    model.notify_enabled = True ; model.message = "訊息"
    assert model.to_rule().trigger.message == "訊息"


def test_to_dict_builds_color_condition():
    m = RuleEditorModel()
    m.condition_type = "color"
    m.hue, m.sat, m.val = "0", "255", "255"
    m.hue_tol = "15"
    m.min_pixels = "5"
    m.absent = True
    cond = m.to_dict()["condition"]
    assert cond == {"type": "color", "hue": 0, "sat": 255, "val": 255,
                    "hue_tol": 15, "min_pixels": 5, "absent": True}


def test_from_rule_reads_color_condition():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict({
        "name": "紅點", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "color", "hue": 3, "sat": 200, "val": 230,
                      "hue_tol": 12, "min_pixels": 4, "absent": True},
        "trigger": {"type": "notify", "message": "有紅點"}})
    m = RuleEditorModel.from_rule(rule)
    assert m.condition_type == "color"
    assert m.hue == "3" and m.min_pixels == "4" and m.absent is True


def test_color_model_to_rule_validates():
    m = RuleEditorModel()
    m.name = "紅點"
    m.title_pattern = "遊戲"
    m.condition_type = "color"
    m.hue, m.sat, m.val = "0", "255", "255"
    m.stop_all_enabled = True
    m.notify_enabled = False
    rule = m.to_rule()                       # 不應拋例外
    assert rule.condition.type == "color"


def test_to_dict_builds_triggers_in_fixed_order():
    m = RuleEditorModel()
    m.notify_enabled = True
    m.message = "有事"
    m.stop_all_enabled = True
    m.run_script_enabled = False
    assert m.to_dict()["triggers"] == [
        {"type": "notify", "message": "有事"}, {"type": "stop_all"}]


def test_from_rule_reads_multiple_triggers():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "x"},
        "triggers": [{"type": "notify", "message": "m"}, {"type": "stop_all"}]})
    model = RuleEditorModel.from_rule(rule)
    assert model.notify_enabled and model.stop_all_enabled
    assert not model.run_script_enabled and model.message == "m"


def test_attach_screenshot_flag_serializes_to_dict():
    model = RuleEditorModel()
    model.name = "r"
    model.title_pattern = "x"
    model.pattern = "p"
    model.notify_enabled = True
    model.message = "m"
    model.attach_screenshot = True
    assert model.to_dict()["attach_screenshot"] is True


def test_from_rule_restores_attach_screenshot():
    rule = rule_from_dict(_min_attach_rule(True))
    assert RuleEditorModel.from_rule(rule).attach_screenshot is True


def _min_attach_rule(attach):
    return {"name": "r", "target_window": {"title_pattern": "x"},
            "condition": {"type": "text", "pattern": "p"},
            "triggers": [{"type": "notify", "message": "m"}],
            "attach_screenshot": attach}


def test_text_absent_serializes_to_condition():
    model = RuleEditorModel()
    model.name = "r"
    model.title_pattern = "x"
    model.condition_type = "text"
    model.pattern = "p"
    model.notify_enabled = True
    model.message = "m"
    model.absent = True
    assert model.to_dict()["condition"]["absent"] is True


def test_from_rule_restores_absent_for_text():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains", "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert RuleEditorModel.from_rule(rule).absent is True
