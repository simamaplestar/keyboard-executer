import pytest

from keyboard_executor.app.script_editor import ScriptEditorDialog
from keyboard_executor.app.script_editor_model import ScriptEditorModel
from keyboard_executor.storage.scripts import ScriptStorage


@pytest.mark.parametrize("mode", ["normal", "game", "window_message", "scan_pulse"])
def test_mac_editor_saves_windows_script_with_standard_input(qapp, tmp_path, mode):
    model = ScriptEditorModel.new("跨平台腳本")
    model.set_input_mode(mode)
    model.insert(0, {"type": "key_press", "key": "a"})
    storage = ScriptStorage(tmp_path)
    dialog = ScriptEditorDialog(model, storage, platform_name="darwin")
    try:
        assert dialog.input_mode_combo.count() == 1
        assert dialog.input_mode_combo.currentData() == "normal"
        assert "macOS" in dialog.input_mode_combo.currentText()
        dialog.title_edit.setText("TextEdit")
        dialog._on_save()
        saved = storage.load("跨平台腳本").settings
        assert not saved.game_input_mode
        assert not saved.window_message_mode
        assert not saved.scan_pulse_mode
    finally:
        dialog.close()


def test_windows_editor_keeps_all_four_modes(qapp, tmp_path):
    dialog = ScriptEditorDialog(ScriptEditorModel.new("Windows"), ScriptStorage(tmp_path),
                                platform_name="win32")
    try:
        assert [dialog.input_mode_combo.itemData(i) for i in range(4)] == [
            "normal", "game", "window_message", "scan_pulse"]
        assert dialog.input_mode_combo.currentData() == "game"
    finally:
        dialog.close()
