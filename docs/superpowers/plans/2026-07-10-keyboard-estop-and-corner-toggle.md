# 遊戲可用按鍵緊急停止 + 滑鼠角落開關 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 GetAsyncKeyState 背景輪詢的按鍵緊急停止（遊戲擋掉 hook/RegisterHotKey 時的後盾），並讓滑鼠左上角 failsafe 可由設定關閉（修好游標被甩到 (0,0) 誤停腳本）。

**Architecture:** 新輪詢器 `AsyncKeyStopPoller` 在背景執行緒讀實體按鍵狀態、上升緣經 Qt Signal 跨執行緒排到 GUI 執行緒停止；角落 failsafe 以 `SessionGuard.corner_failsafe` 旗標閘門，沿用 `stop_key` 既有的 Settings→控制器→guard 流路。三機制（RegisterHotKey／輪詢／滑鼠角落）併存互為後盾。

**Tech Stack:** Python 3.13 / PySide6 / ctypes（Windows GetAsyncKeyState）/ pytest。

## Global Constraints

- 新輪詢器僅 Windows 使用（ctypes）；非 win32／離屏環境不啟動，僅記錄。
- `corner_failsafe` 缺鍵預設 `True`（向後相容舊設定檔）；關閉時滑鼠左上角完全不觸發停止。
- 上升緣觸發（未按→按下）避免按著不放重複觸發；輪詢間隔固定 `0.03` 秒。
- **執行緒安全**：輪詢器 `on_trigger` 由背景執行緒呼叫，必須經 `MainWindow.emergency_stop_requested`（Qt Signal）排到 GUI 執行緒，不可從輪詢執行緒直接動 Qt widget。
- 三機制併存；任一先偵測到即停。vk 解析沿用 `global_hotkey.vk_for_key`（勿重複實作）。
- 定位為安全性「停止」機制，非反作弊繞過。面向使用者訊息維持繁中。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH，Qt 需 offscreen）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/app/key_stop_poller.py` | GetAsyncKeyState 背景輪詢按鍵停止 | Create |
| `src/keyboard_executor/core/guard.py` | `SessionGuard` 角落判定加 `corner_failsafe` 閘門 | Modify |
| `src/keyboard_executor/app/settings.py` | `Settings` 加 `corner_failsafe` 欄位＋驗證 | Modify |
| `src/keyboard_executor/app/run_controller.py` | `corner_failsafe` 傳抵 guard | Modify |
| `src/keyboard_executor/app/watch_controller.py` | `corner_failsafe` 傳抵 guard | Modify |
| `src/keyboard_executor/app/settings_page.py` | 角落 failsafe 勾選框 | Modify |
| `src/keyboard_executor/app/main_window.py` | 輪詢器 wiring（Signal/setup/reregister/close）＋傳 corner_failsafe | Modify |
| 對應 `tests/…` | 各層測試 | Create/Modify |

**cli 不需改**：`cli._start_play_guard`/`_start_watch_guard` 建 `SessionGuard` 未帶 `corner_failsafe`，沿用預設 `True`（角落照舊有效）。

執行順序 **Task 1→7**：Task 4 依賴 Task 2（guard 的 `corner_failsafe` 參數）；Task 5 依賴 Task 3（Settings 欄位）；Task 6 依賴 Task 1（輪詢器）、Task 3（欄位）、Task 4（控制器參數）。

---

### Task 1: `AsyncKeyStopPoller`（GetAsyncKeyState 背景輪詢）

**Files:**
- Create: `src/keyboard_executor/app/key_stop_poller.py`
- Test: `tests/app/test_key_stop_poller.py`

**Interfaces:**
- Consumes: `keyboard_executor.app.global_hotkey.vk_for_key`。
- Produces: `AsyncKeyStopPoller(on_trigger, *, key_down_fn=None, sleep=None, poll_interval=0.03)`；`.start(key_name) -> bool`（解析不到鍵回 False 且不起執行緒）；`.stop()`。上升緣時呼叫 `on_trigger`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/app/test_key_stop_poller.py`：
```python
from keyboard_executor.app.key_stop_poller import AsyncKeyStopPoller


def test_start_returns_false_for_unknown_key():
    p = AsyncKeyStopPoller(lambda: None, key_down_fn=lambda vk: False,
                           sleep=lambda s: None)
    assert p.start("這不是鍵名") is False
    assert p._thread is None


def test_fires_once_per_rising_edge_not_while_held():
    triggers = []
    states = iter([False, False, True, True, False, True])  # 上升緣在 index 2、5
    poller = None
    n = {"i": 0}

    def key_down_fn(vk):
        return next(states)

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 6:
            poller.stop()

    poller = AsyncKeyStopPoller(lambda: triggers.append(1),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    assert poller.start("f10") is True
    poller._thread.join(timeout=2)
    assert len(triggers) == 2      # 兩次上升緣各一次；按著不放不重複


def test_no_fire_when_key_never_down():
    triggers = []
    poller = None
    n = {"i": 0}

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 3:
            poller.stop()

    poller = AsyncKeyStopPoller(lambda: triggers.append(1),
                               key_down_fn=lambda vk: False, sleep=fake_sleep)
    poller.start("f10")
    poller._thread.join(timeout=2)
    assert triggers == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_key_stop_poller.py -v`
