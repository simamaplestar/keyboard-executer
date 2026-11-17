from types import SimpleNamespace

import pytest
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook


class SpyListener:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class ListenerFactory:
    """記錄每次建構出的 SpyListener，供測試取用 callbacks。"""

    def __init__(self):
        self.instances = []

    def __call__(self, **callbacks):
        listener = SpyListener(**callbacks)
        self.instances.append(listener)
        return listener


def make_hook(clock_value=1.5):
    kb_factory, mouse_factory = ListenerFactory(), ListenerFactory()
    hook = PynputInputHook(keyboard_listener_cls=kb_factory,
                           mouse_listener_cls=mouse_factory,
                           clock=lambda: clock_value)
    events: list[InputEvent] = []
    hook.start(events.append)
    return hook, kb_factory.instances[0], mouse_factory.instances[0], events


def test_start_starts_keyboard_and_mouse_listeners():
    hook, kb, mouse, _ = make_hook()
    assert kb.started and mouse.started
    assert set(kb.callbacks) == {"on_press", "on_release"}
    assert set(mouse.callbacks) == {"on_move", "on_click", "on_scroll"}


def test_key_press_emits_key_down_with_canonical_name():
    _, kb, _, events = make_hook(clock_value=1.5)
    kb.callbacks["on_press"](Key.f9)
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500, key="f9")]


def test_key_release_emits_key_up_and_lowercases_char():
    _, kb, _, events = make_hook()
    kb.callbacks["on_release"](KeyCode.from_char("A"))
    assert events == [InputEvent(kind=EventKind.KEY_UP, timestamp_ms=1500, key="a")]


def test_unrecognized_key_is_skipped():
    _, kb, _, events = make_hook()
    kb.callbacks["on_press"](Key.media_play_pause)
    assert events == []


def test_click_emits_mouse_down_then_up():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_click"](10, 20, Button.left, True)
    mouse.callbacks["on_click"](10, 20, Button.left, False)
    assert [e.kind for e in events] == [EventKind.MOUSE_DOWN, EventKind.MOUSE_UP]
    assert events[0].button is MouseButton.LEFT
    assert (events[0].x, events[0].y) == (10, 20)


def test_unsupported_button_is_skipped():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_click"](1, 2, SimpleNamespace(name="x1"), True)
    assert events == []


def test_move_emits_mouse_move_with_int_coords():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_move"](10.7, 20.2)
    assert events == [InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=1500, x=10, y=20)]


def test_scroll_emits_scroll_event():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_scroll"](5, 6, 0, -3)
    assert events == [InputEvent(kind=EventKind.SCROLL, timestamp_ms=1500, x=5, y=6, dx=0, dy=-3)]


def test_double_start_raises_in_chinese():
    hook, _, _, _ = make_hook()
    with pytest.raises(RuntimeError, match="重複啟動"):
        hook.start(lambda e: None)


def test_stop_stops_both_listeners_and_allows_restart():
    hook, kb, mouse, _ = make_hook()
    hook.stop()
    assert kb.stopped and mouse.stopped
    hook.start(lambda e: None)  # stop 後可重新 start，不拋錯


class CanonicalSpyListener(SpyListener):
    """帶 canonical() 的 Spy：一律把按鍵正規化為 KeyCode('s')。"""

    def canonical(self, key):
        return KeyCode.from_char("s")


class _CanonicalKbFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, **callbacks):
        listener = CanonicalSpyListener(**callbacks)
        self.instances.append(listener)
        return listener


def _canonical_hook():
    kb_factory = _CanonicalKbFactory()
    hook = PynputInputHook(keyboard_listener_cls=kb_factory,
                           mouse_listener_cls=ListenerFactory(),
                           clock=lambda: 1.5)
    events: list[InputEvent] = []
    hook.start(events.append)
    return kb_factory.instances[0], events


def test_on_press_uses_listener_canonical_for_char_keys():
    # 字元鍵仍走 canonical（修正 Alt/Ctrl 按住時的字元變形）
    kb, events = _canonical_hook()
    kb.callbacks["on_press"](KeyCode.from_char("x"))   # canonical() 換成 's'
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500, key="s")]


