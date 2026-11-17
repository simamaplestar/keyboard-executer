import base64

import pytest

from keyboard_executor.core.models import (
    Rule,
    RuleCondition,
    RuleTrigger,
    Script,
    ScriptSettings,
    ScriptValidationError,
    TargetWindow,
    action_from_dict,
)
from keyboard_executor.core.transfer import (
    FORMAT_ID,
    FORMAT_VERSION,
    Bundle,
    build_bundle,
    missing_templates,
    parse_bundle,
    resolve,
    script_names_in_script,
    template_names_in_script,
    walk_actions,
)

PNG = b"\x89PNG\r\n\x1a\n fake bytes"


def script(name, actions=(), ):
    return Script(name=name, target_window=TargetWindow(title_pattern="遊戲"),
                  actions=tuple(action_from_dict(a) for a in actions),
                  settings=ScriptSettings())


def rule(name, *, template=None, run_script=None):
    condition = (RuleCondition(type="image", template=template, threshold=0.8)
                 if template else
                 RuleCondition(type="text", pattern="x", mode="contains"))
    trigger = (RuleTrigger(type="run_script", script_name=run_script) if run_script
               else RuleTrigger(type="notify", message="hi"))
    return Rule(name=name, target_window=TargetWindow(title_pattern="遊戲"),
                condition=condition, triggers=(trigger,))


def key(k="a"):
    return {"type": "key_press", "key": k, "hold_ms": 0}


# --- 走訪巢狀動作 ---

def test_walk_actions_descends_into_loop_and_branches():
    s = script("巢狀", [
        key("a"),
        {"type": "loop", "count": 2, "actions": [
            {"type": "wait_image", "region": None, "template": "迴圈內圖",
             "threshold": 0.8, "timeout_ms": 1000, "on_timeout": "abort"}]},
        {"type": "if_image", "region": None, "template": "條件圖", "threshold": 0.8,
         "then": [{"type": "click_image", "region": None, "template": "then圖",
                   "threshold": 0.8}],
         "else": [{"type": "run_script", "script_name": "else腳本"}]},
    ])
    types = [str(a.type) for a in walk_actions(s.actions)]
    assert types.count("wait_image") == 1 and types.count("click_image") == 1
    # 巢狀層的引用一樣要收到，只看第一層會漏
    assert template_names_in_script(s) == {"迴圈內圖", "條件圖", "then圖"}
    assert script_names_in_script(s) == {"else腳本"}


def test_script_without_references_needs_nothing():
    s = script("純按鍵", [key("a"), key("b")])
    assert template_names_in_script(s) == set()
    assert script_names_in_script(s) == set()


# --- 相依解析 ---

def make_loaders(scripts, rules):
    by_script = {s.name: s for s in scripts}
    by_rule = {r.name: r for r in rules}

    def load_script(name):
        if name not in by_script:
            raise ScriptValidationError(f"找不到腳本 {name!r}")
        return by_script[name]

    return load_script, lambda name: by_rule[name]


def test_resolve_pulls_in_scripts_referenced_by_run_script_recursively():
    a = script("A", [{"type": "run_script", "script_name": "B"}])
    b = script("B", [{"type": "run_script", "script_name": "C"}])
    c = script("C", [{"type": "click_image", "region": None, "template": "C圖",
                      "threshold": 0.8}])
    load_script, load_rule = make_loaders([a, b, c], [])
    deps = resolve(["A"], [], load_script, load_rule)
    assert [s.name for s in deps.scripts] == ["A", "B", "C"]   # 勾的排前面
    assert deps.templates == {"C圖"}
    assert deps.missing_scripts == set()


def test_resolve_pulls_in_script_referenced_by_rule_trigger():
    s = script("被規則呼叫", [key("a")])
    r = rule("規則", template="規則圖", run_script="被規則呼叫")
    load_script, load_rule = make_loaders([s], [r])
    deps = resolve([], ["規則"], load_script, load_rule)
    assert [x.name for x in deps.scripts] == ["被規則呼叫"]
    assert deps.templates == {"規則圖"}


def test_resolve_reports_missing_reference_instead_of_failing():
    """引用了已刪掉的腳本：照樣匯出其他項目，但要回報缺哪個。"""
    a = script("A", [{"type": "run_script", "script_name": "已刪除"}])
    load_script, load_rule = make_loaders([a], [])
    deps = resolve(["A"], [], load_script, load_rule)
    assert [s.name for s in deps.scripts] == ["A"]
    assert deps.missing_scripts == {"已刪除"}


