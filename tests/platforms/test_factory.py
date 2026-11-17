import sys

import pytest

from keyboard_executor.platforms.factory import Platform, get_platform


@pytest.mark.parametrize("options", [
    {"game_input_mode": True}, {"window_message_mode": True}, {"scan_pulse_mode": True},
])
def test_windows_script_uses_standard_backend_on_mac(options, caplog):
    from keyboard_executor.platforms.common.input_pynput import PynputInputBackend
    from unittest.mock import patch

    with patch("keyboard_executor.platforms.common.input_pynput.KeyboardController"), \
         patch("keyboard_executor.platforms.common.input_pynput.MouseController"):
        platform = get_platform(_sys_platform="darwin", **options)
    assert isinstance(platform.input_backend, PynputInputBackend)
    assert "macOS" in caplog.text


def test_unsupported_platform_raises():
    with pytest.raises(RuntimeError, match="不支援的平台"):
        get_platform(_sys_platform="linux")


@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_returns_pynput_and_pywinctl():
    from keyboard_executor.platforms.common.input_pynput import PynputInputBackend
    from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager

    platform = get_platform()
    assert isinstance(platform, Platform)
    assert isinstance(platform.input_backend, PynputInputBackend)
    assert isinstance(platform.window_manager, PywinctlWindowManager)


@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_returns_win32_backend():
    from keyboard_executor.platforms.win32.input import Win32InputBackend

    platform = get_platform()
    assert isinstance(platform.input_backend, Win32InputBackend)


@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_window_message_mode_reaches_backend():
    platform = get_platform(window_message_mode=True)
    assert platform.input_backend._window_message_mode is True


@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_scan_pulse_mode_reaches_backend():
    platform = get_platform(scan_pulse_mode=True)
    assert platform.input_backend._scan_pulse_mode is True


@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_wires_rapid_ocr_engine():
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine

    platform = get_platform()
    assert isinstance(platform.ocr_engine, RapidOcrEngine)
    assert isinstance(get_platform(ocr_lang='en').ocr_engine, RapidOcrEngine)


@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_wires_screen_capture():
    from keyboard_executor.platforms.common.capture_mss import MssScreenCapture

    platform = get_platform()
    assert isinstance(platform.screen_capture, MssScreenCapture)


@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_wires_ocr_engine():
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine

    platform = get_platform()
    assert isinstance(platform.ocr_engine, RapidOcrEngine)


@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_legacy_language_does_not_select_another_model():
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
    platform = get_platform(ocr_lang='japan')
    assert isinstance(platform.ocr_engine, RapidOcrEngine)
    assert platform.ocr_engine._engine is None


@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_wires_force_foreground_into_window_manager():
    from keyboard_executor.platforms.win32.foreground import force_foreground
    platform = get_platform()
    assert platform.window_manager._force_foreground is force_foreground
