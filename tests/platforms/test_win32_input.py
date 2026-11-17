import pytest

from keyboard_executor.platforms.base import MouseButton, WindowInfo
from keyboard_executor.platforms.win32.input import Win32InputBackend


class SpyPdi:
    """模擬 pydirectinput 模組的最小介面。"""

    def __init__(self):
        self.ops = []
        self.PAUSE = 0.1

    def keyDown(self, key):
        self.ops.append(("keyDown", key))

    def keyUp(self, key):
        self.ops.append(("keyUp", key))

    def moveTo(self, x, y):
        self.ops.append(("moveTo", x, y))

    def click(self, button):
        self.ops.append(("click", button))

    def press(self, key):
        self.ops.append(("press", key))

    def mouseDown(self, button):
        self.ops.append(("mouseDown", button))

    def mouseUp(self, button):
        self.ops.append(("mouseUp", button))


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


class SpyNativeWindow:
    def __init__(self, hwnd):
        self._hwnd = hwnd

    def getHandle(self):
        return self._hwnd


class SpyUser32:
    def __init__(self, foreground=0x1234):
        self.foreground = foreground
        self.ops = []
        self.scans = {0x26: 0x48, 0x28: 0x50, 0x25: 0x4B, 0x27: 0x4D}

    def GetForegroundWindow(self):
        return self.foreground

    def MapVirtualKeyW(self, vk, mode):
        assert mode == 0
        return self.scans.get(vk, vk)

    def VkKeyScanW(self, char_code):
        ch = char_code if isinstance(char_code, str) else chr(char_code)
        return ord(ch.upper()) if ch.isalnum() else -1

    def PostMessageW(self, hwnd, message, wparam, lparam):
        self.ops.append((hwnd, message, wparam, lparam))
        return 1


def make_game_backend():
    pdi, kb, mouse, sleeps = SpyPdi(), SpyKeyboard(), SpyMouse(), []
    backend = Win32InputBackend(
        game_input_mode=True, pdi=pdi, keyboard=kb, mouse=mouse, sleep=sleeps.append
    )
    return backend, pdi, kb, mouse, sleeps


def make_message_backend(*, foreground=0x1234):
    user32, kb, mouse, sleeps = SpyUser32(foreground), SpyKeyboard(), SpyMouse(), []
    backend = Win32InputBackend(
        window_message_mode=True, user32=user32,
        keyboard=kb, mouse=mouse, sleep=sleeps.append)
    backend.set_target_window(WindowInfo(
        handle=SpyNativeWindow(0x1234), title="遊戲", app_name="Game",
        x=0, y=0, width=800, height=600, is_active=True))
    return backend, user32, kb, mouse, sleeps


def make_scan_pulse_backend():
    pdi, kb, mouse, sleeps = SpyPdi(), SpyKeyboard(), SpyMouse(), []
    backend = Win32InputBackend(
        scan_pulse_mode=True, pdi=pdi, keyboard=kb, mouse=mouse,
        sleep=sleeps.append)
    return backend, pdi, kb, mouse, sleeps


def test_game_mode_key_press_uses_pydirectinput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.key_press("enter")
    assert pdi.ops == [("keyDown", "enter"), ("keyUp", "enter")]
    assert kb.ops == []  # 不走 pynput


def test_game_mode_key_press_with_hold():
    backend, pdi, kb, _, sleeps = make_game_backend()
    backend.key_press("w", hold_ms=1000)
    assert pdi.ops == [("keyDown", "w"), ("keyUp", "w")]
    assert sleeps == [1.0]
    assert kb.ops == []  # 不走 pynput


def test_game_mode_key_combo_releases_in_reverse():
    backend, pdi, kb, mouse, _ = make_game_backend()
    backend.key_combo(["ctrl", "c"])
    assert pdi.ops == [
        ("keyDown", "ctrl"), ("keyDown", "c"),
        ("keyUp", "c"), ("keyUp", "ctrl"),
    ]
    assert kb.ops == []
    assert mouse.ops == []


def test_game_mode_click_uses_pydirectinput():
    backend, pdi, _, mouse, _ = make_game_backend()
    backend.mouse_click(100, 200, MouseButton.RIGHT, count=2)
    assert pdi.ops == [("moveTo", 100, 200), ("click", "right"), ("click", "right")]
    assert mouse.ops == []


def test_normal_mode_falls_back_to_pynput():
    kb, mouse = SpyKeyboard(), SpyMouse()
    backend = Win32InputBackend(
        game_input_mode=False, keyboard=kb, mouse=mouse, sleep=lambda s: None
    )
    backend.type_text("hi")
    backend.mouse_click(1, 2)
    assert kb.ops == [("type", "hi")]
    assert ("move", (1, 2)) in mouse.ops


