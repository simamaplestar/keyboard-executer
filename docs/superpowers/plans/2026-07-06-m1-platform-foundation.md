# M1 平台基礎層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立平台抽象層 + 輸入模擬 + 視窗控制，能以 Python 程式碼對指定視窗執行一段寫死的動作序列（Windows/macOS）。

**Architecture:** 三層架構的最底層。`platforms/base.py` 定義五個抽象介面（本階段完整實作 `InputBackend` 與 `WindowManager`，其餘三個先鎖定契約）。pynput 與 pywinctl 本身跨平台，共用實作放 `platforms/common/`；Windows 專屬（DPI、pydirectinput 遊戲模式）與 macOS 專屬（權限檢查）各放 `win32/`、`darwin/`。所有外部依賴以建構子注入，core 邏輯與包裝層的映射邏輯全部可單元測試。

**Tech Stack:** Python 3.11+、pynput（輸入模擬）、pywinctl（視窗控制）、pydirectinput（Windows 遊戲 scan code）、pytest。

**對應 spec:** `docs/superpowers/specs/2026-07-06-keyboard-executor-design.md` §3、§4、§13-M1。M2–M5 各自另立計畫。

## Global Constraints

- Python `>=3.11`（spec §1；可用 StrEnum、`X | None` 語法）
- src layout：程式碼一律在 `src/keyboard_executor/` 下（spec §4）
- 判斷作業系統（`sys.platform`）只允許出現在 `platforms/` 層（spec §4）
- 座標一律為實體像素；視窗相對座標 = 以目標視窗左上角為原點（spec §5.2、§14）
- 不做任何反偵測、反外掛繞過；輸入只走 SendInput / CGEvent 標準路徑（spec §11）
- 外部依賴（pynput controller、pywinctl 模組、sleep、clock）一律可由建構子注入，預設用真實實作（spec §12 測試策略）
- Commit 訊息用 conventional commits（feat/test/chore/docs）

---

### Task 1: 專案腳手架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/keyboard_executor/__init__.py`
- Create: `src/keyboard_executor/core/__init__.py`
- Create: `src/keyboard_executor/platforms/__init__.py`
- Create: `src/keyboard_executor/platforms/common/__init__.py`
- Create: `src/keyboard_executor/platforms/win32/__init__.py`
- Create: `src/keyboard_executor/platforms/darwin/__init__.py`
- Create: `src/keyboard_executor/storage/__init__.py`
- Create: `tests/__init__.py`（空檔案；讓 `tests` 成為 package，後續才能 `from tests.fakes import ...`）
- Test: `tests/test_sanity.py`

**Interfaces:**
- Consumes: 無
- Produces: 可安裝的套件骨架；`keyboard_executor.__version__: str`

- [ ] **Step 1: 建立 pyproject.toml**

```toml
[project]
name = "keyboard-executor"
version = "0.1.0"
description = "跨平台鍵盤滑鼠自動化工具（模擬/錄製/回放 + OCR 畫面判斷）"
requires-python = ">=3.11"
dependencies = [
    "pynput>=1.7.6",
    "pywinctl>=0.3",
    "pydirectinput>=1.0.4; sys_platform == 'win32'",
    "pyobjc-framework-ApplicationServices>=10.0; sys_platform == 'darwin'",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 建立 .gitignore**

```gitignore
__pycache__/
*.py[cod]
.venv/
venv/
dist/
build/
*.egg-info/
.pytest_cache/
.DS_Store
```

- [ ] **Step 3: 建立套件骨架**

`src/keyboard_executor/__init__.py`：

```python
__version__ = "0.1.0"
```

其餘 `__init__.py`（core、platforms、platforms/common、platforms/win32、platforms/darwin、storage、tests）皆為空檔案。

- [ ] **Step 4: 寫 sanity 測試**

`tests/test_sanity.py`：

```python
import keyboard_executor


def test_package_importable():
    assert keyboard_executor.__version__ == "0.1.0"
```

- [ ] **Step 5: 建立虛擬環境、安裝、跑測試**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -v
```

Expected: `test_package_importable PASSED`（1 passed）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/ tests/
git commit -m "chore: 專案腳手架（src layout + pytest）"
```

---

### Task 2: core 座標系統

**Files:**
- Create: `src/keyboard_executor/core/geometry.py`
- Create: `tests/core/__init__.py`（空檔案）
- Test: `tests/core/test_geometry.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `Point(x: int, y: int)`（frozen dataclass）
  - `Rect(x: int, y: int, width: int, height: int)`（frozen dataclass）
  - `to_absolute(origin: Point, rel: Point) -> Point` — 視窗相對 → 螢幕絕對
  - `to_relative(origin: Point, abs_pt: Point) -> Point` — 螢幕絕對 → 視窗相對
  - `origin` 一律指目標視窗左上角的螢幕絕對座標

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_geometry.py`：

```python
from keyboard_executor.core.geometry import Point, Rect, to_absolute, to_relative


def test_to_absolute_offsets_by_window_origin():
    origin = Point(100, 200)
    assert to_absolute(origin, Point(30, 40)) == Point(130, 240)


def test_to_relative_is_inverse_of_to_absolute():
    origin = Point(100, 200)
    rel = Point(30, 40)
    assert to_relative(origin, to_absolute(origin, rel)) == rel


