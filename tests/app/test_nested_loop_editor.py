import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog

from keyboard_executor.app.script_editor import ScriptEditorDialog
from keyboard_executor.app.script_editor_model import ScriptEditorModel
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage


def editor_with_loop(tmp_path):
    model = ScriptEditorModel(script_from_dict({
        "name": "雙層迴圈", "target_window": {"title_pattern": "遊戲"},
        "actions": [{"type": "loop", "count": 2, "actions": [
            {"type": "key_press", "key": "a"},
            {"type": "loop", "count": 3, "actions": [
                {"type": "key_press", "key": "b"}]}]}]}))
    return ScriptEditorDialog(model, ScriptStorage(tmp_path)), model


def respond_to_modal(callback, errors):
    def respond():
        try:
            callback(QApplication.activeModalWidget())
        except Exception as exc:
            errors.append(exc)
            QApplication.activeModalWidget().reject()
    QTimer.singleShot(0, respond)


def test_add_second_level_loop_through_inner_add_saves_and_undoes(qapp, tmp_path, monkeypatch):
    from keyboard_executor.app.script_editor import LoopActionForm
    editor, model = editor_with_loop(tmp_path)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("迴圈", True))
    errors = []

    def fill(dialog):
        assert isinstance(dialog, LoopActionForm)
        dialog.count_spin.setValue(4)
        dialog.add_action("key_press", {"key": "c", "hold_ms": "80"})
        dialog.accept()

    respond_to_modal(fill, errors)
    editor._add_to_loop(0)
    assert not errors
    result = model.action_at(0)
    assert result["count"] == 2
    assert result["actions"][2] == {"type": "loop", "count": 4, "actions": [
        {"type": "key_press", "key": "c", "hold_ms": 80}]}
    editor._undo()
    assert len(model.action_at(0)["actions"]) == 2
    editor._redo()
    editor.save_button.click()
    saved = ScriptStorage(tmp_path).load("雙層迴圈")
    assert saved.actions[0].params["actions"][2].params["count"] == 4


def test_double_click_nested_loop_edits_child_without_json_or_affecting_sibling(qapp, tmp_path):
    from keyboard_executor.app.script_editor import ActionForm, LoopActionForm
    editor, model = editor_with_loop(tmp_path)
    errors = []

    def edit_child(dialog):
        assert isinstance(dialog, ActionForm)
        dialog._edits["key"].setText("left")
        dialog._edits["hold_ms"].setText("200")
        dialog.accept()

    def edit_loop(dialog):
        assert isinstance(dialog, LoopActionForm)
        dialog.count_spin.setValue(5)
        dialog.action_list.setCurrentRow(0)
        respond_to_modal(edit_child, errors)
        dialog.edit_button.click()
        dialog.accept()

    respond_to_modal(edit_loop, errors)
    editor._edit_loop_inner(0, 1)
    assert not errors
    actions = model.action_at(0)["actions"]
    assert model.action_at(0)["count"] == 2
    assert actions[0]["key"] == "a"
    assert actions[1] == {"type": "loop", "count": 5, "actions": [
        {"type": "key_press", "key": "left", "hold_ms": 200}]}


def test_loop_form_supports_recursive_add_cancel_and_action_order(qapp):
    from keyboard_executor.app.script_editor import LoopActionForm
    dialog = LoopActionForm(initial={"count": 2, "actions": [
        {"type": "key_press", "key": "a"}, {"type": "key_press", "key": "b"}]})
    errors = []

    def cancel_child(child):
        assert isinstance(child, LoopActionForm)
        child.add_action("key_press", {"key": "c"})
        child.reject()

    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("loop"))
    respond_to_modal(cancel_child, errors)
    dialog.add_button.click()
    assert not errors
    assert [a["key"] for a in json.loads(dialog.values()["actions"])] == ["a", "b"]
    dialog.action_list.setCurrentRow(1)
    dialog.up_button.click()
    assert [a["key"] for a in json.loads(dialog.values()["actions"])] == ["b", "a"]
    dialog.remove_button.click()
    assert [a["key"] for a in json.loads(dialog.values()["actions"])] == ["a"]


def test_empty_or_zero_count_loop_cannot_be_accepted(qapp):
    from keyboard_executor.app.script_editor import LoopActionForm
    dialog = LoopActionForm()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "至少一個動作" in dialog.status_label.text()
    dialog.add_action("delay", {"ms": "100"})
    dialog.count_spin.setValue(0)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "count" in dialog.status_label.text()
    dialog.count_spin.setValue(-1)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
