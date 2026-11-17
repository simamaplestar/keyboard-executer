# 每腳本啟動快捷鍵 — 設計文件

- **日期**：2026-07-13
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

使用者希望「每個腳本都可以設定一個啟動快捷鍵（單鍵或組合鍵），按下該熱鍵就執行那個腳本」，而且**在遊戲/背景時也要有效**（沿用緊急停止那套 `GetAsyncKeyState` 背景輪詢，不靠焦點、不靠低階 hook）。

過程中一併確認兩項相關調整，因同屬「熱鍵與停止控制」範疇故併入本設計：

- **多鍵組合錄製**：目前組合鍵錄製只收得到「N 個修飾鍵＋1 個主鍵」，按 `shift+a+方向鍵` 只錄到 `shift+a`。要能收 3 鍵以上（單元六）。
- **緊急停止不再停監看**：按下緊急停止只中止腳本回放，監看規則完全獨立、只由「停止監看」按鈕停止（單元七）。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 生效範圍 | **遊戲/背景也要**——用 `GetAsyncKeyState` 背景輪詢讀實體按鍵狀態（同 `AsyncKeyStopPoller`），不經焦點/訊息佇列/使用者態 hook |
| 已有腳本在跑時按熱鍵 | **先停現在跑的、再跑新的**（熱鍵可在腳本執行中切換腳本） |
| 熱鍵形式 | 單鍵（`f5`）或組合鍵（`ctrl+shift+1`）；空＝不設 |
| 兩腳本同熱鍵 | 建綁定時**去重**：清單排序先出現者拿走該熱鍵，其餘記一行警告並略過 |
| 熱鍵含緊急停止鍵 | 略過該綁定並警告（緊急停止優先，避免一按又停又跑） |
| 組合鍵鍵數 | 錄製改「累積＋放開才定案」，支援 3 鍵以上（如 `shift+a+right`）；修飾鍵固定序在前 |
| 緊急停止與監看 | 緊急停止（停止鍵／背景輪詢／滑鼠甩左上角）只停回放，**監看完全獨立**，僅由「停止監看」按鈕停止 |
| 定位 | 純觸發便利功能，非反偵測 |

**但書（已向使用者說明）**：`GetAsyncKeyState` 只「讀」不「攔」——單鍵熱鍵若遊戲也用該鍵，兩邊都會動（遊戲照收）；建議用遊戲不用的鍵或組合鍵。遊戲若在核心層過濾鍵盤，連這也讀不到（同緊急停止但書）。

## 3. 架構總覽

七個獨立單元，各有單一職責、可獨立測試（單元一～五為啟動快捷鍵主體，六、七為併入的相關調整）：

1. **`ScriptSettings.hotkey`（資料）** — 腳本設定新增 `hotkey: str` 欄位，隨腳本存檔。
2. **`vk_for_key` 擴充＋`hotkey_to_vks`（對應）** — 熱鍵字串 → Windows 虛擬鍵碼清單。
3. **`ScriptHotkeyPoller`（偵測）** — 多綁定版 `GetAsyncKeyState` 背景輪詢器，上升緣觸發。
4. **腳本編輯器欄位（UI）** — 用既有 `_KeyCaptureEdit(combo=True)` 擷取熱鍵並存進 settings。
5. **主視窗接線（協調）** — `_run_script(name)` 共用執行路徑、綁定建置與去重、poller 生命週期。
6. **多鍵組合錄製（`_KeyCaptureEdit`）** — combo 模式改「累積＋放開才定案」，支援 3 鍵以上。
7. **緊急停止不再停監看** — 拆除監看的緊急停止 guard，`_on_emergency_hotkey` 只停回放。

資料只單向流動：UI → 存檔 → 開機/清單變動時重建綁定 → 背景輪詢 → Qt Signal 排回 GUI 執行緒 → 執行。

## 4. 單元一：`ScriptSettings.hotkey`（`core/models.py`）