def test_to_relative_can_be_negative_when_outside_window():
    origin = Point(100, 200)
    assert to_relative(origin, Point(50, 50)) == Point(-50, -150)


def test_rect_holds_geometry():
    r = Rect(10, 20, 300, 400)
    assert (r.x, r.y, r.width, r.height) == (10, 20, 300, 400)


def test_point_is_immutable():
    import dataclasses
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        Point(1, 2).x = 9
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/core/test_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.geometry'`

- [ ] **Step 3: 最小實作**

`src/keyboard_executor/core/geometry.py`：

```python
"""座標系統：所有腳本座標一律為「目標視窗左上角為原點」的相對座標（實體像素）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


def to_absolute(origin: Point, rel: Point) -> Point:
    """視窗相對座標 → 螢幕絕對座標。origin 為視窗左上角的螢幕座標。"""
    return Point(origin.x + rel.x, origin.y + rel.y)


def to_relative(origin: Point, abs_pt: Point) -> Point:
    """螢幕絕對座標 → 視窗相對座標。origin 為視窗左上角的螢幕座標。"""
    return Point(abs_pt.x - origin.x, abs_pt.y - origin.y)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/core/test_geometry.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/geometry.py tests/core/test_geometry.py
git commit -m "feat: 視窗相對座標系統（Point/Rect/換算）"
```

---

### Task 3: 平台抽象介面與測試替身

**Files:**
- Create: `src/keyboard_executor/platforms/base.py`
- Create: `tests/fakes.py`
- Create: `tests/platforms/__init__.py`（空檔案）
- Test: `tests/platforms/test_base.py`

**Interfaces:**
- Consumes: `Point`, `Rect`（Task 2）
- Produces（後續所有任務與 M2–M5 都依賴這些簽名）:
  - `WindowInfo(handle: Any, title: str, app_name: str, x: int, y: int, width: int, height: int, is_active: bool)`（frozen dataclass）
  - `MouseButton`（StrEnum：`LEFT="left"`, `RIGHT="right"`, `MIDDLE="middle"`）
  - `InputEvent(kind, timestamp_ms, key, x, y, button, dx, dy)`（M2 錄製契約）
  - `TextBox(text, x, y, width, height, confidence)`（M3 OCR 契約）
  - 抽象類別：`InputBackend`、`InputHook`、`WindowManager`、`ScreenCapture`、`OcrEngine`（方法簽名見下方程式碼）
  - 測試替身：`FakeInputBackend`（記錄呼叫於 `.calls`）、`FakeWindowManager(windows)`（`.activated` 記錄）

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_base.py`：

```python
from keyboard_executor.platforms.base import MouseButton, WindowInfo
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(title="視窗A", app="AppA", active=False):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=10, y=20, width=800, height=600, is_active=active)


def test_fake_input_backend_records_calls():
    backend = FakeInputBackend()
    backend.key_press("enter")
    backend.key_combo(["ctrl", "s"])
    backend.type_text("哈囉")
    backend.mouse_click(5, 6, MouseButton.RIGHT, count=2)
    assert backend.calls == [
        ("key_press", "enter", 0),
        ("key_combo", ["ctrl", "s"]),
        ("type_text", "哈囉"),
        ("mouse_click", 5, 6, MouseButton.RIGHT, 2),
    ]


def test_fake_window_manager_finds_by_title_regex():
    w1, w2 = make_window("記事本 - 未命名"), make_window("瀏覽器", app="Browser")
    manager = FakeWindowManager([w1, w2])
    assert manager.find_windows(title_pattern="記事") == [w1]
    assert manager.find_windows(title_pattern="不存在") == []


def test_fake_window_manager_finds_by_app_name_case_insensitive():
    w = make_window(app="Notepad")
    manager = FakeWindowManager([w])
    assert manager.find_windows(app_name="notepad") == [w]


def test_fake_window_manager_activate_records_and_succeeds():
    w = make_window()
    manager = FakeWindowManager([w])
    assert manager.activate(w) is True
    assert manager.activated == [w]


def test_fake_window_manager_refresh_returns_none_for_closed_window():
    w = make_window()
    manager = FakeWindowManager([])
    assert manager.refresh(w) is None


def test_mouse_button_values():
    assert MouseButton.LEFT == "left"
    assert MouseButton("right") is MouseButton.RIGHT
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.base'`

- [ ] **Step 3: 實作 base.py**

`src/keyboard_executor/platforms/base.py`：

```python
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
    x: int             # 視窗左上角螢幕絕對座標（實體像素）
    y: int
    width: int
    height: int
    is_active: bool


class MouseButton(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


@dataclass(frozen=True)
class InputEvent:
    """全域監聽事件。kind: key_down / key_up / mouse_move / mouse_down / mouse_up / scroll"""
    kind: str
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

    @abstractmethod
    def key_press(self, key: str, hold_ms: int = 0) -> None: ...

    @abstractmethod
    def key_combo(self, keys: list[str]) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def mouse_move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None: ...

    @abstractmethod
    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None: ...

    @abstractmethod
    def scroll(self, x: int, y: int, dx: int, dy: int) -> None: ...


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


class ScreenCapture(ABC):
    @abstractmethod
    def capture(self, region: Rect) -> Any:
        """擷取螢幕區域（絕對座標），回傳 numpy BGR 影像。M3 實作。"""
        ...


class OcrEngine(ABC):
    @abstractmethod
    def recognize(self, image: Any) -> list[TextBox]:
        """辨識影像中的文字。M3 實作。"""
        ...
```

