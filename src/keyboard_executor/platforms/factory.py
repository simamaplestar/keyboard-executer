"""平台工廠：整個程式唯一依 sys.platform 分派的進入點。"""
from __future__ import annotations

import sys
import logging
from dataclasses import dataclass

from keyboard_executor.platforms.base import (
    InputBackend,
    OcrEngine,
    ScreenCapture,
    WindowManager,
)


@dataclass(frozen=True)
class Platform:
    input_backend: InputBackend
    window_manager: WindowManager
    screen_capture: ScreenCapture | None = None
    ocr_engine: OcrEngine | None = None


def get_platform(game_input_mode: bool = False, window_message_mode: bool = False,
                 scan_pulse_mode: bool = False,
                 ocr_lang: str | None = None,
                 _sys_platform: str | None = None) -> Platform:
    # Retain the old argument for settings/callers, not model selection.
    del ocr_lang
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
    plat = _sys_platform if _sys_platform is not None else sys.platform
    if plat == "win32":
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
        from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager
        from keyboard_executor.platforms.win32.dpi import ensure_dpi_awareness
        from keyboard_executor.platforms.win32.foreground import force_foreground
        from keyboard_executor.platforms.win32.input import Win32InputBackend

        ensure_dpi_awareness()
        return Platform(
            input_backend=Win32InputBackend(
                game_input_mode=game_input_mode,
                window_message_mode=window_message_mode,
                scan_pulse_mode=scan_pulse_mode),
            window_manager=PywinctlWindowManager(force_foreground=force_foreground),
            screen_capture=MssScreenCapture(),
            ocr_engine=RapidOcrEngine(),
        )
    if plat == "darwin":
        if game_input_mode or window_message_mode or scan_pulse_mode:
            logging.getLogger(__name__).warning(
                "腳本的 Windows 輸入模式不適用 macOS，改用 macOS 標準輸入")
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
        from keyboard_executor.platforms.common.input_pynput import PynputInputBackend
        from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager

        return Platform(
            input_backend=PynputInputBackend(),
            window_manager=PywinctlWindowManager(),
            screen_capture=MssScreenCapture(),
            ocr_engine=RapidOcrEngine(),
        )
    raise RuntimeError(f"不支援的平台: {plat}")