### 4.1 欄位
`ScriptSettings` 加 `hotkey: str = ""`（frozen dataclass，接在 `window_retry_interval_ms` 之後）。

### 4.2 驗證（`_validate_settings`）
- `allowed` 集合加入 `"hotkey"`（否則 `_check_no_extra` 會擋掉此鍵）。
- 讀 `hotkey = data.get("hotkey", defaults.hotkey)`；規則：
  - 必須是字串，否則 `_err("settings.hotkey 必須是字串")`。
  - `strip()` 後為空 → 視為「未設」，正規化為 `""`（允許）。
  - 非空 → 以 `"+"` 拆開，每個非空部分須 `is_valid_key(part)`；任一不合法 → `_err(f"settings.hotkey 不是可用的按鍵名稱: {part!r}")`。存回時各部分 `strip().lower()` 後以 `"+"` 重組（與 `_KeyCaptureEdit` 產出的 canonical 形式一致）。
- 回傳的 `ScriptSettings(...)` 帶入 `hotkey=正規化後的值`。

### 4.3 序列化（`script_to_dict`）
`settings` dict 加 `"hotkey": s.hotkey`。

### 4.4 相容
舊腳本檔無 `hotkey` 鍵 → `data.get("hotkey", "")` 帶入空字串（不設熱鍵），無破壞。

## 5. 單元二：`vk_for_key` 擴充＋`hotkey_to_vks`（`app/global_hotkey.py`）

### 5.1 修飾鍵對應
`vk_for_key` 目前不認 `ctrl/shift/alt/win`（只有 f 鍵、字母數字、`_VK_SPECIAL`）。新增修飾鍵對應表並在 `_VK_SPECIAL` 命中前先查：

```python
_VK_MODIFIERS = {
    "ctrl": 0x11, "control": 0x11,   # VK_CONTROL
    "shift": 0x10,                    # VK_SHIFT
    "alt": 0x12,                      # VK_MENU
    "win": 0x5B, "super": 0x5B, "cmd": 0x5B,   # VK_LWIN
}
```

在 `vk_for_key` 開頭（`_VK_SPECIAL` 判斷之前或合併）加：`if n in _VK_MODIFIERS: return _VK_MODIFIERS[n]`。（`is_valid_key` 已收 `control/super/cmd` 別名，故一併對應以免驗證過關卻解不出 vk。）

### 5.2 熱鍵字串 → vk 清單
新增公開函式（放在 `vk_for_key` 之後）：

```python
def hotkey_to_vks(hotkey: str) -> list[int] | None:
    """熱鍵字串（如 'ctrl+shift+1' 或 'f5'）→ 每個按鍵的 VK 清單；
    任一部分無法對應、或字串為空 → None。"""
    parts = [p for p in (hotkey or "").split("+") if p.strip()]
    if not parts:
        return None
    vks = []
    for p in parts:
        vk = vk_for_key(p)
        if vk is None:
            return None
        vks.append(vk)
    return vks
```

## 6. 單元三：`ScriptHotkeyPoller`（新檔 `app/script_hotkey_poller.py`）

多綁定版 `AsyncKeyStopPoller`：對每個綁定偵測「整組鍵同時按下」的上升緣。沿用相同的執行緒模型、`stop()` 自我 join 防護、可注入 `key_down_fn`/`sleep`。

### 6.1 GetAsyncKeyState 讀取器共用
把 `key_stop_poller.py` 現有的 `_win_key_down` 提升為公開 `win_key_down`（保留 `_win_key_down = win_key_down` 別名以免動到既有引用/測試），新 poller `from keyboard_executor.app.key_stop_poller import win_key_down` 重用，DRY。

### 6.2 介面

```python
class ScriptHotkeyPoller:
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None, poll_interval=0.03):
        # on_trigger: callable(script_name: str) —— 每次某綁定上升緣呼叫一次
        ...
        self._bindings: list[tuple[str, tuple[int, ...]]] = []

    def start(self, bindings) -> bool:
        # bindings: Iterable[(script_name, [vk, ...])]；過濾掉空 vk；
        # 至少一個有效綁定才啟動並回 True，否則回 False（不啟執行緒）。
        ...

    def stop(self) -> None:
        # 設停止旗標；t is not current_thread() 才 join（同 AsyncKeyStopPoller）。
        ...
```

