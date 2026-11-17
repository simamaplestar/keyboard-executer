"""模板管理對話框（M4 待辦 #4：TemplateStore delete seam 的 GUI 入口）。"""
import numpy as np

from keyboard_executor.app.template_manager import TemplateManagerDialog
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.storage.templates import TemplateStore


class FakeStore:
    def __init__(self, names):
        self.names = list(names)
        self.deleted = []

    def list_names(self):
        return list(self.names)

    def load_template(self, name):
        if name not in self.names:
            raise ScriptValidationError(f"找不到模板 {name!r}")
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def delete(self, name):
        if name not in self.names:
            raise ScriptValidationError(f"找不到模板 {name!r}")
        self.names.remove(name)
        self.deleted.append(name)


def test_dialog_lists_templates(qapp):
    dialog = TemplateManagerDialog(FakeStore(["乙鈕", "甲鈕"]))
    items = [dialog.template_list.item(i).text()
             for i in range(dialog.template_list.count())]
    assert items == ["乙鈕", "甲鈕"]


def test_delete_confirmed_removes_and_refreshes(qapp):
    store = FakeStore(["甲鈕", "乙鈕"])
    messages = []
    dialog = TemplateManagerDialog(store, confirm=lambda m: messages.append(m) or True)
    dialog.template_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert store.deleted == ["甲鈕"]
    assert "甲鈕" in messages[0]
    assert dialog.template_list.count() == 1
    assert "已刪除模板「甲鈕」" in dialog.status_label.text()


def test_delete_cancelled_keeps_template(qapp):
    store = FakeStore(["甲鈕"])
    dialog = TemplateManagerDialog(store, confirm=lambda m: False)
    dialog.template_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert store.deleted == []
    assert dialog.template_list.count() == 1


# --- 圖片預覽 ---

def real_store(tmp_path, **images):
    store = TemplateStore(tmp_path)
    for name, image in images.items():
        store.save_template(name, image)
    return store


def solid(h, w):
    return np.full((h, w, 3), 128, dtype=np.uint8)


def test_list_items_carry_thumbnails(qapp, tmp_path):
    """只列名稱的話，要刪掉哪張、哪張是舊的重複擷取，全靠記憶。"""
    dialog = TemplateManagerDialog(real_store(tmp_path, 甲=solid(20, 30),
                                              乙=solid(20, 30)))
    icons = [dialog.template_list.item(i).icon() for i in range(2)]
    assert all(not icon.isNull() for icon in icons)


def test_first_template_previewed_on_open(qapp, tmp_path):
    """開啟就看得到第一張，不必先點一下。"""
    dialog = TemplateManagerDialog(real_store(tmp_path, 甲=solid(20, 30)))
    assert not dialog.preview.pixmap().isNull()
    assert dialog.preview.name == "甲"
    assert dialog.size_label.text() == "30 × 20 px"


def row_of(widget, name):
    """依名稱找列——list_names() 是排序過的，不能假設加入順序就是顯示順序。"""
    for i in range(widget.count()):
        if widget.item(i).text() == name:
            return i
    raise AssertionError(f"清單中找不到 {name!r}")


def test_selecting_another_template_updates_preview(qapp, tmp_path):
    dialog = TemplateManagerDialog(real_store(tmp_path, 甲=solid(20, 30),
                                              乙=solid(40, 60)))
    dialog.template_list.setCurrentRow(row_of(dialog.template_list, "乙"))
    assert dialog.preview.name == "乙"
    assert dialog.size_label.text() == "60 × 40 px"


def test_preview_cleared_when_last_template_deleted(qapp, tmp_path):
    dialog = TemplateManagerDialog(real_store(tmp_path, 甲=solid(20, 30)),
                                   confirm=lambda m: True)
    dialog.template_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert dialog.template_list.count() == 0
    assert dialog.preview.pixmap().isNull()
    assert dialog.size_label.text() == ""


def test_empty_store_shows_placeholder(qapp, tmp_path):
    dialog = TemplateManagerDialog(real_store(tmp_path))
    assert "未指定模板" in dialog.preview.text()
