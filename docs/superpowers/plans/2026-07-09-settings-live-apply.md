# 設定存檔免重開 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 設定頁存檔後免重開程式即生效——日誌等級與系統級緊急停止熱鍵立即套用；控制器 stop_key、Discord webhook、OCR 語言於下一次執行/監看生效；進行中的那一次維持原設定。

**Architecture:** SettingsPage 存檔成功發 `saved(Settings)` 訊號 → main_window `_apply_settings` 更新設定快照、重建平台工廠 partial、就地更新兩控制器欄位（不重建實例，故進行中的 stop 仍有效）、重新註冊系統熱鍵、刷新畫面標籤。

**Tech Stack:** Python 3.13 / PySide6（QDialog Signal）/ pytest。

## Global Constraints

- 所有面向使用者訊息用**繁體中文**。
- **進行中不動**：`apply_settings` 只改「下一次 build_job 才讀的欄位」，不得動到進行中的 `_stop_event`／不得重建控制器實例。
- **生效時機**：日誌等級＝立即；系統級緊急停止熱鍵＝立即重註冊；控制器 stop_key／webhook／OCR＝下一次執行/監看。
- 熱鍵重註冊失敗只記 log、不中斷（沿用既有風格）。`self._global_hotkey` 可能為 `None`（非 win32／離屏／原註冊失敗）→ 先判 None。
- 檔案行尾 LF。
- 全程 TDD。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/app/settings_page.py` | 存檔成功發 `saved` 訊號、更新狀態訊息 | Modify |
| `src/keyboard_executor/app/run_controller.py` | `apply_settings` 就地更新 stop_key/get_platform | Modify |
| `src/keyboard_executor/app/watch_controller.py` | `apply_settings` 就地更新 stop_key/get_platform/webhook | Modify |
| `src/keyboard_executor/app/main_window.py` | 接 `saved`、`_apply_settings`、熱鍵重註冊、標籤刷新 | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

---

### Task 1: SettingsPage `saved` 訊號與狀態訊息

**Files:**
- Modify: `src/keyboard_executor/app/settings_page.py`
- Test: `tests/app/test_settings_page_widget.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: 既有 `SettingsStore.save/load`
- Produces: `SettingsPage.saved`（`PySide6.QtCore.Signal(object)`）——存檔成功後 emit 已持久化並正規化的 `Settings`（即 `self._store.load()` 的結果）；驗證失敗時不 emit。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_settings_page_widget.py` 末端新增：
```python
def test_settings_page_emits_saved_with_persisted_settings(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store)
    seen = []
    page.saved.connect(seen.append)
    page.stop_edit.setText("f8")
    page.save_button.click()
    assert len(seen) == 1
    assert isinstance(seen[0], Settings) and seen[0].stop_key == "f8"


