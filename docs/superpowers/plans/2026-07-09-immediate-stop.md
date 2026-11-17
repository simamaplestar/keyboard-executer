# 停止腳本立即中斷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓按鍵 hold 動作可即時中斷並保證放鍵——輸入後端加 `key_down`/`key_up`，Player 對 `hold_ms>0` 改用「key_down → 可中斷的 `_sleep` → `finally` key_up」。

**Architecture:** 停止邏輯留在本來就握有 `stop_event` 與可中斷 `_sleep` 的 `Player`；後端只多兩個單純的 `key_down`/`key_up`。Player 撐 hold 時用自身可中斷的 `_sleep`，並以 `finally` 保證放鍵，不卡鍵；停止途中 `_sleep` 立即返回、放鍵後由下一個 `_check_stop` 中止。

**Tech Stack:** Python 3.13 / pynput / pydirectinput（win32 game mode）/ pytest。

## Global Constraints

- `hold_ms == 0`（即時點按）維持呼叫 `backend.key_press(key, 0)` 不變（既有測試皆用 hold_ms=0，須續過）。
- `key_up` 必須在 `finally`，保證中斷時放鍵、不卡鍵。
- 不動 `get_platform`／控制器接線；不改 `delay`/`等待`（本來就即時）。
- 面向使用者訊息維持繁中現況。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/platforms/base.py` | `InputBackend` 介面加抽象 `key_down`/`key_up` | Modify |
| `src/keyboard_executor/platforms/common/input_pynput.py` | pynput 實作 `key_down`/`key_up` | Modify |
| `src/keyboard_executor/platforms/win32/input.py` | game mode 走 pdi 的 `key_down`/`key_up` | Modify |
| `tests/fakes.py` | `FakeInputBackend.key_down`/`key_up`（記錄呼叫） | Modify |
| `src/keyboard_executor/core/player.py` | `_run_one` 的 `KEY_PRESS` hold 分支 | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

---

### Task 1: 後端 `key_down` / `key_up`

**Files:**
- Modify: `src/keyboard_executor/platforms/base.py`（`InputBackend`）
- Modify: `src/keyboard_executor/platforms/common/input_pynput.py`（`PynputInputBackend`）
- Modify: `src/keyboard_executor/platforms/win32/input.py`（`Win32InputBackend`）
- Modify: `tests/fakes.py`（`FakeInputBackend`）
- Test: `tests/platforms/test_input_pynput.py`、`tests/platforms/test_win32_input.py`

**Interfaces:**
- Produces: `InputBackend.key_down(key: str) -> None`、`InputBackend.key_up(key: str) -> None`（三個實作 + FakeInputBackend）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_input_pynput.py` 末端新增（沿用檔內 `SpyKeyboard`、`SpyMouse`、`PynputInputBackend`）：
```python
def test_key_down_then_key_up_press_and_release_same_key():
    kb, mouse = SpyKeyboard(), SpyMouse()
    backend = PynputInputBackend(keyboard=kb, mouse=mouse, sleep=lambda s: None)
    backend.key_down("a")
    backend.key_up("a")
    assert [op[0] for op in kb.ops] == ["press", "release"]
    assert kb.ops[0][1] == kb.ops[1][1]      # 同一顆鍵先 press 後 release
```
在 `tests/platforms/test_win32_input.py` 末端新增（沿用檔內 `make_game_backend`）：
```python
def test_game_mode_key_down_and_key_up_use_pydirectinput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.key_down("a")
    backend.key_up("a")
    assert pdi.ops == [("keyDown", "a"), ("keyUp", "a")]
    assert kb.ops == []       # 不走 pynput
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py -k "key_down" -v`
Expected: FAIL（`AttributeError`／`TypeError`：`key_down` 不存在，或 ABC 未實作）

- [ ] **Step 3: 最小實作**

3a. `base.py` 的 `InputBackend`，在 `key_press` 抽象方法之後加：
```python
    @abstractmethod
    def key_down(self, key: str) -> None: ...

    @abstractmethod
    def key_up(self, key: str) -> None: ...
```

3b. `input_pynput.py` 的 `PynputInputBackend`，在 `key_press` 之後加：
```python
    def key_down(self, key: str) -> None:
        self._kb.press(parse_key(key))

    def key_up(self, key: str) -> None:
        self._kb.release(parse_key(key))
```

