import json

import numpy as np
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
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.templates import TemplateStore
from keyboard_executor.storage.transfer import TransferService


def make_service(root):
    return TransferService(ScriptStorage(root), RuleStorage(root), TemplateStore(root))


def script(name, actions=()):
    return Script(name=name, target_window=TargetWindow(title_pattern="遊戲"),
                  actions=tuple(action_from_dict(a) for a in actions),
                  settings=ScriptSettings())


def image_rule(name, template):
    return Rule(name=name, target_window=TargetWindow(title_pattern="遊戲"),
                condition=RuleCondition(type="image", template=template, threshold=0.8),
                triggers=(RuleTrigger(type="notify", message="hi"),))


def key(k="a"):
    return {"type": "key_press", "key": k, "hold_ms": 0}


def click_image(template):
    return {"type": "click_image", "region": None, "template": template, "threshold": 0.8}


def seed(root):
    """建立一組有相依關係的資料：主腳本 → 子腳本 → 模板；規則 → 另一張模板。"""
    scripts, rules, templates = ScriptStorage(root), RuleStorage(root), TemplateStore(root)
    scripts.save(script("主腳本", [key("a"), {"type": "run_script", "script_name": "子腳本"}]))
    scripts.save(script("子腳本", [click_image("子圖")]))
    scripts.save(script("無關腳本", [key("b")]))
    rules.save(image_rule("規則", "規則圖"))
    templates.save_template("子圖", np.zeros((3, 3, 3), dtype=np.uint8))
    templates.save_template("規則圖", np.full((3, 3, 3), 255, dtype=np.uint8))
    templates.save_template("沒人用的圖", np.zeros((2, 2, 3), dtype=np.uint8))
    return scripts, rules, templates


# --- 匯出 ---

def test_plan_pulls_in_dependencies_before_exporting(tmp_path):
    seed(tmp_path)
    plan = make_service(tmp_path).plan(["主腳本"], [])
    assert plan.scripts == ["主腳本", "子腳本"]     # run_script 相依自動帶上
    assert plan.templates == ["子圖"]
    assert plan.missing_scripts == [] and plan.missing_templates == []


def test_plan_excludes_unreferenced_templates(tmp_path):
    seed(tmp_path)
    plan = make_service(tmp_path).plan(["主腳本"], ["規則"])
    assert "沒人用的圖" not in plan.templates
    assert sorted(plan.templates) == sorted(["規則圖", "子圖"])


def test_plan_reports_referenced_but_missing_template(tmp_path):
    scripts = ScriptStorage(tmp_path)
    scripts.save(script("缺圖", [click_image("不存在的圖")]))
    plan = make_service(tmp_path).plan(["缺圖"], [])
    assert plan.missing_templates == ["不存在的圖"]
    assert plan.has_warnings


def test_export_writes_readable_json_with_everything(tmp_path):
    seed(tmp_path)
    out = tmp_path / "out.json"
    summary = make_service(tmp_path).export(out, ["主腳本"], ["規則"])
    assert summary.path == out
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [s["name"] for s in data["scripts"]] == ["主腳本", "子腳本"]
    assert [r["name"] for r in data["rules"]] == ["規則"]
    assert set(data["templates"]) == {"子圖", "規則圖"}
    assert data["app_version"]


def test_exported_template_bytes_are_verbatim(tmp_path):
    _, _, templates = seed(tmp_path)
    out = tmp_path / "out.json"
    make_service(tmp_path).export(out, ["子腳本"], [])
    bundle = make_service(tmp_path).read(out)
    assert bundle.templates["子圖"] == templates.read_bytes("子圖")


# --- 匯入 ---

def test_sequence_settings_roundtrip_without_ai_credentials(tmp_path):
    from keyboard_executor.core.models import script_from_dict
    from tests.core.test_sequence_input_config import script_data, config_data
    source, target = tmp_path / "src", tmp_path / "dst"
    ScriptStorage(source).save(script_from_dict(script_data()))
    source.mkdir(exist_ok=True)
    (source / "settings.json").write_text('{"ai_api_key":"private-key"}')
    out = tmp_path / "sequence.json"
    make_service(source).export(out, ["順序輸入"], [])
    assert "private-key" not in out.read_text(encoding="utf-8")
    service = make_service(target)
    service.apply(service.read(out))
    loaded = ScriptStorage(target).load("順序輸入")
    assert loaded.settings.sequence_input.confirm_point == (330, 220)
    assert loaded.settings.sequence_input.enabled