- [ ] **Step 4: 實作測試替身**

`tests/fakes.py`：

```python
"""core 層測試用的平台假實作。"""
from __future__ import annotations

import re

from keyboard_executor.platforms.base import (
    InputBackend,
    MouseButton,
    WindowInfo,
    WindowManager,
)


class FakeInputBackend(InputBackend):
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        self.calls.append(("key_press", key, hold_ms))

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
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest tests/platforms/test_base.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/base.py tests/fakes.py tests/platforms/test_base.py
git commit -m "feat: 平台抽象介面（五介面契約）與測試替身"
```

---

### Task 4: 按鍵名稱映射（keymap）

**Files:**
- Create: `src/keyboard_executor/platforms/common/keymap.py`
- Test: `tests/platforms/test_keymap.py`

**Interfaces:**
- Consumes: pynput（`Key`, `KeyCode`）
- Produces:
  - `parse_key(name: str) -> Key | KeyCode` — 腳本按鍵名稱 → pynput 按鍵；不認得時 raise `ValueError`
  - `parse_combo(combo: str | list[str]) -> list[Key | KeyCode]` — `"ctrl+shift+s"` 或 `["ctrl","shift","s"]`
  - 支援名稱：修飾鍵 ctrl/control、shift、alt/option、cmd/win/super；enter/return、esc/escape、tab、space、backspace、delete、home、end、pageup、pagedown、up/down/left/right；f1–f20；任何單一字元

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_keymap.py`：

```python
import pytest
from pynput.keyboard import Key, KeyCode

from keyboard_executor.platforms.common.keymap import parse_combo, parse_key


def test_parse_special_keys():
    assert parse_key("ctrl") is Key.ctrl
    assert parse_key("enter") is Key.enter
    assert parse_key("f9") is Key.f9
    assert parse_key("pageup") is Key.page_up


def test_parse_key_aliases():
    assert parse_key("control") is Key.ctrl
    assert parse_key("return") is Key.enter
    assert parse_key("option") is Key.alt
    assert parse_key("win") is Key.cmd


def test_parse_key_is_case_insensitive_and_strips():
    assert parse_key(" F10 ") is Key.f10
    assert parse_key("CTRL") is Key.ctrl


def test_parse_single_char():
    assert parse_key("a") == KeyCode.from_char("a")
    assert parse_key("1") == KeyCode.from_char("1")


def test_parse_unknown_key_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_key("notakey")


def test_parse_combo_from_string():
    assert parse_combo("ctrl+shift+s") == [Key.ctrl, Key.shift, KeyCode.from_char("s")]


def test_parse_combo_from_list():
    assert parse_combo(["cmd", "q"]) == [Key.cmd, KeyCode.from_char("q")]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_keymap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.common.keymap'`

- [ ] **Step 3: 實作 keymap.py**

`src/keyboard_executor/platforms/common/keymap.py`：

```python
"""腳本按鍵名稱（字串）→ pynput 按鍵物件的映射。"""
from __future__ import annotations

from pynput.keyboard import Key, KeyCode

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
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 21)},
}


def parse_key(name: str) -> Key | KeyCode:
    n = name.strip().lower()
    if n in _SPECIAL:
        return _SPECIAL[n]
    if len(n) == 1:
        return KeyCode.from_char(n)
    raise ValueError(f"無法辨識的按鍵名稱: {name!r}")


def parse_combo(combo: str | list[str]) -> list[Key | KeyCode]:
    keys = combo.split("+") if isinstance(combo, str) else combo
    return [parse_key(k) for k in keys]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_keymap.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/common/keymap.py tests/platforms/test_keymap.py
git commit -m "feat: 按鍵名稱映射（腳本字串 → pynput）"
```

---

### Task 5: pynput 輸入模擬（共用實作）

**Files:**
- Create: `src/keyboard_executor/platforms/common/input_pynput.py`
- Test: `tests/platforms/test_input_pynput.py`

**Interfaces:**
- Consumes: `InputBackend`, `MouseButton`（Task 3）、`parse_key`（Task 4）
- Produces:
  - `PynputInputBackend(keyboard=None, mouse=None, sleep=time.sleep)` — 實作 `InputBackend`；controller 與 sleep 可注入。macOS 直接使用；Windows 由 Task 6 繼承擴充

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_input_pynput.py`：

```python
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from keyboard_executor.platforms.base import MouseButton
from keyboard_executor.platforms.common.input_pynput import PynputInputBackend


class SpyKeyboard:
    def __init__(self):
        self.ops = []

    def press(self, key):
        self.ops.append(("press", key))

    def release(self, key):
        self.ops.append(("release", key))

    def type(self, text):
        self.ops.append(("type", text))


class SpyMouse:
    def __init__(self):
        self.ops = []
        self._position = (0, 0)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        self.ops.append(("move", value))

    def click(self, button, count):
        self.ops.append(("click", button, count))

    def press(self, button):
        self.ops.append(("press", button))

    def release(self, button):
        self.ops.append(("release", button))

    def scroll(self, dx, dy):
        self.ops.append(("scroll", dx, dy))


def make_backend():
    kb, mouse, sleeps = SpyKeyboard(), SpyMouse(), []
    backend = PynputInputBackend(keyboard=kb, mouse=mouse, sleep=sleeps.append)
    return backend, kb, mouse, sleeps