### 6.3 輪詢迴圈（`_run`）
```python
def _run(self):
    prev = {name: False for name, _ in self._bindings}
    while not self._stop_flag.is_set():
        for name, vks in self._bindings:
            try:
                down = all(self._key_down_fn(vk) for vk in vks)
            except Exception:
                logger.warning("腳本熱鍵輪詢讀取失敗", exc_info=True)
                down = False
            if down and not prev.get(name, False):
                try:
                    self._on_trigger(name)
                except Exception:
                    logger.exception("腳本熱鍵觸發處理失敗")
            prev[name] = down
        self._sleep(self._poll_interval)
```

- **上升緣**：整組鍵「全部按下」且上一輪非全部按下 → 觸發一次（按住不重複觸發）。
- 各綁定各自維護 prev 狀態，互不干擾。

## 7. 單元四：腳本編輯器「啟動快捷鍵」欄位（`app/script_editor.py`＋`app/script_editor_model.py`）

### 7.1 `ScriptEditorModel`
鏡射既有 `game_input_mode`：

```python
@property
def hotkey(self) -> str:
    return str(self._settings.get("hotkey", ""))

def set_hotkey(self, value: str) -> None:
    self._settings["hotkey"] = value or ""
```

`new()` 的 `_settings` 字面值加 `"hotkey": ""`。

### 7.2 `ScriptEditorDialog`
在「遊戲模式」勾選框（第 532–535 行）之後加一列標籤＋擷取欄位（`_KeyCaptureEdit` 已 import）：

```python
hk_row = QHBoxLayout()
hk_row.addWidget(QLabel("啟動快捷鍵"))
self.hotkey_edit = _KeyCaptureEdit(combo=True)
self.hotkey_edit.setText(model.hotkey)
hk_row.addWidget(self.hotkey_edit, 1)
layout.addLayout(hk_row)
```

（`combo=True` 讓單鍵或組合鍵都能錄；`_KeyCaptureEdit` 只產 canonical 名稱，存的值一定是驗證與 `hotkey_to_vks` 認得的形式。）

### 7.3 `_on_save`
在 `set_game_input_mode(...)`（第 1076 行）之後加：
```python
self._model.set_hotkey(self.hotkey_edit.text())
```

## 8. 單元五：主視窗接線（`app/main_window.py`）

### 8.1 抽出共用執行路徑 `_run_script(name)`
把 `_on_run_clicked` 的執行主體抽成可重用的 `_run_script(name)`，讓按鈕與熱鍵共用；熱鍵路徑依決策**先停現在跑的、再跑新的**：

```python
def _on_run_clicked(self) -> None:
    self._run_script(self._scripts.selected)

def _run_script(self, name) -> None:
    if name is None:
        self.append_log("請先選取要執行的腳本")
        return
    try:
        job = self._run_controller.build_job(name)
    except ScriptValidationError as e:
        self.append_log(f"腳本載入失敗：{e}")
        return
    # 先停現在跑的、再跑新的（熱鍵可在腳本執行中切換）。
    # 正常結束後 _cleanup_worker 會把 self._worker 設 None，故非 None 即代表仍在跑。
    if self._worker is not None:
        self._run_controller.stop()
        self._cleanup_worker()
    stop_key = self._settings.stop_key.upper()
    self.append_log(f"開始回放：{name}（{stop_key} 或滑鼠甩到螢幕左上角可緊急停止）")
    worker = self._worker_factory(job)
    worker.progress.connect(self._on_progress)
    worker.finished.connect(self._on_run_finished)
    worker.failed.connect(self._on_worker_failed)
    self._worker = worker
    self.run_button.setEnabled(False)
    worker.start()
```

