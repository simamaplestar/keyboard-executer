import pytest

from keyboard_executor.app.script_list import ScriptListController, summary_for_script, script_list_label
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage


def make_storage(tmp_path, names=("乙", "甲")):
    storage = ScriptStorage(tmp_path)
    for name in names:
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "記事本"},
            "actions": [{"type": "key_press", "key": "a"},
                        {"type": "delay", "ms": 10}]}))
    return storage


def test_refresh_lists_names_sorted(tmp_path):
    controller = ScriptListController(make_storage(tmp_path))
    assert controller.refresh() == ["乙", "甲"]     # ScriptStorage.list_names 已排序
    assert controller.names == ["乙", "甲"]


def test_select_tracks_selection_and_unknown_raises(tmp_path):
    controller = ScriptListController(make_storage(tmp_path))
    controller.refresh()
    controller.select("甲")
    assert controller.selected == "甲"
    with pytest.raises(ValueError, match="未知腳本"):
        controller.select("不存在")
    assert controller.selected == "甲"


def test_delete_selected_removes_and_refreshes(tmp_path):
    controller = ScriptListController(make_storage(tmp_path))
    controller.refresh()
    controller.select("甲")
    assert controller.delete_selected() == "甲"
    assert controller.names == ["乙"]
    assert controller.selected is None
    with pytest.raises(ValueError, match="尚未選取"):
        controller.delete_selected()


def test_summary_for_script_ok_and_broken(tmp_path):
    storage = make_storage(tmp_path)
    summary = summary_for_script(storage, "甲")
    assert "腳本「甲」" in summary and "2 個步驟" in summary and "記事本" in summary
    (tmp_path / "壞.json").write_text("{不是json", encoding="utf-8")
    assert "腳本載入失敗" in summary_for_script(storage, "壞")


import dataclasses


def test_duplicate_selected_copies_content_and_layout(tmp_path):
    storage = make_storage(tmp_path, names=("甲",))
    storage.save_layout("甲", {"node": [1, 2]})
    controller = ScriptListController(storage)
    controller.refresh()
    controller.select("甲")
    new = controller.duplicate_selected()
    assert new == "甲 - 複製"
    assert new in controller.names                      # 複製後清單含新名
    copy = storage.load(new)
    assert copy == dataclasses.replace(storage.load("甲"), name=new)   # 除名稱外一模一樣
    assert storage.load_layout(new) == {"node": [1, 2]}  # 版面一併複製


def test_duplicate_selected_raises_when_nothing_selected(tmp_path):
    controller = ScriptListController(make_storage(tmp_path))
    controller.refresh()
    with pytest.raises(ValueError):
        controller.duplicate_selected()


def test_script_list_label_with_and_without_hotkey(tmp_path):
    storage = ScriptStorage(tmp_path)

    def save(name, hotkey):
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "x"},
            "settings": {"hotkey": hotkey},
            "actions": [{"type": "key_press", "key": "a"}]}))

    save("甲", "")
    save("乙", "ctrl+shift+1")
    save("丙", "f8")
    assert script_list_label(storage, "甲") == "甲"
    assert script_list_label(storage, "乙") == "乙   [Ctrl+Shift+1]"
    assert script_list_label(storage, "丙") == "丙   [F8]"
    (tmp_path / "壞.json").write_text("{不是json", encoding="utf-8")
    assert script_list_label(storage, "壞") == "壞"     # 載入失敗 → 純名稱