def test_pause_zero_is_set_on_injected_pdi():
    _, pdi, _, _, _ = make_game_backend()
    assert pdi.PAUSE == 0  # SpyPdi 初始為 0.1，建構子必須歸零


def test_game_mode_ascii_text_pressed_char_by_char():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.type_text("hi 42")
    assert pdi.ops == [("press", ch) for ch in "hi 42"]
    assert kb.ops == []  # 不走 pynput


def test_game_mode_non_ascii_text_falls_back_to_pynput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.type_text("哈囉 world")
    assert pdi.ops == []
    assert kb.ops == [("type", "哈囉 world")]


def test_literal_chat_text_bypasses_layout_dependent_key_typing():
    sent = []
    pdi, kb = SpyPdi(), SpyKeyboard()
    backend = Win32InputBackend(game_input_mode=True, pdi=pdi, keyboard=kb,
                                mouse=SpyMouse(), literal_typer=sent.append)
    backend.type_text_literal('測試 - achenxi')
    assert sent == ['測試 - achenxi']
    assert pdi.ops == [] and kb.ops == []


def test_game_mode_uppercase_or_symbol_falls_back_to_pynput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.type_text("GG!")
    assert kb.ops == [("type", "GG!")]
    assert pdi.ops == []


def test_game_mode_drag_uses_pdi_with_settles():
    backend, pdi, _, mouse, sleeps = make_game_backend()
    backend.mouse_drag(10, 20, 30, 40, MouseButton.LEFT)
    assert pdi.ops == [
        ("moveTo", 10, 20), ("mouseDown", "left"),
        ("moveTo", 30, 40), ("mouseUp", "left"),
    ]
    assert sleeps == [0.05, 0.05, 0.05]
    assert mouse.ops == []


def test_game_mode_click_settles_after_move():
    backend, pdi, _, _, sleeps = make_game_backend()
    backend.mouse_click(100, 200)
    assert pdi.ops == [("moveTo", 100, 200), ("click", "left")]
    assert sleeps == [0.05]


def test_game_mode_key_down_and_key_up_use_pydirectinput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.key_down("a")
    backend.key_up("a")
    assert pdi.ops == [("keyDown", "a"), ("keyUp", "a")]
    assert kb.ops == []       # 不走 pynput


def test_game_mode_key_combo_holds_before_release():
    backend, _pdi, _kb, _mouse, sleeps = make_game_backend()
    backend.key_combo(["ctrl", "c"])
    assert sleeps == [0.04]        # keyDown 全部後停留再 keyUp


def test_window_message_mode_all_arrows_use_correct_vk_scan_and_extended_flag():
    backend, user32, kb, _mouse, sleeps = make_message_backend()

    for key in ("up", "down", "left", "right"):
        backend.key_press(key, hold_ms=500)

    assert kb.ops == []
    assert sleeps == [0.5, 0.5, 0.5, 0.5]
    expected = [(0x26, 0x48), (0x28, 0x50), (0x25, 0x4B), (0x27, 0x4D)]
    assert len(user32.ops) == 8
    for i, (vk, scan) in enumerate(expected):
        down = user32.ops[i * 2]
        up = user32.ops[i * 2 + 1]
        assert down[:3] == (0x1234, 0x0100, vk)  # WM_KEYDOWN
        assert up[:3] == (0x1234, 0x0101, vk)    # WM_KEYUP
        assert (down[3] >> 16) & 0xFF == scan
        assert (up[3] >> 16) & 0xFF == scan
        assert down[3] & (1 << 24)               # extended-key bit
        assert up[3] & (1 << 24)
        assert not down[3] & ((1 << 30) | (1 << 31))
        assert up[3] & (1 << 30)                 # previous state
        assert up[3] & (1 << 31)                 # transition state


def test_window_message_mode_repeats_all_arrows_as_held_keydown():
    backend, user32, _kb, _mouse, _sleeps = make_message_backend()

    for key in ("up", "down", "left", "right"):
        backend.key_down(key)
        backend.key_repeat(key)
        backend.key_up(key)

    expected_vks = (0x26, 0x28, 0x25, 0x27)
    assert len(user32.ops) == 12
    for i, vk in enumerate(expected_vks):
        down, repeated, up = user32.ops[i * 3:i * 3 + 3]
        assert down[:3] == (0x1234, 0x0100, vk)
        assert repeated[:3] == (0x1234, 0x0100, vk)
        assert up[:3] == (0x1234, 0x0101, vk)
        assert not down[3] & (1 << 30)            # 首次按下：previous state=0
        assert repeated[3] & (1 << 30)            # 自動重複：previous state=1
        assert not repeated[3] & (1 << 31)        # 仍是 key-down
        assert up[3] & ((1 << 30) | (1 << 31))


