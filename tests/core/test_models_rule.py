import pytest

from keyboard_executor.core.models import ScriptValidationError, rule_from_dict, rule_to_dict


def minimal(**over):
    data = {
        "name": "斷線重連",
        "target_window": {"title_pattern": ".*遊戲.*"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "run_script", "script_name": "重連流程"},
    }
    data.update(over)
    return data


def test_rule_minimal_defaults():
    r = rule_from_dict(minimal())
    assert r.name == "斷線重連"
    assert r.region is None
    assert r.condition.type == "text" and r.condition.pattern == "連線中斷"
    assert r.condition.mode == "contains"
    assert r.interval_sec == 5.0 and r.cooldown_sec == 60.0
    assert r.trigger.type == "run_script" and r.trigger.script_name == "重連流程"
    assert r.enabled is True


def test_rule_condition_text_regex_mode():
    r = rule_from_dict(minimal(condition={"type": "text", "pattern": r"\d+",
                                          "mode": "regex"}))
    assert r.condition.mode == "regex"


def test_rule_condition_image_threshold_default():
    r = rule_from_dict(minimal(condition={"type": "image", "template": "圖"}))
    assert r.condition.type == "image" and r.condition.template == "圖"
    assert r.condition.threshold == 0.85


def test_rule_condition_type_must_be_text_or_image():
    with pytest.raises(ScriptValidationError, match="condition"):
        rule_from_dict(minimal(condition={"type": "audio", "pattern": "x"}))


def test_rule_region_null_or_four_ints():
    r = rule_from_dict(minimal(region=[0, 0, 100, 50]))
    assert r.region == [0, 0, 100, 50]
    with pytest.raises(ScriptValidationError, match="region"):
        rule_from_dict(minimal(region=[1, 2]))


def test_rule_interval_must_be_positive():
    with pytest.raises(ScriptValidationError, match="interval_sec"):
        rule_from_dict(minimal(interval_sec=0))


def test_rule_cooldown_non_negative():
    with pytest.raises(ScriptValidationError, match="cooldown_sec"):
        rule_from_dict(minimal(cooldown_sec=-1))
    assert rule_from_dict(minimal(cooldown_sec=0)).cooldown_sec == 0.0


def test_rule_trigger_run_script_needs_name():
    with pytest.raises(ScriptValidationError, match="script_name"):
        rule_from_dict(minimal(trigger={"type": "run_script"}))


def test_rule_trigger_stop_all_no_extra():
    r = rule_from_dict(minimal(trigger={"type": "stop_all"}))
    assert r.trigger.type == "stop_all"
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        rule_from_dict(minimal(trigger={"type": "stop_all", "script_name": "x"}))


def test_rule_trigger_notify_message():
    r = rule_from_dict(minimal(trigger={"type": "notify", "message": "有事發生"}))
    assert r.trigger.type == "notify" and r.trigger.message == "有事發生"


def test_rule_trigger_type_invalid():
    with pytest.raises(ScriptValidationError, match="trigger"):
        rule_from_dict(minimal(trigger={"type": "explode"}))


def test_rule_enabled_must_be_bool():
    with pytest.raises(ScriptValidationError, match="enabled"):
        rule_from_dict(minimal(enabled="yes"))
    assert rule_from_dict(minimal(enabled=False)).enabled is False


def test_rule_name_path_safe():
    with pytest.raises(ScriptValidationError, match="name"):
        rule_from_dict(minimal(name="a/b"))


def test_rule_unknown_field_rejected():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        rule_from_dict(minimal(extra=1))


def test_rule_to_dict_round_trips():
    src = minimal(region=[1, 2, 30, 40], interval_sec=3, cooldown_sec=10,
                  condition={"type": "image", "template": "圖", "threshold": 0.9},
                  trigger={"type": "notify", "message": "嗨"}, enabled=False)
    assert rule_from_dict(rule_to_dict(rule_from_dict(src))) == rule_from_dict(src)


def test_rule_region_error_prefixed_as_rule_not_action():
    with pytest.raises(ScriptValidationError) as exc:
        rule_from_dict(minimal(region=[1, 2, 3]))
    message = str(exc.value)
    assert message.startswith("規則 欄位 region")
    assert "動作" not in message


def test_rule_condition_missing_pattern_prefixed_with_rule_condition():
    with pytest.raises(ScriptValidationError) as exc:
        rule_from_dict(minimal(condition={"type": "text"}))
    message = str(exc.value)
    assert message.startswith("規則 condition 缺少欄位 pattern")
    assert "動作" not in message


def test_rule_trigger_missing_script_name_prefixed_with_rule_trigger():
    with pytest.raises(ScriptValidationError) as exc:
        rule_from_dict(minimal(trigger={"type": "run_script"}))
    message = str(exc.value)
    assert message.startswith("規則 trigger 缺少欄位 script_name")
    assert "動作" not in message


