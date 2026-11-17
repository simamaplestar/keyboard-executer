# 強化目標視窗前景切換 — 設計文件

- **日期**：2026-07-10
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

腳本開始執行時，Player 會呼叫 `window_manager.activate(目標視窗)` 把目標視窗（通常是遊戲）叫到前景；叫不到就中止並顯示「無法將視窗切到前景」。目前的 `activate` 只呼叫一次 `w.activate()` 再輪詢 `isActive`——**最小化不還原、失敗不重試、Windows 前景鎖擋住時沒有更強手法**，導致某些情況（視窗最小化、被前景鎖擋）切不過去、腳本白白中止。

要強化這段前景切換，讓「開始時把目標視窗帶到前景」更可靠。這是通用、正當的視窗管理（讓自動化在前景**看得見**地跑），非反偵測/背景隱藏。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 最小化 | `activate` 開頭若視窗最小化 → 先 `restore()`（跨平台） |
| 重試 | 在 timeout 內重試 `w.activate()`（不再只呼叫一次；跨平台） |
| Windows 強制前景 | 新增 `platforms/win32/foreground.py` 的 `force_foreground(hwnd)`：AttachThreadInput + SetForegroundWindow + BringWindowToTop 繞過前景鎖 |
| 接線 | `force_foreground` 為**注入 seam** 傳入 `PywinctlWindowManager`（win32 預設真實 ctypes 實作，其他平台為 None） |
| 行為不變 | 逾時仍切不到 → 回 `False`（Player 照舊中止顯示「無法將視窗切到前景」）；`activate` 簽名 `(window, timeout_ms=3000) -> bool` 不變 |
| 定位 | 通用視窗管理，非反作弊/反偵測繞過 |

## 3. 元件改動

### 3.1 `platforms/win32/foreground.py`（新檔，Windows 專屬 ctypes）

```python
def force_foreground(hwnd: int) -> bool:
    """用 AttachThreadInput 繞過前景鎖，把 hwnd 硬切到前景。回傳是否成功。
    純 best-effort：任何步驟失敗都吞掉，最後以 GetForegroundWindow == hwnd 判定。"""
```
實作要點（ctypes user32/kernel32）：
- `ShowWindow(hwnd, SW_RESTORE=9)` 先還原（保險）。
- 取 `GetForegroundWindow()`；若已等於 hwnd → 回 True。
- `GetWindowThreadProcessId` 取目標與前景視窗的 thread id、`GetCurrentThreadId` 取本執行緒。
- 對前景 thread 與目標 thread 各 `AttachThreadInput(cur, tid, True)`（tid 有效且非自身時）。
- `try: BringWindowToTop(hwnd); SetForegroundWindow(hwnd) finally: 逐一 AttachThreadInput(..., False) 還原`。
- 回 `GetForegroundWindow() == hwnd`。
- 所有 ctypes 呼叫外層 try/except 保護，不外拋。

### 3.2 `platforms/common/window_pywinctl.py`（`PywinctlWindowManager`）

- `__init__` 新增參數 `force_foreground=None`（注入 seam），存 `self._force_foreground`。
- `activate(window, timeout_ms=3000)` 改為：
  1. `w = window.handle`；若 `getattr(w, "isMinimized", False)` 為真 → `try: w.restore() except Exception: pass`。
  2. `deadline = clock() + timeout_ms/1000`；記 `force_at = clock() + _FORCE_GRACE`（grace ~0.3s，給 pywinctl 先試的時間）；`forced = False`。
  3. 首次 `try: w.activate() except Exception: pass`。
  4. 迴圈 `while clock() < deadline`：
     - `if w.isActive: return True`
     - `try: w.activate() except Exception: pass`（重試）
     - 若 `not forced and self._force_foreground is not None and clock() >= force_at`：`forced = True`；`try: self._force_foreground(w.getHandle()) except Exception: pass`。
     - `sleep(_POLL_INTERVAL)`
  5. 回 `bool(w.isActive)`。
- 常數 `_FORCE_GRACE = 0.3`（秒）。

### 3.3 `platforms/factory.py`（win32 接線）

- 建 `PywinctlWindowManager` 時，於 win32 傳入 `force_foreground=<win32.foreground.force_foreground>`；非 win32 不傳（預設 None）。以 `sys.platform == "win32"` 或既有平台分支判斷（沿用工廠既有結構）。

## 4. 資料流

腳本開始 → Player `_acquire_window` → `wm.activate(win)`：還原最小化 →（pywinctl activate 重試）→ grace 過仍未前景且 win32 → `force_foreground(hwnd)` →（回 True/False）→ Player 依結果繼續或中止。

## 5. 錯誤處理

- `w.restore()` / `w.activate()` / `force_foreground` 任一拋例外都吞掉（best-effort），不使 `activate` 崩潰。
- `force_foreground` 內所有 ctypes 呼叫失敗都吞掉，最後以前景比對回傳結果。
- 逾時仍切不到 → 回 `False`（既有 Player 行為不變：中止 + 「無法將視窗切到前景」）。

## 6. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `window_pywinctl` | 注入 fake 視窗（`isActive`/`isMinimized`/`restore`/`activate`/`getHandle`）+ 既有 `clock`/`sleep` + fake `force_foreground`：① 最小化時 `activate` 會呼叫 `restore()`；② 首次沒前景時會**重試** `w.activate()`（呼叫次數 > 1）；③ pywinctl 一直切不過去且 grace 已過 → `force_foreground` 被呼叫**恰一次**且帶 `getHandle()` 的值；④ 一開始就 `isActive` → 不呼叫 `force_foreground`、快速回 True；⑤ 全程切不到 → 回 False |

真實 win32 `force_foreground`（ctypes AttachThreadInput/SetForegroundWindow）與工廠 win32 接線列**人工驗收**（同 `global_hotkey.py`，離屏/非 win32 測試不覆蓋）。

## 7. 非目標（YAGNI）

- **不**做「對背景視窗定向送輸入」（PostMessage/背景掛機）——那對遊戲多半無效且屬 botting-enablement，不做。
- **不**做常駐「置頂(always-on-top)」——只在開始時切到前景一次（Player 既有時機不變）。
- **不**改 `activate` 的簽名或 Player 呼叫時機。
- grace/poll 間隔固定（0.3s / 0.05s），不做可設定。
