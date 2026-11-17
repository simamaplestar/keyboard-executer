# 遊戲可用的按鍵緊急停止 + 滑鼠角落開關 — 設計文件

- **日期**：2026-07-10
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

兩個已確認的問題（本 session 系統性除錯查出）：

- **A：腳本一失去焦點就停。** 根因：焦點切到全螢幕遊戲時，作業系統/遊戲把游標甩到 (0,0)，落在左上角 5×5 failsafe 範圍 → `stop_event.set()` → 腳本中止。使用者的 log 已證實出現「偵測到緊急停止：滑鼠甩到螢幕左上角 → 中止」。
- **B：遊戲裡按鍵緊急停止收不到。** RegisterHotKey（F10）已註冊但遊戲在更底層吃掉按鍵，pynput 低階鍵盤 hook 也被擋（既有現象，見 `global_hotkey.py` 註解）。使用者只有滑鼠角落能停，但那正是 A 的誤停元凶。

需求方要：**一個在全螢幕遊戲裡也有效的「按鍵」緊急停止**，並且**讓滑鼠角落 failsafe 不再誤停腳本**。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 按鍵停止機制 | 新增 **GetAsyncKeyState 背景輪詢**（讀 OS 層實體按鍵狀態，不經訊息佇列/使用者態 hook/焦點），與既有 RegisterHotKey、滑鼠角落**並存**互為後盾 |
| 滑鼠角落 failsafe | 設定加**開關**，預設**開**（向後相容）；關掉後角落不再觸發停止 |
| 誠實但書 | 若遊戲反作弊在**核心層(driver)**過濾鍵盤，連 GetAsyncKeyState 也讀不到 → 任何鍵盤法皆無效，唯一解是遊戲切**視窗化/無邊框**。需使用者實機驗證 |
| 定位 | 這是安全性「**停止**」機制，**非**協助自動化規避偵測；不做反作弊/反偵測繞過 |

## 3. Part 1 — GetAsyncKeyState 按鍵停止

### 3.1 新模組 `app/key_stop_poller.py`（Windows 專屬，ctypes；鏡射 `global_hotkey.py` 位置）

```python
class AsyncKeyStopPoller:
    """背景輪詢實體按鍵狀態（GetAsyncKeyState）的緊急停止。
    偵測到 stop_key 由「未按」→「按下」（上升緣）時呼叫 on_trigger。"""
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None,
                 poll_interval: float = 0.03):
        ...
    def start(self, key_name: str) -> bool: ...   # 解析 vk（沿用 vk_for_key）；起 daemon 執行緒
    def stop(self) -> None: ...                    # 設停止旗標並 join
```

- `key_down_fn(vk) -> bool`：預設 `bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)`（高位元＝目前按著）。**注入 seam** 供單元測試。
- `sleep`：預設 `time.sleep`，注入供測試（可在 N 次後令輪詢結束）。
- vk 解析**沿用 `global_hotkey.vk_for_key`**（勿重複實作）；解析不到回 `False`（不啟動）。
- 執行緒迴圈：
  ```
  prev = False
  while not self._stop_flag.is_set():
      down = key_down_fn(vk)
      if down and not prev:      # 上升緣
          on_trigger()
      prev = down
      sleep(poll_interval)
  ```
- 上升緣偵測避免按著不放時重複觸發。

### 3.2 執行緒安全（關鍵）

`on_trigger` 由**背景輪詢執行緒**呼叫，**不是 GUI 執行緒**。既有 `_on_emergency_hotkey` 會呼叫 `self.append_log(...)`（動 Qt widget）——從非 GUI 執行緒動 Qt 會當掉。

**做法**：`MainWindow` 新增 `emergency_stop_requested = Signal()`，在 `__init__` connect 到 `_on_emergency_hotkey`（跨執行緒 emit → Qt 以 queued connection 排到 GUI 執行緒執行，安全）。輪詢器的 `on_trigger` 傳 `self.emergency_stop_requested.emit`。
（RegisterHotKey 路徑本就在 GUI 執行緒，維持直接呼叫 `_on_emergency_hotkey` 不變；兩條路都到同一個 slot。）

### 3.3 wiring（`app/main_window.py`）

