import sys

import pytest

from keyboard_executor.app.global_hotkey import vk_for_key


def test_vk_for_key_mapping():
    assert vk_for_key("f1") == 0x70
    assert vk_for_key("f10") == 0x79
    assert vk_for_key("f24") == 0x87
    assert vk_for_key("end") == 0x23
    assert vk_for_key("home") == 0x24
    assert vk_for_key("a") == ord("A")
    assert vk_for_key("K") == ord("K")        # 大小寫皆可
    assert vk_for_key("5") == ord("5")
    assert vk_for_key("f25") is None          # 超出 F1–F24
    assert vk_for_key("nope") is None


def test_vk_for_key_modifiers():
    assert vk_for_key("ctrl") == 0x11
    assert vk_for_key("control") == 0x11
    assert vk_for_key("shift") == 0x10
    assert vk_for_key("alt") == 0x12
    assert vk_for_key("win") == 0x5B
    assert vk_for_key("super") == 0x5B
    assert vk_for_key("cmd") == 0x5B


def test_hotkey_to_vks():
    from keyboard_executor.app.global_hotkey import hotkey_to_vks
    assert hotkey_to_vks("ctrl+shift+1") == [0x11, 0x10, 0x31]
    assert hotkey_to_vks("f5") == [0x74]
    assert hotkey_to_vks("shift+a+right") == [0x10, ord("A"), 0x27]
    assert hotkey_to_vks("ctrl+nope") is None
    assert hotkey_to_vks("") is None
    assert hotkey_to_vks("  ") is None


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey 僅 Windows")
def test_windows_hotkey_register_unregister():
    from keyboard_executor.app.global_hotkey import WindowsHotkey
    hk = WindowsHotkey(lambda: None)
    assert hk.register("f24") is True         # 冷門鍵，應可註冊
    hk.unregister()
    assert hk.register("nope") is False       # 無法對應的鍵名