`_cleanup_worker` 改為收尾時先斷開舊 worker 的訊號再 `wait()`、並把 `self._worker` 設 `None`，避免舊 worker 的 `finished/failed` 在新 worker 已就位後回頭誤觸（重新啟用按鈕、或 `wait()` 到錯的 worker），也讓「非 None 即在跑」的判斷成立：

```python
def _cleanup_worker(self) -> None:
    w = self._worker
    if w is None:
        return
    for attr, slot in (("progress", self._on_progress),
                       ("finished", self._on_run_finished),
                       ("failed", self._on_worker_failed)):
        sig = getattr(w, attr, None)      # 假 worker（如 closeEvent 測試的 SpyWorker）可能沒有訊號
        if sig is not None:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
    w.wait()
    self._worker = None
```

- `getattr(..., None)` 守門：既有 closeEvent 測試用只有 `wait()` 的假 worker，不得因存取 `.progress` 而 `AttributeError`。
- `_on_run_finished`/`_on_worker_failed` 呼叫 `_cleanup_worker` 的既有流程不變（斷開自身連線在 Qt 訊號發送中允許）；差別只是收尾後 `self._worker` 歸零。
- `ImmediateWorker`（測試用同步 worker）跑完即歸零，`_run_script` 再次進入時 `self._worker is None` → 不會誤停。

### 8.2 Signal 與生命週期
- 類別屬性（第 47 行 `emergency_stop_requested` 旁）：`script_hotkey_requested = Signal(str)`。
- `__init__`：`self._script_hotkey_poller = None`（同 `_key_poller` 初始化）；在 `emergency_stop_requested.connect(...)` 之後加 `self.script_hotkey_requested.connect(self._run_script)`；在 `_setup_key_poller()` 之後加 `self._setup_script_hotkeys()`。

```python
def _setup_script_hotkeys(self) -> None:
    """Windows：背景輪詢每個腳本的啟動熱鍵（GetAsyncKeyState），
    上升緣經 script_hotkey_requested 排到 GUI 執行緒執行該腳本。"""
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None or app.platformName() == "offscreen":
            return
        from keyboard_executor.app.script_hotkey_poller import ScriptHotkeyPoller
        self._script_hotkey_poller = ScriptHotkeyPoller(self.script_hotkey_requested.emit)
        self._refresh_script_hotkeys()
    except Exception:
        logger.warning("腳本啟動熱鍵無法啟用", exc_info=True)
```

### 8.3 綁定建置與去重
```python
def _build_script_bindings(self) -> list[tuple[str, list[int]]]:
    from keyboard_executor.app.global_hotkey import hotkey_to_vks, vk_for_key
    stop_vk = vk_for_key(self._settings.stop_key)
    claimed: set[frozenset[int]] = set()
    bindings: list[tuple[str, list[int]]] = []
    for name in self._scripts.names:          # list_names() 已排序 → 先出現者贏
        try:
            hk = self._script_storage.load(name).settings.hotkey.strip()
        except ScriptValidationError:
            continue
        if not hk:
            continue
        vks = hotkey_to_vks(hk)
        if vks is None:
            logger.warning("腳本「%s」啟動熱鍵 %s 有無法對應的按鍵，略過", name, hk)
            continue
        if stop_vk is not None and stop_vk in vks:
            logger.warning("腳本「%s」啟動熱鍵 %s 含緊急停止鍵，略過", name, hk)
            continue
        key = frozenset(vks)
        if key in claimed:
            logger.warning("腳本「%s」啟動熱鍵 %s 與其他腳本重複，略過", name, hk)
            continue
        claimed.add(key)
        bindings.append((name, vks))
    return bindings

def _refresh_script_hotkeys(self) -> None:
    poller = self._script_hotkey_poller
    if poller is None:
        return
    poller.stop()
    bindings = self._build_script_bindings()
    if bindings:
        poller.start(bindings)
```

- **含緊急停止鍵**（不只等於，含在組合裡也算）→ 略過：因為只要 stop 鍵被按下，緊急停止輪詢就會觸發，該熱鍵無法只啟動不停止。

