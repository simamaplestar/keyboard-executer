"""Literal text via Windows Unicode packets, independent of keyboard layout.

KEYEVENTF_UNICODE produces VK_PACKET/WM_CHAR instead of physical letter keys:
https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-keybdinput
"""
from __future__ import annotations

import ctypes


class _KeyboardInput(ctypes.Structure):
    _fields_ = [('wVk', ctypes.c_uint16), ('wScan', ctypes.c_uint16),
                ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32),
                ('dwExtraInfo', ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):
    # INPUT's union must include its largest member even for keyboard input.
    _fields_ = [('dx', ctypes.c_int32), ('dy', ctypes.c_int32),
                ('mouseData', ctypes.c_uint32), ('dwFlags', ctypes.c_uint32),
                ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [('ki', _KeyboardInput), ('mi', _MouseInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', ctypes.c_uint32), ('value', _InputUnion)]


def send_unicode_text(text: str, *, send_input=None) -> None:
    encoded = text.encode('utf-16-le')
    if not encoded:
        return
    units = [int.from_bytes(encoded[i:i+2], 'little') for i in range(0, len(encoded), 2)]
    events = (_Input * (2 * len(units)))()
    for i, unit in enumerate(units):
        for offset, flags in ((0, 0x0004), (1, 0x0004 | 0x0002)):
            event = events[2*i+offset]
            event.type = 1  # INPUT_KEYBOARD
            event.ki = _KeyboardInput(0, unit, flags, 0, 0)
    if send_input is None:
        # pydirectinput also uses windll.user32.SendInput with its own INPUT
        # type. An independent DLL wrapper avoids changing that shared ctypes
        # signature and breaking the next Enter/key release.
        send_input = ctypes.WinDLL('user32', use_last_error=True).SendInput
        send_input.argtypes = [ctypes.c_uint32, ctypes.POINTER(_Input), ctypes.c_int]
        send_input.restype = ctypes.c_uint32
    sent = send_input(len(events), events, ctypes.sizeof(_Input))
    if sent != len(events):
        # Never retype a partly delivered string: the caller must preserve it.
        raise RuntimeError(f'文字輸入未完成 ({sent}/{len(events)}), 請檢查目標視窗與權限')