def test_resolve_survives_reference_cycle():
    """A → B → A：不能無限迴圈。"""
    a = script("A", [{"type": "run_script", "script_name": "B"}])
    b = script("B", [{"type": "run_script", "script_name": "A"}])
    load_script, load_rule = make_loaders([a, b], [])
    deps = resolve(["A"], [], load_script, load_rule)
    assert sorted(s.name for s in deps.scripts) == ["A", "B"]


def test_resolve_does_not_collect_unreferenced_templates():
    """沒被引用的模板不進包——這正是單一 JSON 能維持小檔的關鍵。"""
    s = script("只用一張圖", [{"type": "click_image", "region": None,
                              "template": "有用到", "threshold": 0.8}])
    load_script, load_rule = make_loaders([s], [])
    deps = resolve(["只用一張圖"], [], load_script, load_rule)
    assert deps.templates == {"有用到"}


# --- 建構與解析往返 ---

def test_bundle_round_trip_preserves_everything():
    s = script("腳本", [key("a")])
    r = rule("規則", template="圖")
    data = build_bundle([s], [r], {"圖": PNG}, app_version="0.5.0")
    assert data["format"] == FORMAT_ID and data["version"] == FORMAT_VERSION

    bundle = parse_bundle(data)
    assert [x.name for x in bundle.scripts] == ["腳本"]
    assert [x.name for x in bundle.rules] == ["規則"]
    assert bundle.templates == {"圖": PNG}          # base64 往返後位元組相同
    assert bundle.app_version == "0.5.0"


def test_bundle_is_json_serialisable():
    import json
    s = script("腳本", [key("a")])
    data = build_bundle([s], [rule("規則", template="圖")], {"圖": PNG})
    restored = parse_bundle(json.loads(json.dumps(data, ensure_ascii=False)))
    assert restored.templates["圖"] == PNG


def test_settings_are_never_included():
    """設定含 Discord webhook 與 AI 金鑰，不得隨匯出檔外流。"""
    data = build_bundle([script("s", [key("a")])], [], {})
    assert set(data) == {"format", "version", "app_version", "scripts", "rules",
                         "templates"}


# --- 匯入端的防呆 ---

def test_parse_rejects_foreign_file():
    with pytest.raises(ScriptValidationError, match="不是 Keyboard Executor 的匯出檔"):
        parse_bundle({"hello": "world"})


def test_parse_rejects_newer_format_version():
    with pytest.raises(ScriptValidationError, match="超出本程式支援範圍"):
        parse_bundle({"format": FORMAT_ID, "version": FORMAT_VERSION + 1})


def test_parse_rejects_non_object():
    with pytest.raises(ScriptValidationError, match="最外層必須是 JSON 物件"):
        parse_bundle([1, 2, 3])


def test_parse_rejects_corrupt_template_data():
    data = build_bundle([], [], {})
    data["templates"] = {"壞圖": "!!!not base64!!!"}
    with pytest.raises(ScriptValidationError, match="模板圖片 '壞圖' 損毀"):
        parse_bundle(data)


def test_parse_validates_items_with_the_same_rules_as_local_files():
    """外部檔案不因來源不同就放行壞資料。"""
    data = build_bundle([], [], {})
    data["scripts"] = [{"name": "壞腳本", "actions": [{"type": "不存在的動作"}]}]
    with pytest.raises(ScriptValidationError):
        parse_bundle(data)


def test_missing_templates_reports_referenced_but_unattached():
    s = script("要圖", [{"type": "click_image", "region": None, "template": "沒附的圖",
                        "threshold": 0.8}])
    bundle = Bundle(scripts=[s], templates={"別的圖": PNG})
    assert missing_templates(bundle) == {"沒附的圖"}


def test_missing_templates_empty_when_complete():
    s = script("要圖", [{"type": "click_image", "region": None, "template": "有附",
                        "threshold": 0.8}])
    bundle = Bundle(scripts=[s], templates={"有附": PNG})
    assert missing_templates(bundle) == set()


def test_base64_payload_is_ascii_text():
    data = build_bundle([], [], {"圖": PNG})
    encoded = data["templates"]["圖"]
    assert isinstance(encoded, str)
    assert base64.b64decode(encoded) == PNG
