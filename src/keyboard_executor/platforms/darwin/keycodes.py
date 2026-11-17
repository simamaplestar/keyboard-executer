"""macOS virtual key codes（Carbon ``kVK_*``）。

目前只需要數字鍵盤：pynput 沒有 numpad 專屬的 ``Key`` 成員，錄製端要分辨
「numpad 7」與「主鍵盤 7」只能靠 vk（見 platforms/common/keymap.py）。
與 win32/keycodes.py 的 ``NUMPAD_VK`` 同名同形狀，由 keymap 依平台擇一載入。

值取自 Apple HIToolbox 的 ``Events.h``（kVK_ANSI_Keypad*）。**未在 macOS 實機
驗證**——本專案目前只在 Windows 實機建置與驗收（見 packaging/README.md）。
"""
from __future__ import annotations

NUMPAD_VK: dict[str, int] = {
    "num0": 0x52, "num1": 0x53, "num2": 0x54, "num3": 0x55, "num4": 0x56,
    "num5": 0x57, "num6": 0x58, "num7": 0x59, "num8": 0x5B, "num9": 0x5C,
    "num*": 0x43,   # kVK_ANSI_KeypadMultiply
    "num+": 0x45,   # kVK_ANSI_KeypadPlus
    "num-": 0x4E,   # kVK_ANSI_KeypadMinus
    "num.": 0x41,   # kVK_ANSI_KeypadDecimal
    "num/": 0x4B,   # kVK_ANSI_KeypadDivide
}