Expected: FAIL（`ModuleNotFoundError: keyboard_executor.app.key_stop_poller`）

- [ ] **Step 3: 最小實作**

Create `src/keyboard_executor/app/key_stop_poller.py`：
```python
"""Windows 系統級按鍵緊急停止：背景輪詢 GetAsyncKeyState 讀實體按鍵狀態。

遊戲（含反作弊）常擋掉低階鍵盤 hook（pynput）與 RegisterHotKey 的訊息投遞；
GetAsyncKeyState 讀的是 OS 的 async 按鍵狀態表，不經訊息佇列/使用者態 hook/焦點，
常在那些機制都失效時仍讀得到。偵測停止鍵「未按→按下」上升緣即呼叫 on_trigger。
若遊戲在核心層過濾鍵盤則此法亦無效（接受）。僅 Windows 使用。
"""
from __future__ import annotations

import logging
import threading
import time

from keyboard_executor.app.global_hotkey import vk_for_key

logger = logging.getLogger(__name__)


def _win_key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class AsyncKeyStopPoller:
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None,
                 poll_interval: float = 0.03):
        self._on_trigger = on_trigger
        self._key_down_fn = key_down_fn or _win_key_down
        self._sleep = sleep or time.sleep
        self._poll_interval = poll_interval
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, key_name: str) -> bool:
        vk = vk_for_key(key_name)
        if vk is None:
            return False
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, args=(vk,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_flag.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
            self._thread = None

    def _run(self, vk: int) -> None:
        prev = False
        while not self._stop_flag.is_set():
            try:
                down = bool(self._key_down_fn(vk))
            except Exception:
                logger.warning("按鍵緊急停止輪詢讀取失敗", exc_info=True)
                down = False
            if down and not prev:
                try:
                    self._on_trigger()
                except Exception:
                    logger.exception("按鍵緊急停止觸發處理失敗")
            prev = down
            self._sleep(self._poll_interval)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_key_stop_poller.py -v`
Expected: PASS（3 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/key_stop_poller.py tests/app/test_key_stop_poller.py
git commit -m "feat(estop): GetAsyncKeyState 背景輪詢按鍵緊急停止（上升緣觸發）"
```

---

### Task 2: `SessionGuard` 角落 failsafe 開關

**Files:**
- Modify: `src/keyboard_executor/core/guard.py`（`__init__` 加參數、`handle` 的 MOUSE_MOVE 分支加閘門）
- Test: `tests/core/test_guard.py`

**Interfaces:**
- Produces: `SessionGuard(hook, stop_event, ..., corner_failsafe: bool = True)`；`corner_failsafe=False` 時滑鼠左上角不再 set stop_event。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_guard.py` 末端新增（沿用檔內既有 helper `make_guard(**kwargs)` 與 `mouse_move(x, y)`；`make_guard` 回 `(guard, hook, stop)`，事件經 `hook.push(...)` 進 guard）：
```python
def test_corner_failsafe_off_ignores_corner_move():
    _, hook, stop = make_guard(corner_failsafe=False)
    hook.push(mouse_move(0, 0))
    assert not stop.is_set()          # 關閉時角落不觸發
```
（角落「預設開仍觸發」已由既有 `test_corner_move_triggers_failsafe` 涵蓋，不重複。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_guard.py -k "corner_failsafe" -v`
Expected: FAIL（`SessionGuard` 無 `corner_failsafe` 參數 → `TypeError`）

- [ ] **Step 3: 最小實作**

`guard.py` 的 `SessionGuard.__init__` 參數列末端加 `corner_failsafe: bool = True`，並存 `self._corner_failsafe = corner_failsafe`。把 `handle` 的 MOUSE_MOVE 分支改為：
```python
        elif event.kind is EventKind.MOUSE_MOVE:
            if (self._corner_failsafe
                    and event.x is not None and event.y is not None
                    and 0 <= event.x <= self._corner_size
                    and 0 <= event.y <= self._corner_size):
                if not self._stop_event.is_set():
                    logger.info("偵測到緊急停止：滑鼠甩到螢幕左上角 → 中止")
                self._stop_event.set()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_guard.py -v`
Expected: PASS（新增 1 項與既有全數；既有角落測試 `corner_failsafe` 預設 True 不受影響）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/guard.py tests/core/test_guard.py
git commit -m "feat(guard): 滑鼠左上角 failsafe 可由 corner_failsafe 關閉"
```

