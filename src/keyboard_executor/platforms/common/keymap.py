"""腳本按鍵名稱（字串）→ pynput 按鍵物件的映射。

名稱集合必須與 core/keynames.py 的 SPECIAL_KEY_NAMES 一致
（tests/platforms/test_keymap.py 以集合相等測試鎖定）；新增按鍵時兩邊都要改。

數字鍵盤是唯一需要平台分派的部分：pynput 沒有 numpad 專屬的 Key 成員，只能靠
vk 分辨「numpad 7」與「主鍵盤 7」，而 vk 是平台專屬編碼，故對照表放在各平台
模組（win32/keycodes.py、darwin/keycodes.py），此處依平台擇一載入。
"""
from __future__ import annotations

import sys

from pynput.keyboard import Key, KeyCode

if sys.platform == "darwin":
    from keyboard_executor.platforms.darwin.keycodes import NUMPAD_VK
else:
    from keyboard_executor.platforms.win32.keycodes import NUMPAD_VK

_SPECIAL: dict[str, Key] = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "option": Key.alt,
    "cmd": Key.cmd,
    "win": Key.cmd,
    "super": Key.cmd,
    "enter": Key.enter,
    "return": Key.enter,
    "esc": Key.esc,
    "escape": Key.esc,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "home": Key.home,
    "end": Key.end,
    "pageup": Key.page_up,
    "pagedown": Key.page_down,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "capslock": Key.caps_lock,
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 21)},
}

# Darwin 的 Key enum 沒有這些 Windows 系統鍵。不得在模組匯入時取不存在的
# 屬性；也不映射成另一顆鍵，避免匯入腳本後送出非預期輸入。
_OPTIONAL_KEYS = {
    "insert": "insert", "numlock": "num_lock", "scrolllock": "scroll_lock",
    "printscreen": "print_screen", "pause": "pause", "menu": "menu",
}
UNSUPPORTED_KEYS = {name for name, member in _OPTIONAL_KEYS.items()
                    if not hasattr(Key, member)}
_SPECIAL.update({name: getattr(Key, member) for name, member in _OPTIONAL_KEYS.items()
                 if name not in UNSUPPORTED_KEYS})


def parse_key(name: str) -> Key | KeyCode:
    n = name.strip().lower()
    if n in UNSUPPORTED_KEYS:
        raise ValueError(f"此平台不支援的按鍵: {name!r}")
    if n in _SPECIAL:
        return _SPECIAL[n]
    if n in NUMPAD_VK:
        return KeyCode.from_vk(NUMPAD_VK[n])   # pynput 無 numpad Key，只能用 vk
    if len(n) == 1:
        return KeyCode.from_char(n)
    raise ValueError(f"無法辨識的按鍵名稱: {name!r}")


def parse_combo(combo: str | list[str]) -> list[Key | KeyCode]:
    keys = combo.split("+") if isinstance(combo, str) else combo
    return [parse_key(k) for k in keys]


# 修飾鍵左右變體 → canonical 名稱（錄製反查用）
_MODIFIER_VARIANTS: dict[Key, str] = {
    Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.shift_l: "shift", Key.shift_r: "shift",
    Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
    Key.cmd_l: "cmd", Key.cmd_r: "cmd",
}

# Key → canonical 名稱：取 _SPECIAL 中第一個映射到該 Key 的名稱
#（_SPECIAL 的插入順序保證 canonical 名在別名之前，如 ctrl 在 control 之前）
_CANONICAL_NAME: dict[Key, str] = {}
for _name, _key in _SPECIAL.items():
    _CANONICAL_NAME.setdefault(_key, _name)

# vk → 名稱（錄製反查）。numpad 必須先於 char 判斷：NumLock 開啟時作業系統對
# numpad 7 與主鍵盤 7 回報相同的 char='7'，只有 vk 分得出來。
_VK_TO_NUMPAD: dict[int, str] = {vk: name for name, vk in NUMPAD_VK.items()}


def is_numpad(key) -> bool:
    """按鍵是否來自數字鍵盤（以 vk 判定）。

    錄製端用來擋掉 canonical 正規化：Windows 的 canonical 對帶 scan code 的
    KeyCode 會回傳 KeyCode.from_char(char)（keyboard/_win32.py:395），vk 隨之
    遺失，numpad 7 就退化成主鍵盤 7。
    """
    return getattr(key, "vk", None) in _VK_TO_NUMPAD


def key_to_name(key: Key | KeyCode | None) -> str | None:
    """pynput 按鍵物件 → canonical 按鍵名稱；不支援的鍵回傳 None（呼叫端略過）。"""
    if isinstance(key, KeyCode):
        numpad = _VK_TO_NUMPAD.get(getattr(key, "vk", None))
        if numpad is not None:
            return numpad
        char = key.char
        if not char:
            return None
        # 修飾鍵按住時 pynput 可能回報控制字元（Ctrl+S → '\x13'）：折回原字母
        if len(char) == 1 and "\x01" <= char <= "\x1a":
            return chr(ord(char) + 96)
        if char.isprintable():
            return char.lower()
        return None
    if isinstance(key, Key):
        if key in _MODIFIER_VARIANTS:
            return _MODIFIER_VARIANTS[key]
        return _CANONICAL_NAME.get(key)
    return None