### 8.4 清單/設定變動時重建
- `refresh_scripts()` 尾端加 `self._refresh_script_hotkeys()`（新增/編輯/刪除/複製後都會呼叫 `refresh_scripts`，故一處即涵蓋全部）。`__init__` 中 `refresh_scripts()` 早於 `_setup_script_hotkeys()`，此時 poller 為 None → `_refresh_script_hotkeys` 守門直接 return，稍後 setup 再建初始綁定。
- `_apply_settings()`（設定存檔）尾端加 `self._refresh_script_hotkeys()`——stop_key 若改變，原本撞停止鍵而被略過的熱鍵可能重新可用（反之亦然）。
- `closeEvent()` 加：`if self._script_hotkey_poller is not None: self._script_hotkey_poller.stop()`。

## 9. 單元六：多鍵組合錄製（`app/key_capture.py`）

### 9.1 問題
`_KeyCaptureEdit(combo=True)` 現在按下第一個「非修飾鍵」就 `_stop()` 收工，只記得下 N 個修飾鍵＋1 個主鍵（`parts = _modifier_names(mods) + [name]`）。按 `shift+a+方向鍵` 時一到 `a`（非修飾鍵）就定案成 `shift+a`，方向鍵吃不到。

### 9.2 改法：累積按下、放開才定案
combo 模式追蹤「錄製期間按下過的鍵」（依按下順序、去重存於 `self._pressed`），等開始放開任一鍵才定案：

- `_start()`：`self._pressed = []`，開始監聽（其餘同現況）。
- `keyPressEvent`（監聽中；`event.isAutoRepeat()` 直接忽略）：
  - Esc → `_stop()` 取消（保留原值），同現況。
  - 先把 `event.modifiers()` 的修飾鍵名（`_modifier_names`）併入 `_pressed`（去重）——即使修飾鍵自身的 keyPress 未被送到（合成事件／搶鍵時序），主鍵事件上的 modifiers 位元仍補得回來。
  - `name = _qt_key_to_name(event)`；非 None 且不在 `_pressed` → append。
  - combo 模式**不**在此定案（單鍵模式維持：直接寫 `self._value = name` 後 `_stop()`）。
- `keyReleaseEvent`（新增；監聽中、忽略 auto-repeat）：
  - 若 `_pressed` 至少含一個非修飾鍵 → `_commit()` ＋ `_stop()`。
  - 否則（只按了修飾鍵就放開）→ 從 `_pressed` 移除該鍵、繼續監聽（處理誤按）。
  - 非監聽中 → `super().keyReleaseEvent(event)`。
- `_commit()`：輸出順序＝修飾鍵（固定序 `ctrl/alt/shift/win` 取 `_pressed` 中出現者）＋非修飾鍵（依 `_pressed` 按下順序），以 `+` 相接寫入 `self._value`。

### 9.3 為何兩條來源都併
真實 Qt 下每個修飾鍵有自己的 keyPress（`_QT_MODS` 映射），逐一 append 即可；但既有測試以「單一 keyPress 帶 modifiers 位元」模擬組合，故也從 `event.modifiers()` 補入——兩條來源都涵蓋，穩健。

### 9.4 相容
- 產出仍是 canonical 名稱（如 `shift+a+right`），與 `key_combo` 驗證、`hotkey_to_vks`、`vk_for_key` 一致（每部分 `is_valid_key`、可解 vk）。
- 共用此元件的兩處自動受益：腳本動作「組合鍵（keys）」欄與啟動快捷鍵欄。
- 既有 `key_combo` 執行（press 全部→hold 40ms→反序 release）對多鍵一樣適用。

## 10. 單元七：緊急停止不再停監看（`app/main_window.py`＋`app/watch_controller.py`）

### 10.1 需求
按下緊急停止（停止鍵／背景輪詢／滑鼠甩左上角）只中止「腳本回放」，**不**停止監看。監看只由「停止監看」按鈕停止；規則自訂 `stop_all`（停執行中的腳本）與未來另設的監看專屬快捷鍵不受影響。使用者已選「監看完全獨立」。

