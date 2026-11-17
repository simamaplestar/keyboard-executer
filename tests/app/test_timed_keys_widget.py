"""定時技能編輯：錄製按鍵（含 F1~F12）＋秒數。"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from keyboard_executor.app.timed_keys_widget import TimedKeysWidget
from keyboard_executor.core.models import TimedKey


def test_record_f_key_and_seconds(qapp):
    widget = TimedKeysWidget()
    row = widget.add_row()
    row.key_edit._start()
    row.key_edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F5,
                                         Qt.KeyboardModifier.NoModifier))
    row.seconds.setValue(90)
    assert widget.items() == (TimedKey("f5", 90.0),)
    assert widget.text() == "f5:90"


def test_set_text_round_trip_keeps_hold_and_skips_empty_rows(qapp):
    widget = TimedKeysWidget("1:120, f12:300:1500")
    widget.add_row()                       # 還沒錄按鍵的列略過
    assert [r.key_edit.text() for r in widget.rows()] == ["1", "f12", ""]
    assert widget.text() == "1:120, f12:300:1500"
    widget._remove_row(widget.rows()[0])
    assert widget.text() == "f12:300:1500"
    widget.setText("")
    assert widget.rows() == [] and widget.items() == ()


def test_hold_seconds_or_single_tap(qapp):
    widget = TimedKeysWidget("1:120, 2:600:3000")
    rows = widget.rows()
    assert rows[0].hold.text() == "按一下" and rows[1].hold.value() == 3.0
    rows[0].hold.setValue(1.5)
    assert widget.items() == (TimedKey("1", 120.0, hold_ms=1500),
                              TimedKey("2", 600.0, hold_ms=3000))
    rows[1].hold.setValue(0)
    assert widget.items()[1].hold_ms == 100
