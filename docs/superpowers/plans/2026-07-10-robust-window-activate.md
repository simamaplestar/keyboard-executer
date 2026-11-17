# 強化目標視窗前景切換 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓腳本開始時把目標視窗帶到前景更可靠——最小化先還原、timeout 內重試 `w.activate()`、Windows 前景鎖擋住時用 AttachThreadInput 強制前景。

**Architecture:** `force_foreground(hwnd)`（新 win32 模組，注入 win32 API 供測試）當作注入 seam 傳進 `PywinctlWindowManager`；`activate` 改為「還原最小化 → 迴圈（檢查 isActive→重試 activate→grace 後呼叫 force_foreground）」。工廠在 win32 分支接上真實實作。跨平台安全（非 win32 不帶 seam）。

**Tech Stack:** Python 3.13 / pywinctl / ctypes（Windows user32/kernel32）/ pytest。

## Global Constraints

- `activate` 簽名不變：`activate(window, timeout_ms=3000) -> bool`；切不到仍回 `False`（Player 照舊中止顯示「無法將視窗切到前景」）。
- 所有前景操作 best-effort：`restore`/`activate`/`force_foreground` 任一拋例外都吞掉，不使 `activate` 崩潰。
- `force_foreground` 為注入 seam；win32 預設真實 ctypes 實作，其他平台為 `None`（不呼叫）。
- 檢查順序：迴圈內**先檢查 `isActive` 再重試 `activate`**（保持既有 `activate` 測試不變）。grace 常數 `_FORCE_GRACE = 0.3` 秒、輪詢 `_POLL_INTERVAL = 0.05` 秒。
- 把視窗叫到前景是通用視窗管理，**非**反作弊/反偵測/背景送輸入。面向使用者訊息維持繁中。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH，Qt 需 offscreen）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/platforms/win32/foreground.py` | AttachThreadInput 強制前景（注入 win32 API 供測） | Create |
| `src/keyboard_executor/platforms/common/window_pywinctl.py` | `activate` 加還原/重試/force seam | Modify |
| `src/keyboard_executor/platforms/factory.py` | win32 分支把 force_foreground 傳入 manager | Modify |
| 對應 `tests/…` | 各層測試 | Create/Modify |

執行順序 **Task 1→4**：Task 2 消費 Task 1 的 `force_foreground`（但以注入 seam 解耦，測試各自獨立）；Task 3 把兩者接上工廠。

---

### Task 1: `win32/foreground.py` — AttachThreadInput 強制前景

**Files:**
- Create: `src/keyboard_executor/platforms/win32/foreground.py`
- Test: `tests/platforms/test_win32_foreground.py`

**Interfaces:**
- Produces: `force_foreground(hwnd: int, *, user32=None, kernel32=None) -> bool`。注入 `user32`/`kernel32` 供測試；預設用 `ctypes.windll`。任何錯誤回 `False`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/platforms/test_win32_foreground.py`（注入 fake win32 API，不觸真實 ctypes，故任何平台都能跑）：
```python
from keyboard_executor.platforms.win32.foreground import force_foreground


class FakeU32:
    def __init__(self, hwnd, activate_ok=True):
        self._hwnd = hwnd
        self._activate_ok = activate_ok
        self.fg = 999                     # 一開始前景不是目標
        self.calls = []
        self.attached = []

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("ShowWindow", hwnd, cmd))

    def GetForegroundWindow(self):
        return self.fg

    def GetWindowThreadProcessId(self, hwnd, _pid):
        return 100 if hwnd == self._hwnd else 200   # 目標 thread=100、前景 thread=200

    def AttachThreadInput(self, cur, tid, attach):
        self.calls.append(("Attach", cur, tid, attach))
        if attach:
            self.attached.append(tid)
        return 1

    def BringWindowToTop(self, hwnd):
        self.calls.append(("BringWindowToTop", hwnd))

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        if self._activate_ok:
            self.fg = hwnd                # 切成功


class FakeK32:
    def GetCurrentThreadId(self):
        return 1


def test_force_foreground_attaches_sets_and_detaches():
    u = FakeU32(hwnd=42)
    assert force_foreground(42, user32=u, kernel32=FakeK32()) is True
    assert ("SetForegroundWindow", 42) in u.calls
    assert 200 in u.attached and 100 in u.attached      # 前景 thread 與目標 thread 都附接
    assert ("Attach", 1, 200, False) in u.calls         # 用完有 detach
    assert ("Attach", 1, 100, False) in u.calls


def test_force_foreground_true_when_already_foreground():
    u = FakeU32(hwnd=42)
    u.fg = 42                                            # 已是前景
    assert force_foreground(42, user32=u, kernel32=FakeK32()) is True
    assert all(c[0] != "SetForegroundWindow" for c in u.calls)   # 不必再切


def test_force_foreground_false_on_error():
    class Boom:
        def ShowWindow(self, *a):
            raise RuntimeError("壞了")
    assert force_foreground(42, user32=Boom(), kernel32=FakeK32()) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_win32_foreground.py -v`