3c. `win32/input.py` 的 `Win32InputBackend`，在 `key_press` 之後加：
```python
    def key_down(self, key: str) -> None:
        if self._pdi is None:
            return super().key_down(key)
        self._pdi.keyDown(key)

    def key_up(self, key: str) -> None:
        if self._pdi is None:
            return super().key_up(key)
        self._pdi.keyUp(key)
```

3d. `tests/fakes.py` 的 `FakeInputBackend`，在 `key_press` 之後加：
```python
    def key_down(self, key: str) -> None:
        self.calls.append(("key_down", key))

    def key_up(self, key: str) -> None:
        self.calls.append(("key_up", key))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/base.py src/keyboard_executor/platforms/common/input_pynput.py src/keyboard_executor/platforms/win32/input.py tests/fakes.py tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py
git commit -m "feat(input): 後端加 key_down / key_up（含 game mode）"
```

---

### Task 2: Player 對 `hold_ms>0` 用 key_down + 可中斷 wait + finally key_up

**Files:**
- Modify: `src/keyboard_executor/core/player.py`（`_run_one` 的 `KEY_PRESS` 分支）
- Test: `tests/core/test_player_basic.py`（既有檔，新增測試；沿用 `make_platform`/`make_script`）

**Interfaces:**
- Consumes: `InputBackend.key_down`/`key_up`（Task 1）、既有 `self._sleep`（可中斷）、`FakeInputBackend.calls`
- Produces: `KEY_PRESS` 且 `hold_ms>0` → `key_down` → `_sleep(hold_ms/1000)` → `finally key_up`；`hold_ms==0` → `key_press(key, 0)` 不變。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_player_basic.py` 末端新增（沿用檔頭 `threading`、`make_platform`、`make_script`、`Player`）：
```python
def test_key_press_hold_uses_key_down_wait_key_up():
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_press", "key": "a", "hold_ms": 300}]))
    assert backend.calls == [("key_down", "a"), ("key_up", "a")]
    assert sleeps == [0.3]     # 以可中斷 _sleep 撐 hold（0.3 秒）


def test_key_press_hold_releases_key_and_aborts_on_stop():
    platform, backend, _ = make_platform()
    stop = threading.Event()

    def sleep_then_stop(seconds):
        stop.set()             # 模擬 hold 途中按下停止

    result = Player(platform, stop_event=stop, sleep=sleep_then_stop).play(
        make_script([{"type": "key_press", "key": "a", "hold_ms": 500},
                     {"type": "key_press", "key": "b"}]))
    assert backend.calls == [("key_down", "a"), ("key_up", "a")]  # a 放開、b 未送
    assert result.ok is False                                     # 停止後中止
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_player_basic.py -k "hold" -v`
Expected: FAIL（現況呼叫 `backend.key_press("a", 300)` → `calls` 為 `[("key_press", "a", 300), …]`，非 key_down/key_up）

- [ ] **Step 3: 最小實作**

`player.py` 的 `_run_one`，把 `KEY_PRESS` 分支
```python
        if atype is ActionType.KEY_PRESS:
            self._ensure_alive(win)
            backend.key_press(p["key"], p["hold_ms"])
```
改為：
```python
        if atype is ActionType.KEY_PRESS:
            self._ensure_alive(win)
            if p["hold_ms"] > 0:
                # hold 由 Player 掌管：用可中斷的 _sleep 撐住，finally 保證放鍵，
                # 停止途中不卡鍵、放鍵後由下一個 _check_stop 中止。
                backend.key_down(p["key"])
                try:
                    self._sleep(p["hold_ms"] / 1000)
                finally:
                    backend.key_up(p["key"])
            else:
                backend.key_press(p["key"], 0)   # 即時點按，維持原行為
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_player_basic.py -v`
Expected: PASS（新增 2 項與既有全數——既有 KEY_PRESS 測試皆用 hold_ms=0，走 `key_press(key, 0)` 不變）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_basic.py
git commit -m "feat(player): 按鍵 hold 改用可中斷等待＋finally 放鍵，停止即時不卡鍵"
```

---

### Task 3: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 + 新增 4 項；容許既有 4 skipped）。既有所有 KEY_PRESS 動作皆 hold_ms=0，走不變路徑；其餘後端子類皆繼承 `FakeInputBackend` 的新方法。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~2); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重新打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序）。實機驗收：做一個含「按住某鍵數秒（hold_ms 大）」的腳本，執行後在 hold 途中按停止 → 應**立即停下且該鍵已放開**（不卡鍵）。此步驟在計畫外，由使用者驅動。