def test_special_keys_bypass_canonical():
    """特殊鍵不得送進 canonical()——送進去就再也錄不到。

    真實 pynput 的 canonical() 會把任何帶 vk 的 Key 轉成純 vk 的 KeyCode
    （keyboard/_base.py:762），那種 KeyCode 沒有 .char，key_to_name 回 None，
    事件就被靜默丟棄。Windows 上每個特殊鍵都有 vk，曾導致 home/方向鍵/delete/
    enter/tab/esc/F1-F20 全部錄不到（macOS 的 vk 為 None 所以不現形）。
    """
    kb, events = _canonical_hook()   # 這個 Spy 的 canonical 會把任何鍵變成 's'
    kb.callbacks["on_press"](Key.f9)
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500, key="f9")]


@pytest.mark.parametrize("key, expected", [
    (Key.home, "home"), (Key.end, "end"), (Key.page_up, "pageup"),
    (Key.page_down, "pagedown"), (Key.up, "up"), (Key.down, "down"),
    (Key.delete, "delete"), (Key.enter, "enter"), (Key.tab, "tab"),
    (Key.space, "space"), (Key.esc, "esc"), (Key.backspace, "backspace"),
    (Key.f1, "f1"), (Key.f12, "f12"),
    (Key.ctrl_l, "ctrl"), (Key.shift_r, "shift"), (Key.alt_gr, "alt"),
])
def test_special_keys_are_recorded_with_real_canonical(key, expected):
    """以真實 pynput Listener 的 canonical() 走完整條路徑（回歸測試）。"""
    from pynput import keyboard as real_keyboard

    hook, kb, _, events = make_hook()
    hook._kb_listener = real_keyboard.Listener(on_press=lambda k: None)
    kb.callbacks["on_press"](key)
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500,
                                 key=expected)]


def test_start_recovers_from_partial_startup_failure_and_allows_retry():
    should_fail = {"value": True}

    class FlakyListener(SpyListener):
        def start(self):
            if should_fail["value"]:
                raise RuntimeError("boom")
            self.started = True

    class FlakyMouseFactory:
        def __init__(self):
            self.instances = []

        def __call__(self, **callbacks):
            listener = FlakyListener(**callbacks)
            self.instances.append(listener)
            return listener

    kb_factory = ListenerFactory()
    mouse_factory = FlakyMouseFactory()
    hook = PynputInputHook(keyboard_listener_cls=kb_factory,
                           mouse_listener_cls=mouse_factory,
                           clock=lambda: 1.5)

    with pytest.raises(RuntimeError, match="boom"):
        hook.start(lambda e: None)

    assert hook._kb_listener is None
    assert hook._mouse_listener is None
    assert kb_factory.instances[0].stopped  # 已啟動的 kb listener 被回收

    should_fail["value"] = False
    hook.start(lambda e: None)  # 半啟動回收後重設狀態，不誤判「重複啟動」
    assert hook._kb_listener is not None


def test_numpad_bypasses_canonical_and_keeps_its_identity():
    """numpad 鍵不得送進 canonical()——送進去 vk 會遺失、退化成主鍵盤數字。

    Windows 的 canonical 對帶 scan code 的 KeyCode 回傳 KeyCode.from_char(char)
    （keyboard/_win32.py:395），vk 被丟掉。NumLock 開啟時 numpad 7 的 char 就是
    '7'，於是與主鍵盤 7 再也分不出來——但遊戲裡兩者是可分別綁定的不同實體鍵。
    """
    from pynput import keyboard as real_keyboard

    hook, kb, _, events = make_hook()
    hook._kb_listener = real_keyboard.Listener(on_press=lambda k: None)
    # pynput 在 NumLock 開啟時對 numpad 7 產生的形狀：vk=0x67, char='7', scan=0x47
    kb.callbacks["on_press"](KeyCode(vk=0x67, char="7", _scan=0x47))
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500,
                                 key="num7")]


def test_main_row_digit_still_records_as_plain_digit():
    from pynput import keyboard as real_keyboard

    hook, kb, _, events = make_hook()
    hook._kb_listener = real_keyboard.Listener(on_press=lambda k: None)
    kb.callbacks["on_press"](KeyCode(vk=0x37, char="7", _scan=0x08))
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500, key="7")]