def test_settings_page_does_not_emit_saved_on_validation_failure(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    seen = []
    page.saved.connect(seen.append)
    page.stop_edit.setText("")               # 空熱鍵 → 驗證失敗
    page.save_button.click()
    assert seen == []
    assert "儲存失敗" in page.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -k "emits_saved or does_not_emit" -v`
Expected: FAIL（`AttributeError: 'SettingsPage' object has no attribute 'saved'`）

- [ ] **Step 3: 最小實作**

3a. `settings_page.py` 匯入區加（在 `from __future__` 後、其他 import 之間）：
```python
from PySide6.QtCore import Signal
```

3b. `class SettingsPage(QDialog):` 底下、`__init__` 之前加類別屬性：
```python
class SettingsPage(QDialog):
    saved = Signal(object)   # 存檔成功後發出已持久化並正規化的 Settings
```

3c. `_on_save` 改為存檔成功後 emit（沿用既有欄位；成功訊息改為即時套用語意）：
```python
    def _on_save(self) -> None:
        try:
            self._store.save(Settings(
                toggle_key=self.toggle_edit.text().strip(),
                stop_key=self.stop_edit.text().strip(),
                ocr_language=self.ocr_edit.text().strip(),
                log_level=self.level_combo.currentText(),
                discord_webhook_url=self.discord_edit.text().strip()))
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")
            return
        self.status_label.setText("已儲存，已即時套用（執行中的維持原設定）")
        self.saved.emit(self._store.load())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -v`
Expected: PASS（新增 2 項與既有全數；既有測試斷言 `"已儲存" in status` 仍成立）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings_page.py tests/app/test_settings_page_widget.py
git commit -m "feat(settings): 設定頁存檔成功發 saved 訊號、狀態改即時套用"
```

---

### Task 2: `RunController.apply_settings`

**Files:**
- Modify: `src/keyboard_executor/app/run_controller.py`
- Test: `tests/app/test_run_controller.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: 既有 `RunController`
- Produces: `RunController.apply_settings(self, *, stop_key: str, get_platform) -> None`——就地更新 `self._stop_key`、`self._get_platform`；下一次 `build_job` 生效，不動進行中的回放。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_run_controller.py` 末端新增（沿用檔內既有 `make_controller`、`SpyGuard`、`SpyPlayer`）：
```python
def test_apply_settings_takes_effect_on_next_build_job(tmp_path):
    controller, _storage, _loader, _captured = make_controller(tmp_path, stop_key="f10")
    marker = object()
    plat_calls = []
    controller.apply_settings(
        stop_key="f8",
        get_platform=lambda **k: (plat_calls.append(True), marker)[1])
    controller.build_job("甲")(lambda r: None)
    assert SpyGuard.instances[-1].stop_key == "f8"     # 新 stop_key 生效
    assert SpyPlayer.last.platform is marker           # 用了新的 get_platform
    assert plat_calls                                  # 新 get_platform 被呼叫
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_run_controller.py -k apply_settings -v`
Expected: FAIL（`AttributeError: 'RunController' object has no attribute 'apply_settings'`）

- [ ] **Step 3: 最小實作**

在 `run_controller.py` 的 `RunController` 內、`stop` 方法附近新增：
```python
    def apply_settings(self, *, stop_key: str, get_platform) -> None:
        """就地更新下一次 build_job 會用到的設定；不影響進行中的回放
        （進行中的 job 已捕獲自己的 stop_event 與 platform）。"""
        self._stop_key = stop_key
        self._get_platform = get_platform
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_run_controller.py -v`
Expected: PASS（新增 1 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/run_controller.py tests/app/test_run_controller.py
git commit -m "feat(settings): RunController.apply_settings 就地更新下一次執行的設定"
```

---

### Task 3: `WatchController.apply_settings`

**Files:**
- Modify: `src/keyboard_executor/app/watch_controller.py`
- Test: `tests/app/test_watch_controller.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: 既有 `WatchController`
- Produces: `WatchController.apply_settings(self, *, stop_key: str, get_platform, discord_webhook_url: str) -> None`——就地更新 `self._stop_key`、`self._get_platform`、`self._discord_webhook_url`；下一次 `build_job` 生效。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_watch_controller.py` 末端新增（沿用檔內既有 `SpyEngine`、`SpyGuard`、`make_rule_storage`、`FakeInputHook`）：
```python
def test_apply_settings_takes_effect_on_next_build_job(tmp_path):
    captured = {}

    def fake_notifier_factory(base, webhook):
        captured["webhook"] = webhook
        return base

    plat_calls = []
    controller = WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=lambda *a, **k: object(),
        hook_factory=FakeInputHook, guard_factory=SpyGuard,
        stop_key="f10", discord_webhook_url="https://discord.com/api/webhooks/1/old",
        notifier_factory=fake_notifier_factory)
    controller.apply_settings(
        stop_key="f8",
        get_platform=lambda **k: (plat_calls.append(True), object())[1],
        discord_webhook_url="https://discord.com/api/webhooks/1/new")
    controller.build_job()(lambda r: None)
    assert SpyGuard.instances[-1].stop_key == "f8"                       # 新 stop_key
    assert captured["webhook"] == "https://discord.com/api/webhooks/1/new"  # 新 webhook
    assert plat_calls                                                    # 新 get_platform 被呼叫
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_watch_controller.py -k apply_settings -v`
Expected: FAIL（`AttributeError: 'WatchController' object has no attribute 'apply_settings'`）

- [ ] **Step 3: 最小實作**

在 `watch_controller.py` 的 `WatchController` 內、`stop` 方法附近新增：
```python
    def apply_settings(self, *, stop_key: str, get_platform,
                       discord_webhook_url: str) -> None:
        """就地更新下一次 build_job 會用到的設定；不影響進行中的監看。"""
        self._stop_key = stop_key
        self._get_platform = get_platform
        self._discord_webhook_url = discord_webhook_url
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_watch_controller.py -v`
Expected: PASS（新增 1 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/watch_controller.py tests/app/test_watch_controller.py
git commit -m "feat(settings): WatchController.apply_settings 就地更新下一次監看的設定"
```

---

