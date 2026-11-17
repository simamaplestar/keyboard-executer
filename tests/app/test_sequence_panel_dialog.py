import pytest
from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from keyboard_executor.core.models import ScriptValidationError
from tests.core.test_sequence_input_config import config_data


def test_new_dialog_one_region(qapp):
    dialog = SequenceInputDialog()
    assert dialog.config().mode == 'panel'
    dialog.enabled_check.setChecked(True)
    with pytest.raises(ScriptValidationError): dialog.config()
    dialog.set_region('panel', (10, 20, 400, 300))
    assert dialog.config().panel_region == (10, 20, 400, 300)
    assert dialog.config().enabled
    assert set(dialog.coordinate_edits) == {'panel_region'}
    assert 'OCR' in dialog.policy_label.text()
    assert '30 秒' in dialog.policy_label.text()
    assert 'Discord' in dialog.hint_label.text()


def test_manual_conversion_is_atomic(qapp):
    config = sequence_config_from_dict(config_data())
    dialog = SequenceInputDialog(config)
    dialog._pick('panel_region')
    assert dialog.config() == config  # no target selected, unchanged
    dialog.set_region('panel', (20, 30, 400, 300))
    assert dialog.config().mode == 'panel'
    assert dialog.config().input_point is None
    assert set(dialog.coordinate_edits) == {'panel_region'}


def test_invalid_conversion_preserves_legacy(qapp):
    config = sequence_config_from_dict(config_data())
    dialog = SequenceInputDialog(config)
    with pytest.raises(ScriptValidationError): dialog.set_region('panel', (0, 0, 0, 10))
    assert dialog.config() == config


def test_picker_cancel_dpi_and_successful_conversion(qapp, monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from types import SimpleNamespace
    from keyboard_executor.app import region_picker
    from keyboard_executor.core.geometry import Rect
    from keyboard_executor.platforms.base import WindowInfo
    from tests.fakes import FakeWindowManager
    class Overlay(QObject):
        region_selected = Signal(object)
        cancelled = Signal()
        def __init__(self, *args, **kwargs): super().__init__()
        def open_fullscreen(self): pass
        def devicePixelRatio(self): return 1.25
    monkeypatch.setattr(region_picker, 'RegionPickerOverlay', Overlay)
    monkeypatch.setattr(region_picker, 'drag_scale', lambda scale: scale)
    config = sequence_config_from_dict(config_data())
    win = WindowInfo(1, 'panel', 'app', 0, 0, 500, 500, True)
    wm = FakeWindowManager([win])
    dialog = SequenceInputDialog(config, get_target_window=lambda: 'panel',
        get_platform=lambda: SimpleNamespace(window_manager=wm), capture_factory=lambda: None)
    dialog._pick('panel_region')
    dialog._overlay.cancelled.emit()
    assert dialog.config() == config
    dialog._pick('panel_region')
    dialog._overlay.region_selected.emit(Rect(8, 16, 320, 240))
    assert dialog.config().panel_region == (10, 20, 400, 300)
    assert dialog.config().mode == 'panel'


def test_panel_roundtrip_disabled_and_negative(qapp):
    config = sequence_config_from_dict(dict(mode='panel', enabled=False))
    dialog = SequenceInputDialog(config)
    assert dialog.config() == config
    dialog.coordinate_edits['panel_region'].setText('-1, 2, 3, 4')
    with pytest.raises(ScriptValidationError): dialog.config()
    dialog.accept()
    assert dialog.result() == 0
