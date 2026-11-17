from PySide6.QtCore import Qt

from keyboard_executor.app.key_overlay import KeyOverlay, describe_event
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton


def key_down(name):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=0, key=name)


# --- describe_event（純邏輯） ---

def test_describes_key_down_as_the_key_name():
    assert describe_event(key_down("home")) == "home"
    assert describe_event(key_down("num7")) == "num7"


def test_describes_mouse_down_and_scroll():
    down = InputEvent(kind=EventKind.MOUSE_DOWN, timestamp_ms=0, x=1, y=2,
                      button=MouseButton.LEFT)
    assert describe_event(down) == "滑鼠左鍵"
    up_scroll = InputEvent(kind=EventKind.SCROLL, timestamp_ms=0, x=1, y=2, dy=1)
    down_scroll = InputEvent(kind=EventKind.SCROLL, timestamp_ms=0, x=1, y=2, dy=-1)
    assert describe_event(up_scroll) == "滾輪↑"
    assert describe_event(down_scroll) == "滾輪↓"


def test_ignores_noisy_events():
    """放開與滑鼠移動不顯示：放開只更新修飾鍵狀態，移動在 full 模式每 100ms 一筆，
    都會把剛按的鍵洗掉。"""
    assert describe_event(InputEvent(kind=EventKind.KEY_UP, timestamp_ms=0,
                                     key="a")) is None
    assert describe_event(InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=0,
                                     x=1, y=2)) is None
    assert describe_event(InputEvent(kind=EventKind.MOUSE_UP, timestamp_ms=0,
                                     x=1, y=2, button=MouseButton.LEFT)) is None


# --- KeyOverlay（widget） ---

def test_overlay_does_not_steal_focus(qapp):
    """錄製中焦點必須留在遊戲視窗，否則後續按鍵送錯地方、錄製本身也被打斷。"""
    overlay = KeyOverlay()
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_push_appends_newest_last(qapp):
    overlay = KeyOverlay()
    for name in ("home", "ctrl", "num7"):
        overlay.push(name)
    assert overlay.keys_label.text() == "home  ›  ctrl  ›  num7"


def test_push_keeps_only_the_most_recent(qapp):
    overlay = KeyOverlay(max_items=3)
    for name in ("a", "b", "c", "d"):
        overlay.push(name)
    assert overlay.keys_label.text() == "b  ›  c  ›  d"


def test_clear_resets_to_placeholder(qapp):
    overlay = KeyOverlay()
    overlay.push("home")
    overlay.clear()
    assert "等待按鍵" in overlay.keys_label.text()