---

### Task 3: `Settings` 加 `corner_failsafe` 欄位

**Files:**
- Modify: `src/keyboard_executor/app/settings.py`（`Settings` dataclass、`validate_settings`）
- Test: `tests/app/test_settings.py`（若不存在則沿用既有設定測試檔；用 `find tests -name "*settings*"` 確認路徑）

**Interfaces:**
- Produces: `Settings.corner_failsafe: bool = True`；`validate_settings` 對非布林拒絕；`SettingsStore` round-trip 保留。

- [ ] **Step 1: 寫失敗測試**

在設定測試檔末端新增（`Settings`/`validate_settings`/`SettingsStore`/`ScriptValidationError` 依既有 import）：
```python
def test_corner_failsafe_defaults_true():
    from keyboard_executor.app.settings import Settings
    assert Settings().corner_failsafe is True


def test_corner_failsafe_round_trips(tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    store = SettingsStore(tmp_path)
    store.save(Settings(corner_failsafe=False))
    assert store.load().corner_failsafe is False


def test_corner_failsafe_rejects_non_bool():
    import pytest
    from keyboard_executor.app.settings import Settings, validate_settings
    from keyboard_executor.core.models import ScriptValidationError
    with pytest.raises(ScriptValidationError):
        validate_settings(Settings(corner_failsafe="yes"))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings.py -k "corner_failsafe" -v`
Expected: FAIL（`Settings` 無 `corner_failsafe`）

- [ ] **Step 3: 最小實作**

`settings.py` 的 `Settings` dataclass 末端加欄位：
```python
    discord_webhook_url: str = ""
    corner_failsafe: bool = True
```
`validate_settings` 在回傳前加型別檢查（放在 webhook 檢查之後）：
```python
    if not isinstance(settings.corner_failsafe, bool):
        raise ScriptValidationError(
            f"設定 corner_failsafe 必須是布林值: {settings.corner_failsafe!r}")
```
（`SettingsStore.load` 以 `Settings(**data)` 建構——舊設定檔缺此鍵時用 dataclass 預設 `True`；`save` 以 `asdict` 輸出，自動含此鍵。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings.py -v`
Expected: PASS（新增 3 項與既有全數；若有既有測試斷言 `asdict(Settings())` 的完整 dict，更新為含 `corner_failsafe`）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings.py tests/app/test_settings.py
git commit -m "feat(settings): 加 corner_failsafe 欄位（預設 True，向後相容）"
```

---

### Task 4: 控制器把 `corner_failsafe` 傳抵 guard

**Files:**
- Modify: `src/keyboard_executor/app/run_controller.py`（`__init__`、`apply_settings`、`_start_guard`）
- Modify: `src/keyboard_executor/app/watch_controller.py`（`__init__`、`apply_settings`、`_start_guard`）
- Test: `tests/app/test_run_controller.py`、`tests/app/test_watch_controller.py`（用 `find tests -name "*run_controller*" -o -name "*watch_controller*"` 確認路徑）

**Interfaces:**
- Consumes: `SessionGuard(..., corner_failsafe=...)`（Task 2）。
- Produces: `RunController(..., corner_failsafe: bool = True)`、`WatchController(..., corner_failsafe: bool = True)`；兩者 `apply_settings(..., corner_failsafe=...)`；`_start_guard` 以 `corner_failsafe=self._corner_failsafe` 建 guard。

- [ ] **Step 1: 寫失敗測試**