def test_import_into_empty_store_restores_everything(tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["主腳本"], ["規則"])

    dst = tmp_path / "dst"
    service = make_service(dst)
    summary = service.apply(service.read(out))
    assert sorted(summary.scripts) == ["主腳本", "子腳本"]
    assert summary.rules == ["規則"]
    assert sorted(summary.templates) == ["子圖", "規則圖"]
    assert ScriptStorage(dst).load("主腳本").name == "主腳本"
    assert TemplateStore(dst).load_template("子圖").shape == (3, 3, 3)


def test_import_does_not_overwrite_by_default(tmp_path):
    """匯入來源是別人的檔案，靜默蓋掉自己的腳本是不可接受的資料遺失。"""
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["主腳本"], [])

    dst = tmp_path / "dst"
    mine = script("主腳本", [key("z")])          # 同名但內容不同
    ScriptStorage(dst).save(mine)
    service = make_service(dst)
    summary = service.apply(service.read(out))

    assert "主腳本" in summary.skipped
    assert "主腳本" not in summary.scripts
    kept = ScriptStorage(dst).load("主腳本")
    assert kept.actions[0].params["key"] == "z"   # 我的版本原封不動


def test_import_overwrites_only_named_items(tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["主腳本"], [])

    dst = tmp_path / "dst"
    ScriptStorage(dst).save(script("主腳本", [key("z")]))
    ScriptStorage(dst).save(script("子腳本", [key("z")]))
    service = make_service(dst)
    summary = service.apply(service.read(out), overwrite={"主腳本"})

    assert "主腳本" in summary.scripts and "子腳本" in summary.skipped
    assert ScriptStorage(dst).load("主腳本").actions[0].params["key"] == "a"
    assert ScriptStorage(dst).load("子腳本").actions[0].params["key"] == "z"


def test_conflicts_lists_existing_names(tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["主腳本"], ["規則"])

    dst = tmp_path / "dst"
    ScriptStorage(dst).save(script("主腳本", [key("z")]))
    RuleStorage(dst).save(image_rule("規則", "規則圖"))
    service = make_service(dst)
    conflicts = service.conflicts(service.read(out))
    assert conflicts.scripts == ["主腳本"] and conflicts.rules == ["規則"]
    assert bool(conflicts) is True


def test_no_conflicts_is_falsy(tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["主腳本"], [])
    service = make_service(tmp_path / "dst")
    assert not service.conflicts(service.read(out))


def test_import_continues_after_a_broken_template(tmp_path):
    """單項失敗不該讓整批匯入泡湯。"""
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["子腳本"], [])
    data = json.loads(out.read_text(encoding="utf-8"))
    data["templates"]["子圖"] = "AAAA"          # 合法 base64、但不是影像
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    dst = tmp_path / "dst"
    service = make_service(dst)
    summary = service.apply(service.read(out))
    assert summary.failed == ["子圖"]
    assert summary.scripts == ["子腳本"]        # 腳本照樣進來


def test_import_warns_about_templates_the_bundle_never_included(tmp_path):
    scripts = ScriptStorage(tmp_path / "src")
    scripts.save(script("缺圖", [click_image("沒附的圖")]))
    out = tmp_path / "out.json"
    make_service(tmp_path / "src").export(out, ["缺圖"], [])

    service = make_service(tmp_path / "dst")
    summary = service.apply(service.read(out))
    assert summary.missing_templates == ["沒附的圖"]


def test_read_rejects_non_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ScriptValidationError, match="不是合法 JSON"):
        make_service(tmp_path).read(bad)


def test_read_rejects_missing_file(tmp_path):
    with pytest.raises(ScriptValidationError, match="無法讀取"):
        make_service(tmp_path).read(tmp_path / "nope.json")
