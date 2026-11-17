import json

import numpy as np
from PySide6.QtCore import Qt

from keyboard_executor.app.transfer_dialog import TransferDialog
from keyboard_executor.core.models import (
    Rule,
    RuleCondition,
    RuleTrigger,
    Script,
    ScriptSettings,
    TargetWindow,
    action_from_dict,
)
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.templates import TemplateStore


def script(name, actions=()):
    return Script(name=name, target_window=TargetWindow(title_pattern="遊戲"),
                  actions=tuple(action_from_dict(a) for a in actions),
                  settings=ScriptSettings())


def key(k="a"):
    return {"type": "key_press", "key": k, "hold_ms": 0}


def click_image(template):
    return {"type": "click_image", "region": None, "template": template, "threshold": 0.8}


def seed(root):
    ScriptStorage(root).save(script("主腳本", [key("a"),
                                             {"type": "run_script", "script_name": "子腳本"}]))
    ScriptStorage(root).save(script("子腳本", [click_image("子圖")]))
    RuleStorage(root).save(Rule(
        name="規則", target_window=TargetWindow(title_pattern="遊戲"),
        condition=RuleCondition(type="image", template="規則圖", threshold=0.8),
        triggers=(RuleTrigger(type="notify", message="hi"),)))
    TemplateStore(root).save_template("子圖", np.zeros((3, 3, 3), dtype=np.uint8))
    TemplateStore(root).save_template("規則圖", np.zeros((3, 3, 3), dtype=np.uint8))


def make_dialog(root):
    return TransferDialog(ScriptStorage(root), RuleStorage(root), TemplateStore(root))


def uncheck_all_but(widget, keep):
    for i in range(widget.count()):
        item = widget.item(i)
        item.setCheckState(Qt.CheckState.Checked if item.text() == keep
                           else Qt.CheckState.Unchecked)


def test_lists_everything_checked_by_default(qapp, tmp_path):
    seed(tmp_path)
    dialog = make_dialog(tmp_path)
    assert dialog.script_list.count() == 2 and dialog.rule_list.count() == 1
    states = [dialog.script_list.item(i).checkState() for i in range(2)]
    assert all(s == Qt.CheckState.Checked for s in states)


def test_plan_label_shows_auto_included_dependencies(qapp, tmp_path):
    """使用者只勾主腳本，但 run_script 會帶進子腳本——按下匯出前就要看得到。"""
    seed(tmp_path)
    dialog = make_dialog(tmp_path)
    uncheck_all_but(dialog.script_list, "主腳本")
    uncheck_all_but(dialog.rule_list, None)
    text = dialog.plan_label.text()
    assert "2 支腳本" in text and "含 1 支被呼叫的" in text
    assert "1 張模板圖片" in text


def test_plan_label_warns_about_missing_template(qapp, tmp_path):
    ScriptStorage(tmp_path).save(script("缺圖", [click_image("不存在")]))
    dialog = make_dialog(tmp_path)
    assert "找不到被引用的模板" in dialog.plan_label.text()


def test_export_button_disabled_when_nothing_selected(qapp, tmp_path):
    seed(tmp_path)
    dialog = make_dialog(tmp_path)
    dialog.select_none_button.click()
    assert not dialog.export_button.isEnabled()
    assert "尚未勾選" in dialog.plan_label.text()


def test_select_all_restores_selection(qapp, tmp_path):
    seed(tmp_path)
    dialog = make_dialog(tmp_path)
    dialog.select_none_button.click()
    dialog.select_all_button.click()
    assert dialog.export_button.isEnabled()


def test_export_writes_file_and_reports(qapp, tmp_path):
    seed(tmp_path)
    out = tmp_path / "out.json"
    dialog = make_dialog(tmp_path)
    dialog._ask_save_path = lambda: str(out)
    dialog._on_export()
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {s["name"] for s in data["scripts"]} == {"主腳本", "子腳本"}
    assert "已匯出到" in dialog.status_label.text()


def test_export_cancelled_writes_nothing(qapp, tmp_path):
    seed(tmp_path)
    dialog = make_dialog(tmp_path)
    dialog._ask_save_path = lambda: ""        # 使用者在檔案對話框按取消
    dialog._on_export()
    assert dialog.status_label.text() == ""
    assert not list(tmp_path.glob("*out*.json"))


def test_import_restores_into_empty_store(qapp, tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    src = make_dialog(tmp_path / "src")
    src._ask_save_path = lambda: str(out)
    src._on_export()

    dst_root = tmp_path / "dst"
    dialog = make_dialog(dst_root)
    dialog._ask_open_path = lambda: str(out)
    dialog._on_import()

    assert sorted(ScriptStorage(dst_root).list_names()) == ["主腳本", "子腳本"]
    assert RuleStorage(dst_root).list_names() == ["規則"]
    assert sorted(TemplateStore(dst_root).list_names()) == sorted(["子圖", "規則圖"])
    assert "已匯入" in dialog.status_label.text()
    assert dialog.script_list.count() == 2      # 匯入後清單即時刷新


def test_import_asks_before_overwriting_and_respects_no(qapp, tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    src = make_dialog(tmp_path / "src")
    src._ask_save_path = lambda: str(out)
    src._on_export()

    dst_root = tmp_path / "dst"
    ScriptStorage(dst_root).save(script("主腳本", [key("z")]))
    dialog = make_dialog(dst_root)
    dialog._ask_open_path = lambda: str(out)
    asked = []
    dialog._confirm_overwrite = lambda c: (asked.append(c), False)[1]
    dialog._on_import()

    assert asked, "同名項目必須先問過使用者"
    assert asked[0].scripts == ["主腳本"]
    assert ScriptStorage(dst_root).load("主腳本").actions[0].params["key"] == "z"
    assert "略過同名項目" in dialog.status_label.text()


def test_import_overwrites_when_user_confirms(qapp, tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    src = make_dialog(tmp_path / "src")
    src._ask_save_path = lambda: str(out)
    src._on_export()

    dst_root = tmp_path / "dst"
    ScriptStorage(dst_root).save(script("主腳本", [key("z")]))
    dialog = make_dialog(dst_root)
    dialog._ask_open_path = lambda: str(out)
    dialog._confirm_overwrite = lambda c: True
    dialog._on_import()

    assert ScriptStorage(dst_root).load("主腳本").actions[0].params["key"] == "a"


def test_import_does_not_ask_when_no_conflict(qapp, tmp_path):
    seed(tmp_path / "src")
    out = tmp_path / "out.json"
    src = make_dialog(tmp_path / "src")
    src._ask_save_path = lambda: str(out)
    src._on_export()

    dialog = make_dialog(tmp_path / "dst")
    dialog._ask_open_path = lambda: str(out)
    dialog._confirm_overwrite = lambda c: (_ for _ in ()).throw(
        AssertionError("沒有衝突時不該詢問"))
    dialog._on_import()
    assert "已匯入" in dialog.status_label.text()


def test_import_rejects_foreign_file(qapp, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": "world"}', encoding="utf-8")
    dialog = make_dialog(tmp_path)
    dialog._ask_open_path = lambda: str(bad)
    dialog._on_import()
    assert "匯入失敗" in dialog.status_label.text()


def test_import_cancelled_does_nothing(qapp, tmp_path):
    dialog = make_dialog(tmp_path)
    dialog._ask_open_path = lambda: ""
    dialog._on_import()
    assert dialog.status_label.text() == ""