在對應測試檔各新增（沿用既有注入 `guard_factory` 的模式；下例為 run_controller，watch_controller 比照）：
```python
def test_run_controller_passes_corner_failsafe_to_guard(tmp_path):
    captured = {}

    class FakeGuard:
        def __init__(self, hook, stop_event, *, stop_key="f10", corner_failsafe=True):
            captured["corner_failsafe"] = corner_failsafe
        def start(self): pass
        def stop(self): pass

    from keyboard_executor.app.run_controller import RunController
    ctrl = RunController(_stub_storage(), lambda n: None,
                         guard_factory=FakeGuard, hook_factory=lambda: object(),
                         corner_failsafe=False)
    ctrl._start_guard(__import__("threading").Event())
    assert captured["corner_failsafe"] is False
```
（`_stub_storage()` 用檔內既有 stub；若無，傳一個有 `load` 的簡單物件即可——`_start_guard` 不觸及 storage。watch_controller 版本用 `WatchController(rule_storage, script_storage, templates, guard_factory=FakeGuard, hook_factory=lambda: object(), corner_failsafe=False)` 後呼叫 `ctrl._start_guard(Event())`。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_run_controller.py tests/app/test_watch_controller.py -k "corner_failsafe" -v`
Expected: FAIL（控制器 `__init__` 無 `corner_failsafe`；`_start_guard` 未傳）

- [ ] **Step 3: 最小實作**

`run_controller.py`：
- `__init__` 參數末端加 `corner_failsafe: bool = True`，存 `self._corner_failsafe = corner_failsafe`。
- `apply_settings` 簽名改為 `def apply_settings(self, *, stop_key, get_platform, corner_failsafe=True):` 並 `self._corner_failsafe = corner_failsafe`。
- `_start_guard` 的 `self._guard_factory(...)` 呼叫加 `corner_failsafe=self._corner_failsafe`：
  ```python
          guard = self._guard_factory(self._hook_factory(), stop_event,
                                      stop_key=self._stop_key,
                                      corner_failsafe=self._corner_failsafe)
  ```

`watch_controller.py`：同樣三處（`__init__` 加參數＋存欄位、`apply_settings` 加 `corner_failsafe` 參數＋存、`_start_guard` 的 guard 建構加 `corner_failsafe=self._corner_failsafe`）。

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_run_controller.py tests/app/test_watch_controller.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/run_controller.py src/keyboard_executor/app/watch_controller.py tests/app/test_run_controller.py tests/app/test_watch_controller.py
git commit -m "feat(controllers): corner_failsafe 由設定傳抵 SessionGuard"
```

---

### Task 5: 設定頁角落 failsafe 勾選框

**Files:**
- Modify: `src/keyboard_executor/app/settings_page.py`（加 `QCheckBox`、`_on_save` 帶入）
- Test: `tests/app/test_settings_page_widget.py`（既有 SettingsPage 測試檔）

**Interfaces:**
- Consumes: `Settings.corner_failsafe`（Task 3）。
- Produces: `SettingsPage.corner_failsafe_check`（`QCheckBox`）；存檔時把勾選狀態寫入 `Settings.corner_failsafe`。

- [ ] **Step 1: 寫失敗測試**

在 settings_page 測試檔末端新增（沿用既有建構 `SettingsPage(SettingsStore(tmp_path))` 與存檔點擊模式）：
```python
def test_corner_failsafe_checkbox_saves(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={})
    page.corner_failsafe_check.setChecked(False)
    page.save_button.click()
    assert store.load().corner_failsafe is False


def test_corner_failsafe_checkbox_reflects_loaded(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    store.save(Settings(corner_failsafe=False))
    page = SettingsPage(store, permission_checks={})
    assert page.corner_failsafe_check.isChecked() is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -k "corner_failsafe" -v`
Expected: FAIL（`SettingsPage` 無 `corner_failsafe_check`）

- [ ] **Step 3: 最小實作**

`settings_page.py`：
- 檔頭 import 加 `QCheckBox`（`from PySide6.QtWidgets import (... QCheckBox ...)`）。
- 在 `level_combo` 那一列之後（`layout.addRow("日誌等級", self.level_combo)` 下方）加：
  ```python
          self.corner_failsafe_check = QCheckBox("滑鼠左上角緊急停止（游標甩到左上角即停）")
          self.corner_failsafe_check.setChecked(settings.corner_failsafe)
          layout.addRow("", self.corner_failsafe_check)
  ```
- `_on_save` 的 `Settings(...)` 建構加一個引數：
  ```python
              discord_webhook_url=self.discord_edit.text().strip(),
              corner_failsafe=self.corner_failsafe_check.isChecked())
  ```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings_page.py tests/app/test_settings_page_widget.py
git commit -m "feat(settings-page): 加「滑鼠左上角緊急停止」勾選框"
```

---

### Task 6: main_window 接線（輪詢器 + Signal + 傳 corner_failsafe）

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`
- Test: `tests/app/test_main_window.py`

