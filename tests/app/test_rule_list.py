from keyboard_executor.app.rule_list import RuleListController
from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.storage.rules import RuleStorage


def make_storage(tmp_path):
    storage = RuleStorage(tmp_path)
    for name, enabled in (("甲", True), ("乙", False)):
        storage.save(rule_from_dict({
            "name": name, "target_window": {"title_pattern": "遊戲"},
            "condition": {"type": "text", "pattern": "x"},
            "trigger": {"type": "stop_all"}, "enabled": enabled}))
    return storage


def test_labels_show_enabled_state(tmp_path):
    controller = RuleListController(make_storage(tmp_path))
    # RuleStorage.list_names() 已排序（codepoint 序：乙 U+4E59 < 甲 U+7532）
    assert controller.labels() == ["乙（停用）", "甲（啟用）"]
    assert controller.names == ["乙", "甲"]


def test_toggle_enabled_flips_and_persists(tmp_path):
    storage = make_storage(tmp_path)
    controller = RuleListController(storage)
    assert controller.toggle_enabled("甲") is False
    assert storage.load("甲").enabled is False
    assert controller.toggle_enabled("乙") is True
    assert storage.load("乙").enabled is True


def test_delete_removes_rule(tmp_path):
    storage = make_storage(tmp_path)
    controller = RuleListController(storage)
    controller.delete("甲")
    assert controller.labels() == ["乙（停用）"]


import dataclasses


def test_duplicate_copies_rule_with_unique_name(tmp_path):
    storage = make_storage(tmp_path)
    controller = RuleListController(storage)
    new = controller.duplicate("甲")
    assert new == "甲 - 複製"
    copy = storage.load(new)
    assert copy == dataclasses.replace(storage.load("甲"), name=new)   # 除名稱外一模一樣
    assert new in storage.list_names()