- `_setup_global_hotkey` 之外，新增啟動輪詢器：win32 且非 offscreen 時，`AsyncKeyStopPoller(self.emergency_stop_requested.emit)` 並 `.start(self._settings.stop_key)`；存到 `self._key_poller`。失敗僅記錄，不影響其他停止途徑。
- `_reregister_hotkey(stop_key)` 同時**重啟輪詢器**（`stop()` 後 `start(stop_key)`），與熱鍵一起隨設定更新。
- 關閉視窗（`closeEvent`）時 `self._key_poller.stop()`。
- 三機制併存：RegisterHotKey / GetAsyncKeyState 輪詢 / 滑鼠角落，任一先偵測到即停。

### 3.4 測試

| 層 | 測試 |
|----|------|
| `key_stop_poller` | 注入 `key_down_fn` 回傳腳本化序列（未按→按下→放開）、`sleep` 在數次後令 `stop()`：斷言 `on_trigger` 於上升緣**恰好呼叫一次**；按著不放不重複；未按不呼叫；`start` 對無法解析的鍵回 `False` 不起執行緒 |

（`GetAsyncKeyState` 實體呼叫與 Qt/threads 接線列人工驗收，不進單元測試。）

## 4. Part 2 — 滑鼠角落 failsafe 開關

### 4.1 `core/guard.py`（`SessionGuard`）
- `__init__` 新增參數 `corner_failsafe: bool = True`。
- `handle` 的 `MOUSE_MOVE` 角落判定加閘門：`if self._corner_failsafe and 0 <= x <= corner_size and 0 <= y <= corner_size: stop`。關閉時角落完全不觸發。
- 熱鍵（stop_key）與 toggle 行為不變。

### 4.2 `app/settings.py`（`Settings` + 正規化 + Store）
- `Settings` 新增 `corner_failsafe: bool = True`。
- 正規化/驗證：非布林拒絕（沿用既有機制）；缺鍵預設 `True`（向後相容舊設定檔）。
- `SettingsStore` 讀寫此欄位。

### 4.3 `app/settings_page.py`（UI）
- 加一個勾選框「滑鼠左上角緊急停止（游標甩到左上角即停）」，綁 `corner_failsafe`，預設勾選。存檔經既有 `saved` Signal 即時套用。

### 4.4 控制器接線（沿用 `stop_key` 的既有流路）
- `RunController` / `WatchController`：建構子與 `apply_settings` 新增 `corner_failsafe`，於 `_start_guard` 建 `SessionGuard(..., corner_failsafe=self._corner_failsafe)`。
- `MainWindow`：建立控制器與 `_apply_settings` 時把 `self._settings.corner_failsafe` 傳入（與 `stop_key` 同處）。
- `cli.run_watch` / `run_record`：建 `SessionGuard` 時帶 `corner_failsafe=True`（cli 無設定來源，維持預設開）。

### 4.5 測試

| 層 | 測試 |
|----|------|
| `guard` | `corner_failsafe=False` 時滑鼠移到 (0,0) **不** set stop_event；`True`（預設）時**會** set（現況）；stop_key 熱鍵兩種設定都仍有效 |
| `settings` | `corner_failsafe` round-trip；缺鍵預設 `True`；非布林拒絕 |
| `run_controller`/`watch_controller` | `corner_failsafe` 由建構子/apply_settings 傳抵 `SessionGuard`（注入 guard_factory 斷言收到旗標） |

## 5. 資料流

- 按鍵停止：實體按鍵 → 輪詢器上升緣 → `emergency_stop_requested.emit`（跨執行緒）→ GUI 執行緒 `_on_emergency_hotkey` → `run_controller.stop()` + `watch_controller.stop()`（皆 `Event.set`，執行緒安全）。
- 角落開關：設定 `corner_failsafe` → 控制器 → `SessionGuard` 角落判定閘門。

## 6. 錯誤處理

- 輪詢器啟動失敗（非 win32/離屏/解析不到鍵）：記錄一次警告，不影響 RegisterHotKey 與滑鼠角落。
- 輪詢執行緒內例外：記錄不外拋，不拖垮應用。
- `on_trigger`（Signal emit）本身執行緒安全；GUI 端 slot 的既有 try 不變。

## 7. 非目標（YAGNI）

- **不**做核心層/驅動層鍵盤讀取、Raw Input、DirectInput 逆向或任何反作弊/反偵測繞過。GetAsyncKeyState 只是讀「停止鍵」以**中止**自動化的安全機制；若遊戲核心層過濾鍵盤，接受無解、建議視窗化。
- **不**做每條腳本各自的角落開關（全域一個設定即可）。
- **不**改滑鼠角落的位置/大小為可設定（YAGNI）。
- 輪詢間隔固定 30ms，不做可設定。