def test_key_press_is_press_then_release():
    backend, kb, _, sleeps = make_backend()
    backend.key_press("enter")
    assert kb.ops == [("press", Key.enter), ("release", Key.enter)]
    assert sleeps == []  # hold_ms=0 不需要等待


def test_key_press_with_hold_sleeps_between():
    backend, kb, _, sleeps = make_backend()
    backend.key_press("a", hold_ms=500)
    assert kb.ops == [("press", KeyCode.from_char("a")), ("release", KeyCode.from_char("a"))]
    assert sleeps == [0.5]


def test_key_combo_releases_in_reverse_order():
    backend, kb, _, _ = make_backend()
    backend.key_combo(["ctrl", "shift", "s"])
    s = KeyCode.from_char("s")
    assert kb.ops == [
        ("press", Key.ctrl), ("press", Key.shift), ("press", s),
        ("release", s), ("release", Key.shift), ("release", Key.ctrl),
    ]


def test_type_text_delegates():
    backend, kb, _, _ = make_backend()
    backend.type_text("哈囉 world")
    assert kb.ops == [("type", "哈囉 world")]


def test_mouse_click_moves_then_clicks():
    backend, _, mouse, _ = make_backend()
    backend.mouse_click(100, 200, MouseButton.RIGHT, count=2)
    assert mouse.ops == [("move", (100, 200)), ("click", Button.right, 2)]


def test_mouse_drag_press_move_release():
    backend, _, mouse, _ = make_backend()
    backend.mouse_drag(10, 20, 30, 40)
    assert mouse.ops == [
        ("move", (10, 20)), ("press", Button.left),
        ("move", (30, 40)), ("release", Button.left),
    ]


def test_scroll_moves_then_scrolls():
    backend, _, mouse, _ = make_backend()
    backend.scroll(5, 6, 0, -3)
    assert mouse.ops == [("move", (5, 6)), ("scroll", 0, -3)]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_input_pynput.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.common.input_pynput'`

- [ ] **Step 3: 實作 input_pynput.py**

`src/keyboard_executor/platforms/common/input_pynput.py`：

```python
"""pynput 輸入模擬：macOS（CGEvent）與 Windows（SendInput）共用。"""
from __future__ import annotations

import time

from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

from keyboard_executor.platforms.base import InputBackend, MouseButton
from keyboard_executor.platforms.common.keymap import parse_key

_BUTTON = {
    MouseButton.LEFT: Button.left,
    MouseButton.RIGHT: Button.right,
    MouseButton.MIDDLE: Button.middle,
}

# 滑鼠移動後給前景程式反應時間（秒）；太短會導致部分程式收不到 hover/點擊位置
_SETTLE = 0.05


class PynputInputBackend(InputBackend):
    def __init__(self, keyboard=None, mouse=None, sleep=time.sleep):
        self._kb = keyboard if keyboard is not None else KeyboardController()
        self._mouse = mouse if mouse is not None else MouseController()
        self._sleep = sleep

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        k = parse_key(key)
        self._kb.press(k)
        if hold_ms > 0:
            self._sleep(hold_ms / 1000)
        self._kb.release(k)

    def key_combo(self, keys: list[str]) -> None:
        parsed = [parse_key(k) for k in keys]
        for k in parsed:
            self._kb.press(k)
        for k in reversed(parsed):
            self._kb.release(k)

    def type_text(self, text: str) -> None:
        self._kb.type(text)

    def mouse_move(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        self._mouse.position = (x, y)
        self._sleep(_SETTLE)
        self._mouse.click(_BUTTON[button], count)

    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None:
        b = _BUTTON[button]
        self._mouse.position = (from_x, from_y)
        self._sleep(_SETTLE)
        self._mouse.press(b)
        self._sleep(_SETTLE)
        self._mouse.position = (to_x, to_y)
        self._sleep(_SETTLE)
        self._mouse.release(b)

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._mouse.position = (x, y)
        self._mouse.scroll(dx, dy)
```

注意：測試檢查 `mouse.ops` 時不含 sleep 造成的項目——`_SETTLE` 走注入的 `sleep`，Spy 版本是 `sleeps.append`（list append 只收秒數，不進 `mouse.ops`）。`test_mouse_drag_press_move_release` 的期望序列已對應上面實作的順序。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_input_pynput.py -v`
Expected: 7 passed

- [ ] **Step 5: 全套件回歸**

Run: `pytest -v`
Expected: 全部通過（Task 1–5 累計 26 個測試）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/common/input_pynput.py tests/platforms/test_input_pynput.py
git commit -m "feat: pynput 輸入模擬共用實作"
```

---

### Task 6: pywinctl 視窗控制（共用實作）

**Files:**
- Create: `src/keyboard_executor/platforms/common/window_pywinctl.py`
- Test: `tests/platforms/test_window_pywinctl.py`

**Interfaces:**
- Consumes: `WindowManager`, `WindowInfo`（Task 3）
- Produces:
  - `PywinctlWindowManager(pwc=None, sleep=time.sleep, clock=time.monotonic)` — 實作 `WindowManager`；pywinctl 模組、sleep、clock 可注入

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_window_pywinctl.py`：

```python
from types import SimpleNamespace

from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager


