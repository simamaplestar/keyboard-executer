# 停止腳本立即中斷 — 設計文件

- **日期**：2026-07-09
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

按「停止」時不是立即停，而是要等目前這個動作跑完才停。根因：`Player` 是合作式停止，只在動作之間（`_run_actions` 每個動作前）、每次 loop/repeat 迭代前、以及 wait/poll 迴圈內呼叫 `_check_stop()`。`delay` 與 `等待圖像/文字` 已用可中斷的 `self._sleep`（`stop_event.wait`）等待，按停止會即刻醒來；但**按鍵 hold**（`key_press` 的 `hold_ms`）在輸入後端以不感知停止的 `time.sleep(hold_ms/1000)` 撐住按鍵，中途無法中斷，且若硬中斷會**卡鍵**（keyDown→sleep→keyUp，跳過 keyUp）。

目標：長按鍵動作也能**即時中斷**，且中斷時**保證放開已按下的鍵**。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 做法 | **B：Player 掌管 hold** — 後端加 `key_down`/`key_up`，Player 以自身可中斷的 `_sleep` 等待、`finally` 保證放鍵 |
| 範圍 | 聚焦「按鍵 hold 即時可停 + 保證放鍵」；`delay`/`等待` 本來就即時、不改 |
| OCR 限制 | 單次 OCR `recognize` 是一次 C++ 呼叫，無法中途打斷（有上限、幾秒），如實接受 |
| `text_input`/`mouse_drag` 的 `_SETTLE`（0.05s） | 過短，暫不動（YAGNI） |

## 3. 為什麼 B 而非 A

- **A**：把 stop-aware 的 sleep 注入後端（透過 `get_platform` 串 `stop_event`）— 要動 `get_platform` 與 RunController/WatchController 接線，且後端與 stop_event 耦合。
- **B（採用）**：停止邏輯留在本來就握有 `stop_event` 與可中斷 `_sleep` 的 `Player`；後端維持單純輸入裝置；用 `finally` 明確保證放鍵；不動 `get_platform`／控制器接線。

## 4. 各元件改動

### 4.1 `platforms/base.py`（`InputBackend` 介面）
新增抽象方法 `key_down(self, key: str) -> None`、`key_up(self, key: str) -> None`。

### 4.2 `platforms/common/input_pynput.py`（`PynputInputBackend`）
```python
def key_down(self, key: str) -> None:
    self._kb.press(parse_key(key))

def key_up(self, key: str) -> None:
    self._kb.release(parse_key(key))
```
`key_press` 不變（供 `hold_ms==0` 即時點按與直接呼叫者）。

### 4.3 `platforms/win32/input.py`（`Win32InputBackend`，game mode）
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

### 4.4 `core/player.py`（`_run_one` 的 `KEY_PRESS` 分支）
```python
if atype is ActionType.KEY_PRESS:
    self._ensure_alive(win)
    hold_ms = p["hold_ms"]
    if hold_ms > 0:
        backend.key_down(p["key"])
        try:
            self._sleep(hold_ms / 1000)   # 可中斷：一停止即返回
        finally:
            backend.key_up(p["key"])      # 無論如何都放開，不卡鍵
    else:
        backend.key_press(p["key"], 0)    # 即時點按，維持原行為
```
其餘動作分支不變。停止途中：`_sleep` 立刻返回 → `finally` 放鍵 → 下一個 `_check_stop()`（下一動作前）中止回放。

### 4.5 測試假件
`tests/fakes.py` 的 `FakeInputBackend` 補 `key_down`/`key_up`（記錄呼叫），供 Player 測試斷言。

## 5. 資料流／中止時序

1. 使用者按停止 → 控制器 `stop()` → `stop_event.set()`（即時）。
2. 若正在 `key_press` hold：`self._sleep(hold_ms)` == `stop_event.wait(...)` 立刻返回 → `finally` `key_up` 放鍵。
3. Player 回到 `_run_actions` 迴圈，下一個動作前 `_check_stop()` 見 `stop_event` 已設 → 拋 `_PlayerAbort("已手動停止")` → `play` 回 `PlayResult(ok=False)`。

## 6. 錯誤處理

- `key_up` 於 `finally`，即使 `_sleep` 或後續拋例外也保證放鍵。
- `key_down` 之後、`_sleep` 之前若 `_ensure_alive` 等已通過；hold 期間視窗關閉不另檢查（維持現況，鍵仍會在 finally 放開）。
- 後端 `key_up` 自身例外（罕見）不吞——與現有 `key_press` 一致由上層 `play` 的 except 收斂為 `PlayResult(ok=False)`。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `input_pynput` | `key_down`/`key_up` 呼叫 `_kb.press`/`_kb.release`（注入假 keyboard 斷言） |
| `win32/input` | game mode 下 `key_down`/`key_up` 走 `pdi.keyDown`/`keyUp`；非 game mode 走 pynput（注入假 pdi/keyboard） |
| `player` | `KEY_PRESS` 且 `hold_ms>0` → 依序 `key_down` → `_sleep` → `key_up`；**停止途中（注入的 `_sleep` 內 set stop_event）→ `key_up` 仍被呼叫**、且 `play` 回 `ok=False`；`hold_ms==0` → 走 `key_press(key, 0)` 不變 |

## 8. 非目標（YAGNI）

- 讓單次 OCR `recognize` 可中途打斷（技術上不可行，接受幾秒上限）。
- 讓 `text_input`/`mouse_drag` 逐字/逐步可中斷（`_SETTLE` 過短，效益低）。
- 強制終止工作執行緒（不安全，不做）。