**Interfaces:**
- Consumes: `AsyncKeyStopPoller`（Task 1）、`Settings.corner_failsafe`（Task 3）、控制器 `corner_failsafe` 參數與 `apply_settings`（Task 4）。
- Produces: `MainWindow.emergency_stop_requested`（`Signal`）→ `_on_emergency_hotkey`；`self._key_poller` 生命週期與熱鍵一致。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_main_window.py` 末端新增（沿用檔內 `FakeRunController`、`FakeWatchController`）：
```python
def test_emergency_signal_stops_both_controllers(qapp, tmp_path):
    run = FakeRunController()
    watch = FakeWatchController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=run, watch_controller=watch)
    window.emergency_stop_requested.emit()      # 同執行緒 → 同步呼叫 _on_emergency_hotkey
    assert run.stopped == 1 and watch.stopped == 1
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -k "emergency_signal" -v`
Expected: FAIL（`MainWindow` 無 `emergency_stop_requested`）

- [ ] **Step 3: 最小實作**

`main_window.py`：

3a. 檔頭 import 加 `Signal`：
```python
from PySide6.QtCore import Qt, Signal
```

3b. `class MainWindow(QMainWindow):` 內、`__init__` 之前加類別屬性：
```python
class MainWindow(QMainWindow):
    emergency_stop_requested = Signal()   # 背景輪詢器跨執行緒請求緊急停止（排到 GUI 執行緒）
```

3c. `__init__` 建立控制器時把 `corner_failsafe` 帶入（`RunController(...)` 加 `corner_failsafe=self._settings.corner_failsafe`；`WatchController(...)` 同樣加一行 `corner_failsafe=self._settings.corner_failsafe`）。

3d. `__init__` 內 `self._global_hotkey = None` 之後加 `self._key_poller = None`；在 `self._setup_global_hotkey()`（既有呼叫）之前 connect signal：
```python
        self.emergency_stop_requested.connect(self._on_emergency_hotkey)
        self._setup_global_hotkey()
        self._setup_key_poller()
```

3e. 新增 `_setup_key_poller`（緊接 `_setup_global_hotkey` 之後）：
```python
    def _setup_key_poller(self) -> None:
        """Windows：背景輪詢 GetAsyncKeyState 讀實體按鍵狀態，作為 RegisterHotKey
        與滑鼠角落之外的第三道緊急停止（遊戲擋掉前兩者時的後盾）。上升緣經
        emergency_stop_requested 排到 GUI 執行緒處理。"""
        if sys.platform != "win32":
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None or app.platformName() == "offscreen":
                return
            from keyboard_executor.app.key_stop_poller import AsyncKeyStopPoller
            poller = AsyncKeyStopPoller(self.emergency_stop_requested.emit)
            if poller.start(self._settings.stop_key):
                self._key_poller = poller
                logger.info("按鍵緊急停止輪詢已啟用：%s", self._settings.stop_key.upper())
        except Exception:
            logger.warning("按鍵緊急停止輪詢無法啟用", exc_info=True)
```

3f. `_reregister_hotkey(stop_key)` 末端加重啟輪詢器：
```python
        if self._key_poller is not None:
            self._key_poller.stop()
            self._key_poller.start(stop_key)
```

3g. `_apply_settings` 呼叫控制器 `apply_settings` 處加 `corner_failsafe=new.corner_failsafe`（兩個控制器都加）。

3h. `closeEvent` 的 `if self._global_hotkey is not None:` 區塊後加：
```python
        if self._key_poller is not None:
            self._key_poller.stop()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -v`
Expected: PASS（新增 1 項與既有全數；offscreen 下 `_setup_key_poller`／`_setup_global_hotkey` 皆提早返回，不起執行緒）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/main_window.py tests/app/test_main_window.py
git commit -m "feat(estop): main_window 接上按鍵輪詢緊急停止與 corner_failsafe 設定"
```

---

### Task 7: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 658 + 新增約 13 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~6); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後連同先前累積的改動一起重打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序，避免 cv2.pyd 鎖檔）。實機驗收：
1. 執行一個腳本（遊戲在前景），確認腳本**不再因焦點切換而誤停**（可先在設定關掉「滑鼠左上角緊急停止」）。
2. 在遊戲中按下停止鍵，確認**新的按鍵輪詢**能停下（log 應出現「按鍵緊急停止輪詢已啟用」；若遊戲核心層過濾鍵盤則仍可能無效，改用視窗化模式驗證）。
此步驟在計畫外，由使用者驅動。