### Task 4: main_window 接線 `_apply_settings`（熱鍵重註冊＋標籤刷新）

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`
- Test: `tests/app/test_main_window.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: `SettingsPage.saved`（Task 1）、`RunController.apply_settings`（Task 2）、`WatchController.apply_settings`（Task 3）、既有 `self._global_hotkey`（可能 None）、`self.record_button`
- Produces: `MainWindow._apply_settings(new)`；`self._estop_label`（原為區域變數）；`_reregister_hotkey`、`_refresh_hotkey_labels`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_main_window.py` 末端新增（沿用檔內既有 `ImmediateWorker`）：
```python
def test_apply_settings_updates_snapshot_controllers_hotkey_and_labels(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings

    class RecCtrl:
        def __init__(self):
            self.applied = None
        def apply_settings(self, **kw):
            self.applied = kw
        def stop(self):
            pass

    class FakeHotkey:
        def __init__(self):
            self.calls = []
        def unregister(self):
            self.calls.append("unreg")
        def register(self, key):
            self.calls.append(("reg", key))
            return True

    run_c, watch_c = RecCtrl(), RecCtrl()
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        run_controller=run_c, watch_controller=watch_c,
                        worker_factory=ImmediateWorker)
    window._global_hotkey = FakeHotkey()
    new = Settings(toggle_key="f7", stop_key="f8", ocr_language="en",
                   log_level="DEBUG",
                   discord_webhook_url="https://discord.com/api/webhooks/1/x")
    window._apply_settings(new)

    assert window._settings is new                              # 快照更新（日誌等級即時）
    assert run_c.applied["stop_key"] == "f8"
    assert watch_c.applied["stop_key"] == "f8"
    assert watch_c.applied["discord_webhook_url"] == "https://discord.com/api/webhooks/1/x"
    assert window._global_hotkey.calls == ["unreg", ("reg", "f8")]  # 熱鍵重註冊
    assert "F8" in window._estop_label.text()                  # 標籤刷新
    assert "F7" in window.record_button.toolTip()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -k apply_settings -v`
Expected: FAIL（`AttributeError: 'MainWindow' object has no attribute '_apply_settings'`）

- [ ] **Step 3: 最小實作**

3a. 把緊急停止標籤存成實例屬性。找到（約 `main_window.py:208`）：
```python
        estop = QLabel(f"● 緊急停止 {self._settings.stop_key.upper()}")
        estop.setObjectName("estop")
        lay.addWidget(estop)
```
改為：
```python
        self._estop_label = QLabel(f"● 緊急停止 {self._settings.stop_key.upper()}")
        self._estop_label.setObjectName("estop")
        lay.addWidget(self._estop_label)
```

3b. `_on_open_settings`（約 `main_window.py:594-599`）改為連接 `saved`：
```python
    def _on_open_settings(self) -> None:
        from keyboard_executor.app.settings_page import SettingsPage

        page = SettingsPage(SettingsStore(self._data_dir),
                            permission_checks=self._permission_checks, parent=self)
        page.saved.connect(self._apply_settings)
        page.exec()
```

3c. 新增 `_apply_settings` 與兩個輔助方法（放在 `_on_open_settings` 附近）：
```python
    def _apply_settings(self, new) -> None:
        """設定存檔後免重開即套用：日誌等級與系統熱鍵立即；控制器 stop_key／
        webhook／OCR 於下一次執行/監看生效（進行中的維持原設定）。"""
        self._settings = new
        self._get_platform = partial(
            get_platform,
            ocr_lang=ocr_lang_from_setting(new.ocr_language))
        self._run_controller.apply_settings(
            stop_key=new.stop_key, get_platform=self._get_platform)
        self._watch_controller.apply_settings(
            stop_key=new.stop_key, get_platform=self._get_platform,
            discord_webhook_url=new.discord_webhook_url)
        self._reregister_hotkey(new.stop_key)
        self._refresh_hotkey_labels()

    def _reregister_hotkey(self, stop_key: str) -> None:
        if self._global_hotkey is None:
            return          # 非 win32／離屏／原註冊失敗，無事可做
        self._global_hotkey.unregister()
        if self._global_hotkey.register(stop_key):
            logger.info("系統級緊急停止熱鍵已更新：%s", stop_key.upper())
        else:
            logger.warning("系統級緊急停止熱鍵重新註冊失敗：%s；仍可用滑鼠角落停止",
                           stop_key.upper())

    def _refresh_hotkey_labels(self) -> None:
        self._estop_label.setText(f"● 緊急停止 {self._settings.stop_key.upper()}")
        self.record_button.setToolTip(
            f"開啟錄製面板錄製新腳本（{self._settings.toggle_key.upper()} 開始/停止）")
```

（`partial`、`get_platform`、`ocr_lang_from_setting` 於 `main_window.py` 開頭已 import；沿用。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -v`
Expected: PASS（新增 1 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/main_window.py tests/app/test_main_window.py
git commit -m "feat(settings): 設定存檔即套用（重讀快照、更新控制器、重註冊熱鍵、刷新標籤）"
```

---

### Task 5: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 + 新增約 5 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~4); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。如有 CRLF 用 `sed -i 's/\r$//' <file>` 正規化後 `git add` 修補。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重新打包 exe，於實機驗收：改日誌等級存檔→立即生效；改緊急停止熱鍵存檔→不重開即用新鍵；改 Discord webhook 存檔→下一次監看即用新網址（不必重啟）；改 OCR 語言存檔→下一次執行/監看生效；且在**執行/監看進行中**改設定，進行中的那一次維持原設定、停止鈕仍有效。此步驟在計畫外，由使用者驅動。