def test_scan_pulse_mode_pulses_all_arrows_with_release_gap():
    backend, pdi, kb, _mouse, sleeps = make_scan_pulse_backend()

    for key in ("up", "down", "left", "right"):
        backend.key_down(key)
        consumed = backend.key_repeat(key)
        backend.key_up(key)
        assert consumed == pytest.approx(0.012)

    assert pdi.ops == [
        op
        for key in ("up", "down", "left", "right")
        for op in (("keyDown", key), ("keyUp", key),
                   ("keyDown", key), ("keyUp", key))
    ]
    assert sleeps == [0.012] * 4
    assert backend.key_repeat_interval("up") == pytest.approx(0.018)
    assert kb.ops == []


def test_window_message_mode_refuses_to_send_when_target_is_not_foreground():
    backend, user32, _kb, _mouse, _sleeps = make_message_backend(foreground=0x9999)

    with pytest.raises(RuntimeError, match="前景"):
        backend.key_press("up")

    assert user32.ops == []


def test_window_message_mode_releases_held_key_if_focus_changes():
    backend, user32, _kb, _mouse, _sleeps = make_message_backend()
    backend.key_down("up")
    user32.foreground = 0x9999

    backend.key_up("up")

    assert [op[1] for op in user32.ops] == [0x0100, 0x0101]


def test_window_message_mode_requires_bound_target_window():
    user32 = SpyUser32()
    backend = Win32InputBackend(
        window_message_mode=True, user32=user32,
        keyboard=SpyKeyboard(), mouse=SpyMouse(), sleep=lambda _s: None)

    with pytest.raises(RuntimeError, match="目標視窗"):
        backend.key_press("down")


def test_window_message_and_game_modes_are_mutually_exclusive():
    with pytest.raises(ValueError, match="不能同時"):
        Win32InputBackend(
            game_input_mode=True, window_message_mode=True,
            pdi=SpyPdi(), user32=SpyUser32(),
            keyboard=SpyKeyboard(), mouse=SpyMouse())


@pytest.mark.parametrize("modes", [
    {"game_input_mode": True, "scan_pulse_mode": True},
    {"window_message_mode": True, "scan_pulse_mode": True},
])
def test_scan_pulse_mode_is_mutually_exclusive(modes):
    with pytest.raises(ValueError, match="不能同時"):
        Win32InputBackend(
            **modes, pdi=SpyPdi(), user32=SpyUser32(),
            keyboard=SpyKeyboard(), mouse=SpyMouse())


# --- 數字鍵盤（與主鍵盤數字是不同的實體鍵，遊戲常分別綁定） ---

class SpyPdiWithMapping(SpyPdi):
    """帶 KEYBOARD_MAPPING 的 Spy：真實 pdi 有這張表，backend 會往裡面補 numpad。"""

    def __init__(self):
        super().__init__()
        # 真實 pdi 有 add/subtract/multiply/divide/decimal 但沒有 num0-num9
        self.KEYBOARD_MAPPING = {
            "add": 0x4E, "subtract": 0x4A, "multiply": 0x37,
            "divide": 0x4B5, "decimal": 0x53, "apps": 0x15D, "7": 0x08,
        }


def test_game_mode_registers_missing_numpad_scancodes():
    """pdi 沒有 num0-num9，backend 要補上掃描碼，否則按 numpad 會靜默什麼都不做。"""
    pdi = SpyPdiWithMapping()
    Win32InputBackend(game_input_mode=True, pdi=pdi,
                      keyboard=SpyKeyboard(), mouse=SpyMouse())
    assert pdi.KEYBOARD_MAPPING["num7"] == 0x47
    assert pdi.KEYBOARD_MAPPING["num0"] == 0x52
    # 已存在的鍵名不覆蓋（尊重 pdi 自己的定義）
    assert pdi.KEYBOARD_MAPPING["decimal"] == 0x53


def test_game_mode_translates_numpad_symbol_names_to_pdi_names():
    backend, pdi, _, _, _ = make_game_backend()
    for name, expected in [("num+", "add"), ("num-", "subtract"),
                           ("num*", "multiply"), ("num/", "divide"),
                           ("num.", "decimal"), ("menu", "apps")]:
        pdi.ops.clear()
        backend.key_press(name)
        assert pdi.ops == [("keyDown", expected), ("keyUp", expected)], name


def test_game_mode_numpad_digit_is_not_main_row_digit():
    backend, pdi, _, _, _ = make_game_backend()
    backend.key_press("num7")
    backend.key_press("7")
    assert pdi.ops == [("keyDown", "num7"), ("keyUp", "num7"),
                       ("keyDown", "7"), ("keyUp", "7")]


def test_message_mode_sends_numpad_vk():
    backend, user32, _, _, _ = make_message_backend()
    backend.key_press("num7")
    vks = [op[2] for op in user32.ops]
    assert vks == [0x67, 0x67]          # VK_NUMPAD7，非主鍵盤 7 的 0x37