def test_rule_number_field_errors_include_offending_value():
    """M4 待辦 #10：models 與 rule_editor_model 的數字欄位錯誤格式統一——
    「規則欄位 {name} 必須是數字: {value!r}」（>0 / >=0 同樣帶值）。"""
    def data(**overrides):
        base = {"name": "r", "target_window": {"title_pattern": "遊戲"},
                "condition": {"type": "text", "pattern": "x", "mode": "contains"},
                "trigger": {"type": "stop_all"}}
        base.update(overrides)
        return base

    with pytest.raises(ScriptValidationError, match="interval_sec 必須是數字: 'x'"):
        rule_from_dict(data(interval_sec="x"))
    with pytest.raises(ScriptValidationError, match="interval_sec 必須 > 0: 0"):
        rule_from_dict(data(interval_sec=0))
    with pytest.raises(ScriptValidationError, match="cooldown_sec 必須 >= 0: -1"):
        rule_from_dict(data(cooldown_sec=-1))


def _color_rule_dict(**cond):
    base = {"type": "color", "hue": 0, "sat": 255, "val": 255}
    base.update(cond)
    return {"name": "紅點", "target_window": {"title_pattern": "遊戲"},
            "condition": base, "trigger": {"type": "notify", "message": "有紅點"}}


def test_color_condition_roundtrip_preserves_fields():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    rule = rule_from_dict(_color_rule_dict(hue_tol=15, min_pixels=5, absent=True))
    assert rule.condition.type == "color"
    assert rule.condition.hue == 0 and rule.condition.min_pixels == 5
    assert rule.condition.absent is True
    again = rule_from_dict(rule_to_dict(rule))
    assert again.condition == rule.condition


def test_color_condition_applies_defaults():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict(_color_rule_dict())
    assert rule.condition.hue_tol == 10 and rule.condition.sat_tol == 80
    assert rule.condition.min_pixels == 3 and rule.condition.absent is False


def test_color_condition_rejects_hue_out_of_range():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(hue=200))


def test_color_condition_rejects_min_pixels_zero():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(min_pixels=0))


def test_color_condition_rejects_non_bool_absent():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(absent="yes"))


def _rule_dict(**kw):
    base = {"name": "r", "target_window": {"title_pattern": "遊戲"},
            "condition": {"type": "text", "pattern": "x"}}
    base.update(kw)
    return base


def test_rule_triggers_list_round_trip():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    r = rule_from_dict(_rule_dict(triggers=[
        {"type": "notify", "message": "m"}, {"type": "stop_all"}]))
    assert [t.type for t in r.triggers] == ["notify", "stop_all"]
    assert rule_from_dict(rule_to_dict(r)).triggers == r.triggers


def test_rule_old_single_trigger_migrates_to_list():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    r = rule_from_dict(_rule_dict(trigger={"type": "stop_all"}))
    assert len(r.triggers) == 1 and r.triggers[0].type == "stop_all"
    assert r.trigger.type == "stop_all"                         # 相容 property
    assert rule_to_dict(r)["triggers"] == [{"type": "stop_all"}]  # 存檔升級為新格式


def test_rule_empty_triggers_rejected():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_rule_dict(triggers=[]))


def test_rule_missing_triggers_rejected():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError, match="triggers"):
        rule_from_dict(_rule_dict())     # 既無 trigger 也無 triggers


def _min_rule_dict(**over):
    d = {"name": "r", "target_window": {"title_pattern": "x"},
         "condition": {"type": "text", "pattern": "p"},
         "triggers": [{"type": "notify", "message": "m"}]}
    d.update(over)
    return d


def test_attach_screenshot_defaults_false_when_absent():
    rule = rule_from_dict(_min_rule_dict())
    assert rule.attach_screenshot is False


def test_attach_screenshot_round_trips_and_serializes():
    rule = rule_from_dict(_min_rule_dict(attach_screenshot=True))
    assert rule.attach_screenshot is True
    assert rule_to_dict(rule)["attach_screenshot"] is True
    assert rule_from_dict(rule_to_dict(rule)).attach_screenshot is True


def test_attach_screenshot_must_be_bool():
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_min_rule_dict(attach_screenshot="yes"))


def test_text_condition_absent_defaults_false():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains"},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is False


def test_text_condition_absent_round_trips():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains", "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is True
    assert rule_to_dict(rule)["condition"]["absent"] is True
    assert rule_from_dict(rule_to_dict(rule)).condition.absent is True


def test_image_condition_absent_round_trips():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "image", "template": "t", "threshold": 0.9, "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is True
    assert rule_to_dict(rule)["condition"]["absent"] is True
    assert rule_from_dict(rule_to_dict(rule)).condition.absent is True


def test_text_condition_rejects_non_bool_absent():
    with pytest.raises(ScriptValidationError):
        rule_from_dict({
            "name": "r", "target_window": {"title_pattern": "x"},
            "condition": {"type": "text", "pattern": "p", "absent": "yes"},
            "triggers": [{"type": "notify", "message": "m"}]})
