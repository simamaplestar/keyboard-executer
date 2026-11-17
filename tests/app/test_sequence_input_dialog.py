from types import SimpleNamespace
import pytest
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from tests.core.test_sequence_input_config import config_data


def test_dialog_round_trip_fixed_policy_and_errors(qapp):
    from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
    from keyboard_executor.core.sequence_input_config import SequenceInputConfig
    dialog = SequenceInputDialog(SequenceInputConfig(), model_label="目前模型")
    assert not dialog.config().enabled
    dialog.enabled_check.setChecked(True)
    dialog.accept()
    assert dialog.result() == 0
    assert dialog.status_label.text()
    dialog.set_region("prompt", (10,10,300,50))
    dialog.set_region("image", (30,70,130,130))
    dialog.set_point("input", (80,220))
    dialog.set_point("confirm", (330,220))
    assert dialog.config() == sequence_config_from_dict(config_data())
    assert "30 秒" in dialog.policy_label.text()
    assert "一次" in dialog.policy_label.text()
    assert dialog.model_label.text() == "目前模型"
    dialog.set_point("input", (-1,0))
    with pytest.raises(ScriptValidationError): dialog.config()
    dialog.accept()
    assert dialog.result() == 0
    assert dialog.coordinate_edits["input_point"].text() == "-1, 0"


def test_no_target_picker_does_not_change_existing_values(qapp):
    from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
    dialog = SequenceInputDialog(sequence_config_from_dict(config_data()))
    dialog._pick("image_region")
    assert "目標視窗" in dialog.status_label.text()
    assert dialog.config().image_region == (30,70,130,130)


def test_editor_accept_undo_and_cancel_preserve_model(qapp, tmp_path, monkeypatch):
    from tests.app.test_script_editor_widget import make_dialog
    from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
    dialog, model = make_dialog(tmp_path)
    config = sequence_config_from_dict(config_data())
    monkeypatch.setattr(SequenceInputDialog, "exec", lambda self: self.DialogCode.Accepted)
    monkeypatch.setattr(SequenceInputDialog, "config", lambda self: config)
    dialog._on_sequence_input()
    assert model.sequence_input == config
    dialog._undo()
    assert model.sequence_input is None
    dialog._redo()
    assert model.sequence_input == config
    monkeypatch.setattr(SequenceInputDialog, "exec", lambda self: self.DialogCode.Rejected)
    dialog._on_sequence_input()
    assert model.sequence_input == config