class StubWindow:
    """模擬 pywinctl 視窗物件的最小介面。"""

    def __init__(self, title, app="App", box=(10, 20, 800, 600), active=False, alive=True):
        self.title = title
        self._app = app
        self.box = SimpleNamespace(left=box[0], top=box[1], width=box[2], height=box[3])
        self.isActive = active
        self.isAlive = alive
        self.activate_calls = 0

    def getAppName(self):
        return self._app

    def activate(self):
        self.activate_calls += 1


class StubPwc:
    def __init__(self, windows):
        self._windows = windows

    def getAllWindows(self):
        return list(self._windows)


class FakeClock:
    """sleep 一次就前進一格的假時鐘。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_manager(windows):
    clock = FakeClock()
    manager = PywinctlWindowManager(
        pwc=StubPwc(windows), sleep=clock.sleep, clock=clock.monotonic
    )
    return manager, clock


def test_list_all_converts_to_window_info():
    manager, _ = make_manager([StubWindow("記事本", app="Notepad", box=(1, 2, 300, 400))])
    infos = manager.list_all()
    assert len(infos) == 1
    info = infos[0]
    assert (info.title, info.app_name) == ("記事本", "Notepad")
    assert (info.x, info.y, info.width, info.height) == (1, 2, 300, 400)


def test_find_windows_by_title_regex():
    manager, _ = make_manager([StubWindow("記事本 - 未命名"), StubWindow("瀏覽器")])
    result = manager.find_windows(title_pattern="記事")
    assert [w.title for w in result] == ["記事本 - 未命名"]


def test_find_windows_by_app_name_case_insensitive():
    manager, _ = make_manager([StubWindow("A", app="Notepad"), StubWindow("B", app="Safari")])
    result = manager.find_windows(app_name="notepad")
    assert [w.app_name for w in result] == ["Notepad"]


def test_activate_returns_true_when_window_becomes_active():
    stub = StubWindow("目標")
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]

    # 第一次輪詢後視窗變為 active
    original_sleep = manager._sleep

    def sleep_then_activate(seconds):
        original_sleep(seconds)
        stub.isActive = True

    manager._sleep = sleep_then_activate
    assert manager.activate(info) is True
    assert stub.activate_calls == 1


def test_activate_times_out_and_returns_false():
    stub = StubWindow("目標", active=False)
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info, timeout_ms=200) is False


def test_refresh_returns_updated_geometry():
    stub = StubWindow("目標", box=(0, 0, 100, 100))
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    stub.box = SimpleNamespace(left=50, top=60, width=100, height=100)
    updated = manager.refresh(info)
    assert (updated.x, updated.y) == (50, 60)


def test_refresh_returns_none_when_window_closed():
    stub = StubWindow("目標", alive=False)
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.refresh(info) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_window_pywinctl.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.common.window_pywinctl'`

- [ ] **Step 3: 實作 window_pywinctl.py**

`src/keyboard_executor/platforms/common/window_pywinctl.py`：

```python
"""pywinctl 視窗控制：Windows 與 macOS 共用。"""
from __future__ import annotations

import re
import time

from keyboard_executor.platforms.base import WindowInfo, WindowManager

_POLL_INTERVAL = 0.05  # activate 後輪詢焦點的間隔（秒）


class PywinctlWindowManager(WindowManager):
    def __init__(self, pwc=None, sleep=time.sleep, clock=time.monotonic):
        if pwc is None:
            import pywinctl as pwc
        self._pwc = pwc
        self._sleep = sleep
        self._clock = clock

    def list_all(self) -> list[WindowInfo]:
        return [self._to_info(w) for w in self._pwc.getAllWindows()]

    def find_windows(
        self, title_pattern: str | None = None, app_name: str | None = None
    ) -> list[WindowInfo]:
        result = []
        for info in self.list_all():
            if title_pattern and not re.search(title_pattern, info.title):
                continue
            if app_name and info.app_name.lower() != app_name.lower():
                continue
            result.append(info)
        return result

    def activate(self, window: WindowInfo, timeout_ms: int = 3000) -> bool:
        w = window.handle
        w.activate()
        deadline = self._clock() + timeout_ms / 1000
        while self._clock() < deadline:
            if w.isActive:
                return True
            self._sleep(_POLL_INTERVAL)
        return bool(w.isActive)

    def refresh(self, window: WindowInfo) -> WindowInfo | None:
        w = window.handle
        try:
            if not w.isAlive:
                return None
            return self._to_info(w)
        except Exception:
            # 視窗物件失效（已關閉）時 pywinctl 可能丟平台相依例外
            return None

    def _to_info(self, w) -> WindowInfo:
        try:
            app = w.getAppName()
        except Exception:
            app = ""
        box = w.box
        return WindowInfo(
            handle=w, title=w.title, app_name=app,
            x=box.left, y=box.top, width=box.width, height=box.height,
            is_active=bool(w.isActive),
        )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_window_pywinctl.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/common/window_pywinctl.py tests/platforms/test_window_pywinctl.py
git commit -m "feat: pywinctl 視窗控制共用實作"
```

---

### Task 7: Windows 專屬層（DPI + 遊戲輸入模式）

**Files:**
- Create: `src/keyboard_executor/platforms/win32/dpi.py`
- Create: `src/keyboard_executor/platforms/win32/input.py`
- Test: `tests/platforms/test_win32_input.py`

**Interfaces:**
- Consumes: `PynputInputBackend`（Task 5）、`MouseButton`（Task 3）
- Produces:
  - `ensure_dpi_awareness() -> None` — 宣告 Per-Monitor DPI Aware；僅在 Windows 呼叫
  - `Win32InputBackend(game_input_mode=False, pdi=None, **kwargs)` — 繼承 `PynputInputBackend`；`game_input_mode=True` 時鍵盤與點擊改走 pydirectinput（scan code），`pdi` 可注入假模組供測試

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_win32_input.py`：

```python
from keyboard_executor.platforms.base import MouseButton
from keyboard_executor.platforms.win32.input import Win32InputBackend


class SpyPdi:
    """模擬 pydirectinput 模組的最小介面。"""

    def __init__(self):
        self.ops = []
        self.PAUSE = 0.1

    def keyDown(self, key):
        self.ops.append(("keyDown", key))

    def keyUp(self, key):
        self.ops.append(("keyUp", key))

    def moveTo(self, x, y):
        self.ops.append(("moveTo", x, y))

    def click(self, button):
        self.ops.append(("click", button))


class SpyKeyboard:
    def __init__(self):
        self.ops = []

    def press(self, key):
        self.ops.append(("press", key))

    def release(self, key):
        self.ops.append(("release", key))

    def type(self, text):
        self.ops.append(("type", text))


class SpyMouse:
    def __init__(self):
        self.ops = []
        self._position = (0, 0)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        self.ops.append(("move", value))

    def click(self, button, count):
        self.ops.append(("click", button, count))

    def press(self, button):
        self.ops.append(("press", button))

    def release(self, button):
        self.ops.append(("release", button))

    def scroll(self, dx, dy):
        self.ops.append(("scroll", dx, dy))


def make_game_backend():
    pdi, kb, mouse, sleeps = SpyPdi(), SpyKeyboard(), SpyMouse(), []
    backend = Win32InputBackend(
        game_input_mode=True, pdi=pdi, keyboard=kb, mouse=mouse, sleep=sleeps.append
    )
    return backend, pdi, kb, mouse, sleeps


def test_game_mode_key_press_uses_pydirectinput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.key_press("enter")
    assert pdi.ops == [("keyDown", "enter"), ("keyUp", "enter")]
    assert kb.ops == []  # 不走 pynput


def test_game_mode_key_press_with_hold():
    backend, pdi, _, _, sleeps = make_game_backend()
    backend.key_press("w", hold_ms=1000)
    assert pdi.ops == [("keyDown", "w"), ("keyUp", "w")]
    assert sleeps == [1.0]


def test_game_mode_key_combo_releases_in_reverse():
    backend, pdi, _, _, _ = make_game_backend()
    backend.key_combo(["ctrl", "c"])
    assert pdi.ops == [
        ("keyDown", "ctrl"), ("keyDown", "c"),
        ("keyUp", "c"), ("keyUp", "ctrl"),
    ]


def test_game_mode_click_uses_pydirectinput():
    backend, pdi, _, mouse, _ = make_game_backend()
    backend.mouse_click(100, 200, MouseButton.RIGHT, count=2)
    assert pdi.ops == [("moveTo", 100, 200), ("click", "right"), ("click", "right")]
    assert mouse.ops == []


def test_normal_mode_falls_back_to_pynput():
    kb, mouse = SpyKeyboard(), SpyMouse()
    backend = Win32InputBackend(
        game_input_mode=False, keyboard=kb, mouse=mouse, sleep=lambda s: None
    )
    backend.type_text("hi")
    backend.mouse_click(1, 2)
    assert kb.ops == [("type", "hi")]
    assert ("move", (1, 2)) in mouse.ops
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_win32_input.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.win32.input'`

- [ ] **Step 3: 實作 dpi.py 與 input.py**

`src/keyboard_executor/platforms/win32/dpi.py`：

```python
"""Windows 高 DPI 宣告。不宣告的話，系統縮放 ≠ 100% 時座標會整體偏移。"""
from __future__ import annotations


def ensure_dpi_awareness() -> None:
    import ctypes

    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE（Windows 8.1+）
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass  # 已由外部設定過或極舊版 Windows；寧可繼續也不要在啟動即崩潰
```

`src/keyboard_executor/platforms/win32/input.py`：

```python
"""Windows 輸入實作。game_input_mode=True 時改走 pydirectinput（DirectInput scan code），
供攔截 SendInput 虛擬鍵碼的遊戲使用。不做任何反偵測——遊戲若阻擋輸入則如實失效。"""
from __future__ import annotations

from keyboard_executor.platforms.base import MouseButton
from keyboard_executor.platforms.common.input_pynput import PynputInputBackend


class Win32InputBackend(PynputInputBackend):
    def __init__(self, game_input_mode: bool = False, pdi=None, **kwargs):
        super().__init__(**kwargs)
        self._pdi = None
        if game_input_mode:
            if pdi is None:
                import pydirectinput as pdi
                pdi.PAUSE = 0  # 由我們自己的 delay 動作控制節奏
            self._pdi = pdi

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        if self._pdi is None:
            return super().key_press(key, hold_ms)
        self._pdi.keyDown(key)
        if hold_ms > 0:
            self._sleep(hold_ms / 1000)
        self._pdi.keyUp(key)

    def key_combo(self, keys: list[str]) -> None:
        if self._pdi is None:
            return super().key_combo(keys)
        for k in keys:
            self._pdi.keyDown(k)
        for k in reversed(keys):
            self._pdi.keyUp(k)

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        if self._pdi is None:
            return super().mouse_click(x, y, button, count)
        self._pdi.moveTo(x, y)
        for _ in range(count):
            self._pdi.click(button=str(button))
```

注意：pydirectinput 的按鍵名稱沿用 pyautogui 慣例（`"ctrl"`、`"enter"`、`"f9"`、單一字元），與本專案腳本按鍵名稱大致相同，因此直接傳字串、不經過 keymap。不相容的名稱（如 `"option"`、`"win"`）屬 macOS/通用別名，游戲模式僅在 Windows 使用，遇到不認得的名稱 pydirectinput 會拋錯，如實回報即可。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_win32_input.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/win32/ tests/platforms/test_win32_input.py
git commit -m "feat: Windows 專屬層（DPI 宣告 + pydirectinput 遊戲輸入模式）"
```

---

### Task 8: macOS 專屬層（權限檢查）

**Files:**
- Create: `src/keyboard_executor/platforms/darwin/permissions.py`
- Test: `tests/platforms/test_darwin_permissions.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `check_accessibility(_ax_is_trusted=None) -> bool` — 是否已授予「輔助使用」權限（模擬輸入的前提）；檢查函式可注入供測試
  - `ACCESSIBILITY_GUIDE: str` — 引導使用者開啟權限的說明文字（M4 GUI 與 demo 共用）

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_darwin_permissions.py`：

```python
from keyboard_executor.platforms.darwin.permissions import (
    ACCESSIBILITY_GUIDE,
    check_accessibility,
)


def test_check_accessibility_true_when_trusted():
    assert check_accessibility(_ax_is_trusted=lambda: 1) is True


def test_check_accessibility_false_when_not_trusted():
    assert check_accessibility(_ax_is_trusted=lambda: 0) is False


def test_guide_mentions_system_settings():
    assert "輔助使用" in ACCESSIBILITY_GUIDE
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_darwin_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.darwin.permissions'`

- [ ] **Step 3: 實作 permissions.py**

`src/keyboard_executor/platforms/darwin/permissions.py`：

```python
"""macOS 權限檢查。模擬輸入需要「輔助使用」；M2 錄製另需「輸入監控」；M3 截圖另需「螢幕錄製」。"""
from __future__ import annotations

ACCESSIBILITY_GUIDE = (
    "尚未授予「輔助使用」權限，無法模擬鍵盤滑鼠。\n"
    "請開啟：系統設定 → 隱私權與安全性 → 輔助使用，"
    "將執行本程式的終端機（或打包後的 App）加入並勾選，然後重新啟動程式。"
)


def check_accessibility(_ax_is_trusted=None) -> bool:
    if _ax_is_trusted is None:
        from ApplicationServices import AXIsProcessTrusted as _ax_is_trusted
    return bool(_ax_is_trusted())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_darwin_permissions.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/darwin/permissions.py tests/platforms/test_darwin_permissions.py
git commit -m "feat: macOS 輔助使用權限檢查"
```

---

### Task 9: 平台工廠

**Files:**
- Create: `src/keyboard_executor/platforms/factory.py`
- Test: `tests/platforms/test_factory.py`

**Interfaces:**
- Consumes: Task 5–8 的所有實作
- Produces:
  - `Platform(input_backend: InputBackend, window_manager: WindowManager)`（frozen dataclass）
  - `get_platform(game_input_mode: bool = False, _sys_platform: str | None = None) -> Platform` — 依 `sys.platform` 分派；不支援的平台 raise `RuntimeError`。`_sys_platform` 僅供測試覆寫

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_factory.py`：

```python
import sys

import pytest

from keyboard_executor.platforms.factory import Platform, get_platform


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/platforms/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.factory'`

- [ ] **Step 3: 實作 factory.py**

`src/keyboard_executor/platforms/factory.py`：

```python
"""平台工廠：整個程式唯一依 sys.platform 分派的進入點。"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from keyboard_executor.platforms.base import InputBackend, WindowManager