### 10.2 `main_window._on_emergency_hotkey`
移除 `self._watch_controller.stop()`，只留 `self._run_controller.stop()`；日誌改為「偵測到緊急停止 → 中止回放」。此函式同時是 `_global_hotkey`（RegisterHotKey）與 `_key_poller`（GetAsyncKeyState 背景輪詢）的回呼，故背景/遊戲中亦不再停監看。

### 10.3 `WatchController`：移除緊急停止 guard
監看的 `SessionGuard`（`_start_guard`）是「按停止鍵／甩角落 → set 監看 `stop_event`」唯一來源，須拆除：
- `build_job`：移除 `guard = self._start_guard(stop_event)` 與 `finally` 的 `guard.stop()`；直接 `engine.run(rules)`。
- 移除 `_start_guard` 方法。
- 建構子移除只服務 guard 的參數：`hook_factory`、`guard_factory`、`stop_key`、`corner_failsafe`。
- `apply_settings` 移除 `stop_key`、`corner_failsafe`（保留 `get_platform`、`discord_webhook_url`）。
- 保留 `on_stop_all`（規則 `stop_all` → 停執行中腳本，與緊急停止無關）與 `stop()`（停止監看按鈕用）。

### 10.4 `main_window` 接線調整
- 建構 `WatchController(...)`（第 77–85 行）移除 `stop_key`、`corner_failsafe` 引數（保留 `discord_webhook_url`、`on_stop_all`）。
- `_apply_settings`（第 ~683 行）呼叫 `watch_controller.apply_settings(...)` 移除 `stop_key`、`corner_failsafe`。
- `corner_failsafe`／`stop_key` 設定本身保留——回放端 `RunController` 仍使用。

### 10.5 測試調整
- `test_watch_controller.py`：刪除只驗 guard 行為的測試（`test_guard_best_effort_with_configured_stop_key`、guard 爆炸容錯、`test_watch_controller_passes_corner_failsafe_to_guard`）；`test_apply_settings_takes_effect_on_next_build_job` 移除 guard／stop_key 斷言、保留 get_platform／discord；`make_controller` 與 `SpyGuard` 移除 guard 接線。
- `test_main_window.py`：`test_apply_settings...` 移除 `watch_c.applied["stop_key"]` 斷言（保留 discord）；`test_emergency_signal_stops_both_controllers` 改為「緊急停止只停 run、不停 watch」（`run.stopped == 1 and watch.stopped == 0`）並更名。

## 11. 資料流

```
編輯器 _KeyCaptureEdit(combo=True) →（Esc 取消）→ _on_save
  → model.set_hotkey("ctrl+shift+1") → settings.hotkey → storage.save

開機／腳本清單變動／設定變動
  → refresh_scripts / _apply_settings → _refresh_script_hotkeys
  → _build_script_bindings（逐一 load 腳本、hotkey_to_vks、含停止鍵/重複則略過）
  → poller.stop() + poller.start(bindings)

背景執行緒（ScriptHotkeyPoller._run）
  → 每 ~30ms 對每綁定檢查「整組 vk 皆按下」上升緣
  → on_trigger(name) = script_hotkey_requested.emit(name)
  → GUI 執行緒 _run_script(name)
  → 若有 worker 在跑：run_controller.stop() + _cleanup_worker()（先停）
  → build_job + worker.start()（再跑新的）
```

## 12. 錯誤處理

- 綁定建置逐腳本 `try/except ScriptValidationError`：單一壞腳本不影響其他熱鍵。
- 無法對應 vk、含停止鍵、重複 → 記一行警告並略過該綁定（不擋其餘）。
- 輪詢讀取例外、`on_trigger` 例外 → 記錄後續跑（不讓背景執行緒死掉）。
- 非 Windows／離屏／setup 失敗 → poller 為 None，所有相關方法守門 no-op（同緊急停止 poller 慣例）。
- 多鍵錄製：`keyReleaseEvent` 於非監聽狀態轉呼叫 `super()`；auto-repeat 事件忽略，不誤加/誤定案。