Expected: FAIL（`ModuleNotFoundError: ...win32.foreground`）

- [ ] **Step 3: 最小實作**

Create `src/keyboard_executor/platforms/win32/foreground.py`：
```python
"""Windows 強制前景：用 AttachThreadInput 繞過 SetForegroundWindow 的前景鎖。

別的程式握有前景、且本程式不被允許搶前景時，一般 SetForegroundWindow 只會閃
工作列而不真的切換。把本執行緒的輸入佇列附接到前景與目標視窗的執行緒後再切，
可繞過此限制。純 best-effort：任何失敗都吞掉，最後以 GetForegroundWindow 判定。
僅 Windows 使用；把視窗叫到前景是通用視窗管理，非反偵測。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SW_RESTORE = 9


def force_foreground(hwnd: int, *, user32=None, kernel32=None) -> bool:
    """把 hwnd 硬切到前景，回傳是否成功（GetForegroundWindow == hwnd）。"""
    try:
        if user32 is None or kernel32 is None:
            import ctypes
            user32 = user32 or ctypes.windll.user32
            kernel32 = kernel32 or ctypes.windll.kernel32
        user32.ShowWindow(hwnd, _SW_RESTORE)              # 還原最小化
        if user32.GetForegroundWindow() == hwnd:
            return True
        cur_tid = kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        attached = []
        for tid in (fg_tid, target_tid):
            if tid and tid != cur_tid and user32.AttachThreadInput(cur_tid, tid, True):
                attached.append(tid)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(cur_tid, tid, False)
        return bool(user32.GetForegroundWindow() == hwnd)
    except Exception:
        logger.warning("強制前景失敗", exc_info=True)
        return False
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_win32_foreground.py -v`
Expected: PASS（3 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/win32/foreground.py tests/platforms/test_win32_foreground.py
git commit -m "feat(win32): force_foreground 用 AttachThreadInput 繞過前景鎖"
```

---

### Task 2: `PywinctlWindowManager.activate` 加還原/重試/force seam

**Files:**
- Modify: `src/keyboard_executor/platforms/common/window_pywinctl.py`（`__init__`、`activate`、常數）
- Test: `tests/platforms/test_window_pywinctl.py`（沿用檔內 `StubWindow`/`StubPwc`/`FakeClock`/`make_manager`；擴充 `StubWindow`）

**Interfaces:**
- Consumes: 注入的 `force_foreground(hwnd) -> bool`（Task 1 的實作，或測試的 fake）。
- Produces: `PywinctlWindowManager(pwc=None, sleep=..., clock=..., force_foreground=None)`；`activate` 行為：還原最小化 → 迴圈（檢查 isActive → 重試 activate → grace 後呼叫 force_foreground 一次）→ 回 `isActive`。

- [ ] **Step 1: 寫失敗測試**

先擴充 `tests/platforms/test_window_pywinctl.py` 的 `StubWindow`（加 `minimized` 參數與 `restore`/`getHandle`，additive，不影響既有測試）：
```python
class StubWindow:
    def __init__(self, title, app="App", box=(10, 20, 800, 600), active=False,
                 alive=True, minimized=False, handle_id=1234):
        self.title = title
        self._app = app
        self.box = SimpleNamespace(left=box[0], top=box[1], width=box[2], height=box[3])
        self.isActive = active
        self.isAlive = alive
        self.isMinimized = minimized
        self.activate_calls = 0
        self.restore_calls = 0
        self._handle_id = handle_id

    def getAppName(self):
        return self._app

    def activate(self):
        self.activate_calls += 1

    def restore(self):
        self.restore_calls += 1
        self.isMinimized = False

    def getHandle(self):
        return self._handle_id
```
再於檔末新增：
```python
def test_activate_restores_minimized_window():
    stub = StubWindow("目標", minimized=True)

    def activate_side():
        stub.activate_calls += 1
        stub.isActive = True

    stub.activate = activate_side
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert stub.restore_calls == 1
    assert stub.isMinimized is False


def test_activate_retries_activate_until_active():
    stub = StubWindow("目標")

    def activate_side():
        stub.activate_calls += 1
        if stub.activate_calls >= 3:        # 第三次才成功 → 證明有重試
            stub.isActive = True

    stub.activate = activate_side
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert stub.activate_calls >= 3


def test_activate_calls_force_foreground_after_grace():
    stub = StubWindow("目標")               # 靠自己永遠切不到
    forced = []

    def fake_force(hwnd):
        forced.append(hwnd)
        stub.isActive = True                # 強制前景成功
        return True

    clock = FakeClock()
    manager = PywinctlWindowManager(pwc=StubPwc([stub]), sleep=clock.sleep,
                                    clock=clock.monotonic, force_foreground=fake_force)
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert forced == [stub.getHandle()]     # grace 過後呼叫恰一次，帶 handle


