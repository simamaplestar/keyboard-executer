"""core 層測試用的平台假實作。"""
from __future__ import annotations

import re
from typing import Callable

import numpy as np

from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.base import (
    InputBackend,
    InputEvent,
    InputHook,
    MouseButton,
    OcrEngine,
    ScreenCapture,
    TextBox,
    WindowInfo,
    WindowManager,
)


class FakeInputBackend(InputBackend):
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.target_windows: list[WindowInfo] = []

    def set_target_window(self, window: WindowInfo | None) -> None:
        if window is not None:
            self.target_windows.append(window)

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        self.calls.append(("key_press", key, hold_ms))

    def key_down(self, key: str) -> None:
        self.calls.append(("key_down", key))

    def key_up(self, key: str) -> None:
        self.calls.append(("key_up", key))

    def key_combo(self, keys: list[str]) -> None:
        self.calls.append(("key_combo", keys))

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def mouse_move(self, x: int, y: int) -> None:
        self.calls.append(("mouse_move", x, y))

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        self.calls.append(("mouse_click", x, y, button, count))

    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None:
        self.calls.append(("mouse_drag", from_x, from_y, to_x, to_y, button))

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.calls.append(("scroll", x, y, dx, dy))


class FakeWindowManager(WindowManager):
    def __init__(self, windows: list[WindowInfo]) -> None:
        self.windows = list(windows)
        self.activated: list[WindowInfo] = []
        self.activate_result = True

    def list_all(self) -> list[WindowInfo]:
        return list(self.windows)

    def find_windows(
        self, title_pattern: str | None = None, app_name: str | None = None
    ) -> list[WindowInfo]:
        result = []
        for w in self.windows:
            if title_pattern and not re.search(title_pattern, w.title):
                continue
            if app_name and w.app_name.lower() != app_name.lower():
                continue
            result.append(w)
        return result

    def activate(self, window: WindowInfo, timeout_ms: int = 3000) -> bool:
        self.activated.append(window)
        return self.activate_result

    def refresh(self, window: WindowInfo) -> WindowInfo | None:
        return window if window in self.windows else None

    def is_alive(self, window: WindowInfo) -> bool:
        return window in self.windows


class FakeInputHook(InputHook):
    """測試用輸入監聽：不開真實 listener，由測試以 push() 注入事件。"""

    def __init__(self) -> None:
        self.on_event: Callable[[InputEvent], None] | None = None
        self.started = 0
        self.stopped = 0

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        self.on_event = on_event
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def push(self, event: InputEvent) -> None:
        assert self.on_event is not None, "hook 尚未 start"
        self.on_event(event)


class FakeScreenCapture(ScreenCapture):
    """測試用截圖：capture 記錄請求的 region、回傳注入影像；scale_factor 回傳注入值。"""

    def __init__(self, image=None, scale: float = 1.0) -> None:
        self.image = image if image is not None else np.zeros((1, 1, 3), dtype=np.uint8)
        self._scale = scale
        self.captures: list[Rect] = []

    def capture(self, region: Rect):
        self.captures.append(region)
        return self.image

    def scale_factor(self) -> float:
        return self._scale


class FakeOcrEngine(OcrEngine):
    """測試用 OCR：recognize 回傳注入的 TextBox 清單。

    boxes 為單一 list[TextBox]（每輪都回同一份），或 list[list[TextBox]]
    佇列（逐輪 pop(0) 供輪詢測試；耗盡後持續回傳最後一份）。
    """

    def __init__(self, boxes=None) -> None:
        self._boxes = boxes if boxes is not None else []
        self._queued = bool(boxes) and isinstance(boxes[0], list)
        self.calls: list = []

    def recognize(self, image) -> list[TextBox]:
        self.calls.append(image)
        if not self._queued:
            return list(self._boxes)
        if len(self._boxes) > 1:
            return self._boxes.pop(0)
        return list(self._boxes[0]) if self._boxes else []