@dataclass(frozen=True)
class Platform:
    input_backend: InputBackend
    window_manager: WindowManager


def get_platform(game_input_mode: bool = False, _sys_platform: str | None = None) -> Platform:
    plat = _sys_platform if _sys_platform is not None else sys.platform
    if plat == "win32":
        from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager
        from keyboard_executor.platforms.win32.dpi import ensure_dpi_awareness
        from keyboard_executor.platforms.win32.input import Win32InputBackend

        ensure_dpi_awareness()
        return Platform(
            input_backend=Win32InputBackend(game_input_mode=game_input_mode),
            window_manager=PywinctlWindowManager(),
        )
    if plat == "darwin":
        from keyboard_executor.platforms.common.input_pynput import PynputInputBackend
        from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager

        return Platform(
            input_backend=PynputInputBackend(),
            window_manager=PywinctlWindowManager(),
        )
    raise RuntimeError(f"不支援的平台: {plat}")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/platforms/test_factory.py -v`
Expected: macOS 上 2 passed, 1 skipped（Windows 上則相反）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/factory.py tests/platforms/test_factory.py
git commit -m "feat: 平台工廠（sys.platform 分派）"
```

---

### Task 10: M1 驗收 demo

**Files:**
- Create: `src/keyboard_executor/demo.py`
- Test: `tests/test_demo.py`

