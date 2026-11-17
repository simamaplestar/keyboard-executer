"""Windows canonical key name → virtual-key code helpers.

Kept in the platform layer so global hotkeys and the foreground-window message
backend share one authoritative mapping without making platforms depend on Qt.
"""
from __future__ import annotations

_VK_SPECIAL = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "printscreen": 0x2C, "pause": 0x13, "menu": 0x5D,
}

# 數字鍵盤 VK：與主鍵盤數字是不同的實體鍵（主鍵盤 7 是 0x37，numpad 7 是 0x67）。
# 錄製端靠這組 VK 才分得出兩者——NumLock 開啟時作業系統對兩者回報相同字元。
NUMPAD_VK: dict[str, int] = {
    **{f"num{i}": 0x60 + i for i in range(10)},
    "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
}

_VK_MODIFIERS = {
    "ctrl": 0x11, "control": 0x11,
    "shift": 0x10,
    "alt": 0x12, "option": 0x12,
    "win": 0x5B, "super": 0x5B, "cmd": 0x5B,
}


def vk_for_key(name: str) -> int | None:
    """Canonical key name → Windows VK; unmappable names return ``None``."""
    n = name.strip().lower()
    if n in _VK_MODIFIERS:
        return _VK_MODIFIERS[n]
    if n in _VK_SPECIAL:
        return _VK_SPECIAL[n]
    if n in NUMPAD_VK:
        return NUMPAD_VK[n]
    if n.startswith("f") and n[1:].isdigit():
        num = int(n[1:])
        if 1 <= num <= 24:
            return 0x70 + (num - 1)
    if len(n) == 1:
        ch = n.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    return None


def hotkey_to_vks(hotkey: str) -> list[int] | None:
    """Hotkey string such as ``ctrl+shift+1`` → VK list."""
    parts = [p for p in (hotkey or "").split("+") if p.strip()]
    if not parts:
        return None
    result = [vk_for_key(p) for p in parts]
    if any(vk is None for vk in result):
        return None
    return [int(vk) for vk in result]
