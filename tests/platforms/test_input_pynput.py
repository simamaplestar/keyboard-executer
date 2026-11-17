from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from keyboard_executor.platforms.base import MouseButton
from keyboard_executor.platforms.common.input_pynput import PynputInputBackend


class SpyKeyboard:
    def __init__(self):
        self.ops = []

    def press(self, key):
        self.ops.append(("press", key))

    def release(self, key):
        self.ops.append(("release", key))

    def type(self, text):
        self.ops.append(("type", text))


class SpyMouse:
    def __init__(self):
        self.ops = []
        self._position = (0, 0)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        self.ops.append(("move", value))

    def click(self, button, count):
        self.ops.append(("click", button, count))

    def press(self, button):
        self.ops.append(("press", button))

    def release(self, button):
        self.ops.append(("release", button))

    def scroll(self, dx, dy):
        self.ops.append(("scroll", dx, dy))


def make_backend():
    kb, mouse, sleeps = SpyKeyboard(), SpyMouse(), []
    backend = PynputInputBackend(keyboard=kb, mouse=mouse, sleep=sleeps.append)
    return backend, kb, mouse, sleeps


def test_key_press_is_press_then_release():
    backend, kb, _, sleeps = make_backend()
    backend.key_press("enter")
    assert kb.ops == [("press", Key.enter), ("release", Key.enter)]
    assert sleeps == []  # hold_ms=0 不需要等待


def test_key_press_with_hold_sleeps_between():
    backend, kb, _, sleeps = make_backend()
    backend.key_press("a", hold_ms=500)
    assert kb.ops == [("press", KeyCode.from_char("a")), ("release", KeyCode.from_char("a"))]
    assert sleeps == [0.5]


def test_key_combo_releases_in_reverse_order():
    backend, kb, _, _ = make_backend()
    backend.key_combo(["ctrl", "shift", "s"])
    s = KeyCode.from_char("s")
    assert kb.ops == [
        ("press", Key.ctrl), ("press", Key.shift), ("press", s),
        ("release", s), ("release", Key.shift), ("release", Key.ctrl),
    ]


def test_type_text_delegates():
    backend, kb, _, _ = make_backend()
    backend.type_text("哈囉 world")
    assert kb.ops == [("type", "哈囉 world")]


def test_mouse_click_moves_then_clicks():
    backend, _, mouse, _ = make_backend()
    backend.mouse_click(100, 200, MouseButton.RIGHT, count=2)
    assert mouse.ops == [("move", (100, 200)), ("click", Button.right, 2)]


def test_mouse_drag_press_move_release():
    backend, _, mouse, _ = make_backend()
    backend.mouse_drag(10, 20, 30, 40)
    assert mouse.ops == [
        ("move", (10, 20)), ("press", Button.left),
        ("move", (30, 40)), ("release", Button.left),
    ]


def test_scroll_moves_then_scrolls():
    backend, _, mouse, sleeps = make_backend()
    backend.scroll(5, 6, 0, -3)
    assert mouse.ops == [("move", (5, 6)), ("scroll", 0, -3)]
    assert sleeps == [0.05]  # 移動後 settle 再捲動（M2b 統一政策）


def test_key_down_then_key_up_press_and_release_same_key():
    kb, mouse = SpyKeyboard(), SpyMouse()
    backend = PynputInputBackend(keyboard=kb, mouse=mouse, sleep=lambda s: None)
    backend.key_down("a")
    backend.key_up("a")
    assert [op[0] for op in kb.ops] == ["press", "release"]
    assert kb.ops[0][1] == kb.ops[1][1]      # 同一顆鍵先 press 後 release


def test_key_combo_holds_before_release():
    backend, _kb, _mouse, sleeps = make_backend()
    backend.key_combo(["ctrl", "s"])
    assert sleeps == [0.04]        # 按下全部後停留 40ms 再放，讓輪詢式遊戲抓得到


def test_key_combo_down_presses_in_order():
    backend, kb, _, _ = make_backend()
    backend.key_combo_down(["ctrl", "s"])
    assert kb.ops == [("press", Key.ctrl), ("press", KeyCode.from_char("s"))]


def test_key_combo_up_releases_in_reverse():
    backend, kb, _, _ = make_backend()
    backend.key_combo_up(["ctrl", "s"])
    assert kb.ops == [("release", KeyCode.from_char("s")), ("release", Key.ctrl)]


def test_key_combo_is_down_hold_up():
    backend, kb, _, sleeps = make_backend()
    backend.key_combo(["ctrl", "s"])
    s = KeyCode.from_char("s")
    assert kb.ops == [("press", Key.ctrl), ("press", s),
                      ("release", s), ("release", Key.ctrl)]
    assert sleeps == [0.04]     # _COMBO_HOLD
