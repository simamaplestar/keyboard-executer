"""平台抽象介面。唯一允許出現 OS 判斷的層是 platforms/，core 層只依賴這些抽象。

M1 完整實作：InputBackend、WindowManager。
M2 實作：InputHook（此處先鎖定契約）。
M3 實作：ScreenCapture、OcrEngine（此處先鎖定契約）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from keyboard_executor.core.geometry import Rect


@dataclass(frozen=True)
class WindowInfo:
    handle: Any        # 平台原生視窗物件/識別，只供 platforms 層內部使用
    title: str
    app_name: str
    x: int             # 視窗左上角螢幕絕對座標（平台輸入座標單位：Windows 為實體像素、
                       # macOS 為 Cocoa 點，與 region_math 一致）
    y: int
    width: int
    height: int
    is_active: bool


class MouseButton(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class EventKind(StrEnum):
    """全域監聽事件類型。"""
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_MOVE = "mouse_move"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    SCROLL = "scroll"


@dataclass(frozen=True)
class InputEvent:
    """全域監聽事件。key 為 canonical 按鍵名稱（keymap.key_to_name 產出）；
    x/y 為螢幕絕對座標（平台輸入座標單位，見 core/geometry.py）。"""
    kind: EventKind
    timestamp_ms: int
    key: str | None = None
    x: int | None = None
    y: int | None = None
    button: MouseButton | None = None
    dx: int = 0
    dy: int = 0


@dataclass(frozen=True)
class TextBox:
    """OCR 辨識結果；座標為輸入影像內的像素座標。"""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float


class InputBackend(ABC):
    """模擬鍵盤滑鼠。滑鼠座標一律為螢幕絕對座標（相對→絕對換算是呼叫端的責任）。"""

    def set_target_window(self, window: WindowInfo | None) -> None:
        """告知後端目前腳本的目標視窗；一般全域輸入後端不需處理。"""
        del window

    @abstractmethod
    def key_press(self, key: str, hold_ms: int = 0) -> None: ...

    @abstractmethod
    def key_down(self, key: str) -> None: ...

    @abstractmethod
    def key_up(self, key: str) -> None: ...

    def key_repeat_interval(self, key: str) -> float | None:
        """要求 Player 在長按時重送 key-down 的間隔；一般後端不需要。"""
        del key
        return None

    def key_repeat(self, key: str) -> float:
        """重複已按住的鍵，回傳後端內部已耗用秒數；一般後端不處理。"""
        del key
        return 0.0

    @abstractmethod
    def key_combo(self, keys: list[str]) -> None: ...

    def key_combo_down(self, keys: list[str]) -> None:
        """依序按下全部鍵（不放開）。按住多久由呼叫端掌控。"""
        for k in keys:
            self.key_down(k)

    def key_combo_up(self, keys: list[str]) -> None:
        """反序放開全部鍵。"""
        for k in reversed(keys):
            self.key_up(k)

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    def type_text_literal(self, text: str) -> None:
        """Insert chat text literally; platforms may avoid layout/IME keystrokes."""
        self.type_text(text)

    @abstractmethod
    def mouse_move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None: ...

    def mouse_click_checked(self, x: int, y: int, button: MouseButton = MouseButton.LEFT,
                            count: int = 1, *, check: Callable[[], None],
                            before_click: Callable[[], None] | None = None,
                            hold_ms: int = 0) -> None:
        """Guarded click. Native backends support held clicks for polling games;
        adapters without press/release fall back to their ordinary click.
        """
        check()
        if before_click is not None:
            before_click()
        self.mouse_click(x, y, button, count)

    @abstractmethod
    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None: ...

    @abstractmethod
    def scroll(self, x: int, y: int, dx: int, dy: int) -> None: ...

    def mouse_drag_checked(self, from_x, from_y, to_x, to_y, button=MouseButton.LEFT,
                           *, check, before_press=None):
        """Optional guarded drag: unsupported adapters must fail closed."""
        raise NotImplementedError('此輸入後端不支援可中斷拖曳')

    def scroll_checked(self, x, y, dx, dy, *, check):
        raise NotImplementedError('此輸入後端不支援可中斷捲動')


class InputHook(ABC):
    """全域輸入監聽（錄製與熱鍵用）。"""

    @abstractmethod
    def start(self, on_event: Callable[[InputEvent], None]) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class WindowManager(ABC):
    @abstractmethod
    def list_all(self) -> list[WindowInfo]: ...

    @abstractmethod
    def find_windows(
        self, title_pattern: str | None = None, app_name: str | None = None
    ) -> list[WindowInfo]:
        """title_pattern 為 regex（re.search）；app_name 為不分大小寫的完全比對。兩者皆給時取交集。"""
        ...

    @abstractmethod
    def activate(self, window: WindowInfo, timeout_ms: int = 3000) -> bool:
        """把視窗拉到前景並等待取得焦點；逾時回傳 False。"""
        ...

    @abstractmethod
    def refresh(self, window: WindowInfo) -> WindowInfo | None:
        """重新查詢視窗幾何；視窗已關閉時回傳 None。"""
        ...

    @abstractmethod
    def is_alive(self, window: WindowInfo) -> bool:
        """輕量存活檢查：只確認視窗還在，不重新查詢幾何或應用程式名稱
        （macOS 的 getAppName 是百 ms 級 AppleScript，鍵盤動作前勿用 refresh）。"""
        ...


class ScreenCapture(ABC):
    @abstractmethod
    def capture(self, region: Rect) -> Any:
        """擷取螢幕區域，呼叫端一律傳入螢幕絕對「實體像素」座標（region 契約對所有
        core 呼叫端與後端保持穩定）。個別後端可能需要把實體像素換算成自己 API 要的
        單位（例如 mss 的 grab() 在所有平台上都以「點」解讀 region，mss 適配器
        （platforms/common/capture_mss.py）因此在內部先 ÷ scale_factor() 換算再呼叫
        grab）。回傳影像的實際解析度依後端而定，其與呼叫端座標系的比例由
        scale_factor() 量測回報，不在此方法的回傳值中另行標示。"""
        ...

    @abstractmethod
    def scale_factor(self) -> float:
        """螢幕實體像素 / 輸入座標點的比值：Windows 為 1.0；Retina 為 2.0。
        呼叫端據此把「點」單位的視窗/區域幾何換算為 mss 擷取用的實體像素。"""
        ...


class OcrRecognitionError(RuntimeError):
    """Inference failed after initialization; not a missing/invalid model error."""


class OcrEngine(ABC):
    @abstractmethod
    def recognize(self, image: Any) -> list[TextBox]:
        """辨識影像中的文字。M3 實作。"""
        ...