## 13. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `models`（ScriptSettings） | `ScriptSettings().hotkey == ""`；`_validate_settings` 接受空字串、單鍵、組合鍵；拒非字串、拒含不合法按鍵名；`_check_no_extra` 允許 `hotkey`；`script_to_dict`／`script_from_dict` round-trip 保值；舊檔缺 `hotkey` → `""` |
| `global_hotkey` | `vk_for_key` 對 `ctrl/control`→0x11、`shift`→0x10、`alt`→0x12、`win/super/cmd`→0x5B；`hotkey_to_vks("ctrl+shift+1")==[0x11,0x10,0x31]`、`("f5")==[0x74]`；含未知鍵 → None；空字串 → None |
| `ScriptHotkeyPoller` | 注入 `key_down_fn`＋`sleep`：單綁定整組按下觸發一次、按住不重複、放開再按再觸發；多綁定互不干擾；`start([])` 回 False 不啟執行緒；`stop()` 於輪詢執行緒內呼叫不自我 join（不 RuntimeError） |
| `script_editor_model` | `hotkey` 預設 `""`；`set_hotkey("ctrl+a")` → property 與 `to_script().settings.hotkey` 皆為 `ctrl+a`；載入既有腳本還原其值 |
| `script_editor`（widget，offscreen） | `hotkey_edit` 存在、初值反映 `model.hotkey`；設值後 `_on_save` → 存下的腳本 `settings.hotkey` 正確 |
| `main_window`（offscreen＋fake worker/storage） | `_build_script_bindings` 去重（先出現者贏）、略過含停止鍵者、略過無法對應者；`script_hotkey_requested.emit(name)` → `_run_script(name)` 被呼叫；`_run_script` 在有 worker 執行中時先 `run_controller.stop()` 再啟新 worker |
| `key_capture`（widget，單元六） | combo：連續 press `shift`→`a`→`right` 累積、release 定案 `shift+a+right`；單一 keyPress 帶 ctrl+shift 位元＋release → `ctrl+shift+s`（既有測試補 release 事件）；auto-repeat 忽略；Esc 取消保留原值；單鍵模式仍即時定案 |
| `watch_controller`（單元七） | 移除 `guard_factory`／`hook_factory`／`stop_key`／`corner_failsafe` 參數後 build_job 仍執行引擎（既有 `test_build_job_runs_engine…` 續過）；刪除 guard 相關測試（§10.5）；`stop()`（按鈕）仍設 `stop_event`；`on_stop_all` 仍透傳 |
| `main_window`（緊急停止，單元七） | `_on_emergency_hotkey`／`emergency_stop_requested.emit()` 只呼叫 `run_controller.stop()`、不呼叫 `watch_controller.stop()`（`run.stopped==1 and watch.stopped==0`） |

既有 `_cleanup_worker` / `_on_run_clicked` 相關測試若有斷言，隨介面調整更新（行為等價：正常單次執行仍照舊）。單元七的監看 guard 測試依 §10.5 刪除/改寫。

## 14. 非目標（YAGNI）

- 腳本熱鍵改用 `RegisterHotKey`（本功能一律用背景輪詢，涵蓋遊戲/背景）。
- 每腳本可調輪詢間隔（固定 30ms，與緊急停止一致）。
- 編輯器內即時衝突提示（衝突於綁定階段記錄＋略過即可）。
- 解決「遊戲也用同一單鍵時雙重觸發」（已列為但書，非本功能可解）。
- 規則（Rule）的啟動熱鍵（本次只做腳本）。
- 全域「停用所有腳本熱鍵」總開關。
- 監看專屬停止快捷鍵（使用者提到的「另外設定快捷鍵」屬未來，本次只做「停止監看」按鈕）。
- 組合鍵錄製上限鍵數／可設定的定案手勢（放開即定案，固定行為）。
