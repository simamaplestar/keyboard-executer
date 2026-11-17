"""Chat settings stay local until script save; sending is managed by the runtime."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QTabWidget

from keyboard_executor.app.script_editor_model import ScriptEditorModel
from keyboard_executor.core.chat_reply_config import chat_config_from_dict
from keyboard_executor.core.models import ScriptValidationError, script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage


def configured_reply():
    return chat_config_from_dict({
        "enabled": True, "self_name": "我的角色", "region": [20, 40, 450, 150],
        "map_actions": [{"type": "mouse_click", "x": 22, "y": 400},
                        {"type": "text_input", "text": "{reply}"},
                        {"type": "key_press", "key": "enter"}],
        "whisper_actions": [{"type": "key_press", "key": "h"},
                            {"type": "text_input", "text": "{recipient}"},
                            {"type": "key_press", "key": "enter"},
                            {"type": "text_input", "text": "{reply}"},
                            {"type": "key_press", "key": "enter"}]})


def script_model():
    return ScriptEditorModel(script_from_dict({
        "name": "聊天測試", "target_window": {"title_pattern": "遊戲"},
        "actions": [{"type": "key_press", "key": "a"}]}))


def test_model_chat_config_is_validated_copied_and_restorable():
    model = script_model()
    before = model.snapshot()
    model.set_chat_reply(configured_reply())
    assert model.to_script().settings.chat_reply.self_name == "我的角色"
    exposed = model.chat_reply
    exposed.map_actions[0].params["x"] = 999
    assert model.chat_reply.map_actions[0].params["x"] == 22
    with pytest.raises(ScriptValidationError):
        model.set_chat_reply(replace(configured_reply(), self_name=""))
    assert model.chat_reply.enabled
    model.restore(before)
    assert model.chat_reply is None


def test_dialog_accepts_edited_settings_without_output_routes(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog(configured_reply())
    dialog.name_edit.setText(" 新名字 ")
    dialog.prompt_edit.setPlainText("保持簡短")
    dialog.interval_spin.setValue(0.5)
    dialog.timeout_spin.setValue(12)
    dialog.length_spin.setValue(35)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    result = dialog.config()
    assert (result.self_name, result.prompt, result.interval_sec,
            result.timeout_sec, result.max_reply_chars) == ("新名字", "保持簡短", 0.5, 12, 35)
    assert result.map_actions == () and result.whisper_actions == ()
    assert result.auto_map_channel is True


@pytest.mark.parametrize("field,value", [
    ("name_edit", ""), ("region_edit", ""), ("region_edit", "1, 2, 0, 100")])
def test_enabled_dialog_rejects_missing_name_or_invalid_region(qapp, field, value):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog(configured_reply())
    getattr(dialog, field).setText(value)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.status_label.text()


def test_dialog_cancel_does_not_mutate_original_settings_or_legacy_routes(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    original = configured_reply()
    dialog = ChatReplyDialog(original)
    dialog.name_edit.setText("取消的名字")
    dialog.prompt_edit.setPlainText("取消的提示詞")
    dialog.reply_whisper_check.setChecked(False)
    dialog.reject()
    assert original.self_name == "我的角色"
    assert original.map_actions[0].params["x"] == 22
    assert original.reply_whisper is True
    assert original.prompt == configured_reply().prompt


def test_dialog_only_exposes_master_and_channel_switches_with_no_route_editors(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog()
    assert set(dialog.findChildren(QCheckBox)) == {
        dialog.enabled_check, dialog.reply_map_check, dialog.reply_whisper_check}
    assert dialog.findChildren(QTabWidget) == []
    for old_control in ("map_route", "whisper_route", "whisper_preset_button", "auto_map_channel_check"):
        assert not hasattr(dialog, old_control)


def test_new_dialog_can_enable_both_channels_with_name_and_region_only(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog()
    dialog.enabled_check.setChecked(True)
    dialog.name_edit.setText("角色")
    dialog.region_edit.setText("1, 2, 300, 100")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.config().active
    assert dialog.config().map_actions == () and dialog.config().whisper_actions == ()


def test_editor_modal_commit_is_undoable_and_only_save_writes_disk(qapp, tmp_path):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    from keyboard_executor.app.script_editor import ScriptEditorDialog
    model, storage = script_model(), ScriptStorage(tmp_path)
    editor = ScriptEditorDialog(model, storage)
    errors = []

    def edit_open_dialog():
        try:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, ChatReplyDialog)
            dialog.name_edit.setText("未啟用草稿")
            dialog.accept()
        except Exception as exc:
            errors.append(exc)
            QApplication.activeModalWidget().reject()

    QTimer.singleShot(0, edit_open_dialog)
    editor.chat_reply_button.click()
    assert not errors
    assert model.chat_reply.self_name == "未啟用草稿"
    assert storage.list_names() == []
    editor._undo()
    assert model.chat_reply is None
    editor._redo()
    assert model.chat_reply.self_name == "未啟用草稿"
    editor.save_button.click()
    loaded = storage.load("聊天測試")
    assert loaded.settings.chat_reply.self_name == "未啟用草稿"
    assert not loaded.settings.chat_reply.enabled


def test_editor_modal_cancel_keeps_config_and_undo_unchanged(qapp, tmp_path):
    from keyboard_executor.app.script_editor import ScriptEditorDialog
    model = script_model()
    model.set_chat_reply(configured_reply())
    editor = ScriptEditorDialog(model, ScriptStorage(tmp_path))

    def cancel_open_dialog():
        dialog = QApplication.activeModalWidget()
        dialog.name_edit.setText("不儲存")
        dialog.reject()

    QTimer.singleShot(0, cancel_open_dialog)
    editor.chat_reply_button.click()
    assert model.chat_reply.self_name == "我的角色"
    assert not editor._undo_stack


def test_region_picker_activates_refreshes_and_converts_to_window_coordinates(qapp, monkeypatch):
    from keyboard_executor.app import region_picker
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    from keyboard_executor.core.geometry import Rect
    events = []
    original = SimpleNamespace(x=10, y=20, width=900, height=700)
    refreshed = SimpleNamespace(x=100, y=200, width=900, height=700)

    class WindowManager:
        def find_windows(self, title_pattern=None, app_name=None):
            assert (title_pattern, app_name) == ("遊戲", "Game")
            return [original]

        def activate(self, window):
            events.append("activate")
            return True

        def refresh(self, window):
            events.append("refresh")
            return refreshed

    def open_overlay(overlay):
        events.append("overlay")
        overlay.region_selected.emit(Rect(80, 120, 100, 60))

    monkeypatch.setattr(region_picker.RegionPickerOverlay, "open_fullscreen", open_overlay)
    monkeypatch.setattr(region_picker, "drag_scale", lambda _: 2.0)
    dialog = ChatReplyDialog(get_target_window=lambda: "遊戲", get_target_app=lambda: "Game",
                             get_platform=lambda: SimpleNamespace(window_manager=WindowManager()))
    dialog.pick_region_button.click()
    assert events == ["activate", "refresh", "overlay"]
    assert dialog.config().region == (60, 40, 200, 120)


def test_region_activation_failure_keeps_prior_selection(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    wm = SimpleNamespace(find_windows=lambda **_: [object()], activate=lambda _: False)
    dialog = ChatReplyDialog(configured_reply(), get_target_window=lambda: "遊戲",
                             get_platform=lambda: SimpleNamespace(window_manager=wm))
    dialog.pick_region_button.click()
    assert dialog.config().region == (20, 40, 450, 150)
    assert "最上層" in dialog.status_label.text()


def test_channel_checkboxes_save_independently_and_restore(qapp, tmp_path):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog(configured_reply())
    dialog.reply_map_check.setChecked(False)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    model = script_model()
    model.set_chat_reply(dialog.config())
    storage = ScriptStorage(tmp_path)
    storage.save(model.to_script())
    reopened = ChatReplyDialog(storage.load("聊天測試").settings.chat_reply)
    assert reopened.reply_map_check.isChecked() is False
    assert reopened.reply_whisper_check.isChecked() is True
    reopened.reply_map_check.setChecked(True)
    reopened.accept()
    assert reopened.result() == QDialog.DialogCode.Accepted
    assert reopened.config().reply_map is True


def test_applying_legacy_dialog_saves_automatic_sending_and_clears_routes(qapp, tmp_path):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    original = replace(configured_reply(), auto_map_channel=False)
    dialog = ChatReplyDialog(original)
    assert dialog.config().auto_map_channel is True
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    model = script_model()
    model.set_chat_reply(dialog.config())
    storage = ScriptStorage(tmp_path)
    storage.save(model.to_script())
    reopened = ChatReplyDialog(storage.load("聊天測試").settings.chat_reply)
    assert reopened.config().auto_map_channel is True
    assert reopened.config().map_actions == () and reopened.config().whisper_actions == ()
    assert original.auto_map_channel is False
    assert original.map_actions and original.whisper_actions


def test_both_channel_checkboxes_off_show_paused_and_accept_empty_draft(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    dialog = ChatReplyDialog()
    dialog.enabled_check.setChecked(True)
    dialog.reply_map_check.setChecked(False)
    dialog.reply_whisper_check.setChecked(False)
    assert "暫停" in dialog.channel_status.text()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.config().reply_map is False and dialog.config().reply_whisper is False


def test_default_prompt_is_editable_and_user_changes_are_saved(qapp):
    from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog
    from keyboard_executor.core.chat_reply_config import DEFAULT_PROMPT
    dialog = ChatReplyDialog()
    assert dialog.prompt_edit.toPlainText() == DEFAULT_PROMPT
    dialog.prompt_edit.setPlainText("只回答組隊問題")
    dialog.accept()
    assert dialog.config().prompt == "只回答組隊問題"


@pytest.mark.parametrize("enabled,reply_map,reply_whisper,expected", [
    (False, True, True, "未啟用"),
    (True, False, False, "已暫停（未選回覆頻道）"),
    (True, True, False, "已啟用：地圖"),
    (True, False, True, "已啟用：密語"),
    (True, True, True, "已啟用：密語／地圖")])
def test_editor_summary_reflects_selected_channels(qapp, tmp_path, enabled, reply_map, reply_whisper, expected):
    from keyboard_executor.app.script_editor import ScriptEditorDialog
    model = script_model()
    model.set_chat_reply(replace(configured_reply(), enabled=enabled,
                                 reply_map=reply_map, reply_whisper=reply_whisper))
    editor = ScriptEditorDialog(model, ScriptStorage(tmp_path))
    assert editor.chat_reply_status.text() == expected