**Interfaces:**
- Consumes: `get_platform`（Task 9）、`Point`/`to_absolute`（Task 2）、`check_accessibility`/`ACCESSIBILITY_GUIDE`（Task 8）
- Produces:
  - `build_parser() -> argparse.ArgumentParser`
  - `main(argv: list[str] | None = None) -> int` — 0 成功、1 失敗
  - CLI：`python -m keyboard_executor.demo --title <regex> [--game-input]`

- [ ] **Step 1: 寫失敗測試**

`tests/test_demo.py`：

```python
import pytest

from keyboard_executor.demo import build_parser


def test_parser_requires_title():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_parses_title_and_game_input():
    args = build_parser().parse_args(["--title", "記事本.*", "--game-input"])
    assert args.title == "記事本.*"
    assert args.game_input is True


def test_game_input_defaults_false():
    args = build_parser().parse_args(["--title", "x"])
    assert args.game_input is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_demo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.demo'`

- [ ] **Step 3: 實作 demo.py**

`src/keyboard_executor/demo.py`：

```python
"""M1 驗收 demo：把目標視窗切到前景，執行一段寫死的動作序列。

macOS：開啟「文字編輯」並新增文件後執行
    python -m keyboard_executor.demo --title "未命名|Untitled"
Windows：開啟「記事本」後執行
    python -m keyboard_executor.demo --title "記事本|Notepad"
"""
from __future__ import annotations

import argparse
import sys
import time

from keyboard_executor.core.geometry import Point, to_absolute
from keyboard_executor.platforms.factory import get_platform


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M1 demo：對指定視窗執行寫死的動作序列")
    parser.add_argument("--title", required=True, help="目標視窗標題（regex）")
    parser.add_argument(
        "--game-input", action="store_true",
        help="Windows 遊戲輸入模式（pydirectinput scan code）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if sys.platform == "darwin":
        from keyboard_executor.platforms.darwin.permissions import (
            ACCESSIBILITY_GUIDE,
            check_accessibility,
        )

        if not check_accessibility():
            print(ACCESSIBILITY_GUIDE, file=sys.stderr)
            return 1

    platform = get_platform(game_input_mode=args.game_input)

    windows = platform.window_manager.find_windows(title_pattern=args.title)
    if not windows:
        print(f"找不到符合 {args.title!r} 的視窗", file=sys.stderr)
        return 1
    win = windows[0]
    print(f"目標視窗：{win.title}（{win.app_name}）@ ({win.x}, {win.y}) {win.width}x{win.height}")

    if not platform.window_manager.activate(win):
        print("無法將視窗切到前景", file=sys.stderr)
        return 1
    time.sleep(0.3)  # 前景切換後留給系統穩定的時間

    origin = Point(win.x, win.y)
    center = to_absolute(origin, Point(win.width // 2, win.height // 2))
    backend = platform.input_backend
    backend.mouse_click(center.x, center.y)
    backend.type_text("hello from keyboard-executor")
    backend.key_press("enter")
    backend.type_text("M1 acceptance ok")
    print("動作序列執行完畢")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_demo.py -v`