def test_activate_no_force_when_active_before_grace():
    stub = StubWindow("目標")
    forced = []

    def activate_side():
        stub.activate_calls += 1
        stub.isActive = True                # 立刻成功（grace 之前）

    stub.activate = activate_side
    clock = FakeClock()
    manager = PywinctlWindowManager(pwc=StubPwc([stub]), sleep=clock.sleep,
                                    clock=clock.monotonic,
                                    force_foreground=lambda hwnd: forced.append(hwnd))
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert forced == []                     # grace 前就成功，不呼叫 force
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_window_pywinctl.py -k "restore or retries or force" -v`
Expected: FAIL（`PywinctlWindowManager` 無 `force_foreground` 參數 / 不還原 / 不重試）

- [ ] **Step 3: 最小實作**

`window_pywinctl.py`：常數區加 `_FORCE_GRACE = 0.3`（`_POLL_INTERVAL` 已有）。`__init__` 加參數：
```python
    def __init__(self, pwc=None, sleep=time.sleep, clock=time.monotonic,
                 force_foreground=None):
        if pwc is None:
            import pywinctl as pwc
        self._pwc = pwc
        self._sleep = sleep
        self._clock = clock
        self._force_foreground = force_foreground
```
把 `activate` 整個換成：
```python
    def activate(self, window: WindowInfo, timeout_ms: int = 3000) -> bool:
        w = window.handle
        if getattr(w, "isMinimized", False):
            try:
                w.restore()          # 最小化先還原，否則切前景常無效
            except Exception:
                pass
        deadline = self._clock() + timeout_ms / 1000
        force_at = self._clock() + _FORCE_GRACE   # 先讓 pywinctl 試，grace 過才強切
        forced = False
        while True:
            if w.isActive:
                return True
            try:
                w.activate()          # 重試（不再只呼叫一次）
            except Exception:
                pass
            if (not forced and self._force_foreground is not None
                    and self._clock() >= force_at):
                forced = True
                try:
                    self._force_foreground(w.getHandle())   # Windows：AttachThreadInput 強切
                except Exception:
                    pass
            if self._clock() >= deadline:
                return bool(w.isActive)
            self._sleep(_POLL_INTERVAL)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_window_pywinctl.py -v`
Expected: PASS（新增 4 項與既有全數；既有 `test_activate_returns_true...`（斷言 `activate_calls == 1`）因「先檢查 isActive 再重試」而仍為 1、`test_activate_times_out...` 仍回 False）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/common/window_pywinctl.py tests/platforms/test_window_pywinctl.py
git commit -m "feat(window): activate 加還原最小化、重試、win32 強制前景 seam"
```

---

### Task 3: 工廠 win32 分支接上 force_foreground

**Files:**
- Modify: `src/keyboard_executor/platforms/factory.py`（win32 分支 26-40）
- Test: `tests/platforms/test_factory.py`

**Interfaces:**
- Consumes: `win32.foreground.force_foreground`（Task 1）、`PywinctlWindowManager(force_foreground=...)`（Task 2）。
- Produces: win32 平台的 `window_manager._force_foreground is force_foreground`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_factory.py` 末端新增（沿用檔頭 `sys`/`pytest`/`get_platform`）：
```python
@pytest.mark.skipif(sys.platform != "win32", reason="僅在 Windows 驗證")
def test_win32_wires_force_foreground_into_window_manager():
    from keyboard_executor.platforms.win32.foreground import force_foreground
    platform = get_platform()
    assert platform.window_manager._force_foreground is force_foreground
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_factory.py -k "force_foreground" -v`
Expected: FAIL（工廠建 `PywinctlWindowManager()` 未帶 `force_foreground`，屬性為 `None`）

- [ ] **Step 3: 最小實作**

`factory.py` 的 win32 分支：import 加入 foreground，並把 manager 建構帶入 seam：
```python
    if plat == "win32":
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
        from keyboard_executor.platforms.common.ocr_paddle import PaddleOcrEngine
        from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager
        from keyboard_executor.platforms.win32.dpi import ensure_dpi_awareness
        from keyboard_executor.platforms.win32.foreground import force_foreground
        from keyboard_executor.platforms.win32.input import Win32InputBackend

        ensure_dpi_awareness()
        return Platform(
            input_backend=Win32InputBackend(game_input_mode=game_input_mode),
            window_manager=PywinctlWindowManager(force_foreground=force_foreground),
            screen_capture=MssScreenCapture(),
            ocr_engine=PaddleOcrEngine(lang=ocr_lang),  # PP-OCRv5 跨平台，取代原生 OCR
        )
```
（darwin 分支不動——不帶 `force_foreground`，維持 `None`。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_factory.py -v`
Expected: PASS（win32 host 上新項通過；既有全數不變）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/factory.py tests/platforms/test_factory.py
git commit -m "feat(factory): win32 把 force_foreground 接入視窗管理器"
```

---

### Task 4: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 671 + 新增約 8 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~3); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後連同先前累積的改動一起重打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序）。實機驗收：把目標遊戲視窗**最小化**或讓別的視窗在前景，按「執行」→ 應可靠地把遊戲叫到前景後才開始送輸入；若原本會出現「無法將視窗切到前景」而中止，改善後應減少。此步驟在計畫外，由使用者驅動。
