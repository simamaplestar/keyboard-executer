"""Darwin 沒有 Windows 系統鍵，不能因此讓整個鍵盤模組無法匯入。"""
import enum
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pynput.keyboard import Key, KeyCode


@pytest.fixture
def mac_keymap(monkeypatch):
    # 與 pynput.keyboard._darwin.Key 相同的支援範圍；保留 host 的 KeyCode
    # 實作，測試不需要 Cocoa 或實際送出任何鍵盤事件。
    unavailable = {"insert", "num_lock", "scroll_lock", "print_screen", "pause", "menu"}
    mac_keys = enum.Enum("Key", {
        name: key.value for name, key in Key.__members__.items()
        if name not in unavailable
    })
    path = (Path(__file__).resolve().parents[2] / "src/keyboard_executor"
            / "platforms/common/keymap.py")
    spec = importlib.util.spec_from_file_location("mac_keymap_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        patch.setitem(sys.modules, "pynput.keyboard",
                      SimpleNamespace(Key=mac_keys, KeyCode=KeyCode))
        spec.loader.exec_module(module)
    return module, mac_keys


def test_mac_keymap_imports_and_round_trips_command_and_function_keys(mac_keymap):
    keymap, keys = mac_keymap
    assert keymap.parse_key("cmd") is keys.cmd
    assert keymap.key_to_name(keys.cmd_r) == "cmd"
    assert keymap.parse_key("f10") is keys.f10
    assert keymap.key_to_name(keymap.parse_key("num7")) == "num7"
    assert keymap.parse_key("num7") != keymap.parse_key("7")


@pytest.mark.parametrize("name", ["insert", "numlock", "scrolllock", "printscreen", "pause", "menu"])
def test_mac_windows_only_key_reports_platform_limitation(mac_keymap, name):
    keymap, _ = mac_keymap
    with pytest.raises(ValueError, match="此平台不支援"):
        keymap.parse_key(name)