Expected: 3 passed

- [ ] **Step 5: 全套件回歸**

Run: `pytest -v`
Expected: 全部通過（macOS 上 46 passed, 1 skipped；Windows 上 46 passed, 1 skipped）

- [ ] **Step 6: macOS 手動 smoke 測試（M1 驗收）**

1. 開啟「文字編輯」（TextEdit）→ 新增文件
2. 回到終端機執行：

```bash
python -m keyboard_executor.demo --title "未命名|Untitled"
```

3. 首次執行若印出輔助使用權限引導 → 依指示到「系統設定 → 隱私權與安全性 → 輔助使用」勾選終端機，重跑
4. Expected：TextEdit 跳到前景，游標點在文件中央，輸入兩行文字：
   ```
   hello from keyboard-executor
   M1 acceptance ok
   ```
5. 程式輸出 `動作序列執行完畢`，exit code 0

- [ ] **Step 7: Windows 手動 smoke 測試（有 Windows 機器時執行；沒有則記入 backlog，M5 前必須補驗）**

1. `pip install -e ".[dev]"` 後開啟記事本
2. 執行：

```powershell
python -m keyboard_executor.demo --title "記事本|Notepad"
```

3. Expected：記事本跳到前景並輸入同樣兩行文字
4. 額外驗證高 DPI：在縮放 125%/150% 的螢幕上執行，游標仍應點在視窗中央（驗證 `ensure_dpi_awareness` 生效）

- [ ] **Step 8: Commit**

```bash
git add src/keyboard_executor/demo.py tests/test_demo.py
git commit -m "feat: M1 驗收 demo（前景切換 + 寫死動作序列）"
```

---

## 完成定義（M1 驗收標準，對應 spec §13）

- [ ] `pytest -v` 全數通過
- [ ] macOS smoke 測試通過（Task 10 Step 6）
- [ ] Windows smoke 測試通過或已記入 backlog（Task 10 Step 7）
- [ ] 座標換算、按鍵映射、視窗尋找/啟用、遊戲模式分派皆有單元測試覆蓋

## 後續計畫（不在本計畫範圍）

- M2：錄製引擎 + JSON 腳本格式 + 回放引擎 → `docs/superpowers/plans/`（M1 完成後撰寫）
- M3：截圖 + OCR + 模板比對 + 規則引擎
- M4：GUI（PySide6）
- M5：打包與發布
