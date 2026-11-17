# 儲存成功自動關閉視窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 四個編輯視窗（規則編輯器、腳本編輯器、設定頁、錄製面板）主「儲存」成功後自動 `self.accept()` 關閉；驗證失敗維持開著並顯示錯誤。

**Architecture:** 每個視窗的 `_on_save*` 方法在成功路徑最後加一行 `self.accept()`（四者皆為以 `.exec()` 開啟的 `QDialog`）。失敗路徑（`ScriptValidationError` 或無可存內容）照舊 `setText(...)` + `return`，不呼叫 `accept()`。

**Tech Stack:** PySide6（`QDialog.accept()` / `QDialog.result()`）/ pytest。

## Global Constraints

- **只在儲存成功時關閉**；驗證失敗維持開著。
- 只動主「儲存」；子動作（框選區域、擷取模板、滴管取色）不改。
- 面向使用者訊息維持繁中現況。LF 行尾。全程 TDD。
- 判定關閉用 `dialog.result() == QDialog.DialogCode.Accepted`（`accept()` 後為 Accepted；未關時 result() 為預設 0）。測試中對話框未 `.exec()`，`accept()` 只設 result 並隱藏，`status_label`／storage 仍可讀。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 方法 | 動作 |
|------|------|------|
| `src/keyboard_executor/app/rule_editor.py` | `_on_save` | 成功末端加 `self.accept()` |
| `src/keyboard_executor/app/script_editor.py` | `_on_save` | 成功末端加 `self.accept()` |
| `src/keyboard_executor/app/settings_page.py` | `_on_save` | 成功末端加 `self.accept()` |
| `src/keyboard_executor/app/recorder_panel.py` | `_on_save_clicked` | 成功末端加 `self.accept()` |

---

### Task 1: 規則編輯器儲存成功關閉

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor.py`（`_on_save` 尾端）
- Test: `tests/app/test_rule_editor_widget.py`（既有檔，新增測試）

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_rule_editor_widget.py` 末端新增：
```python
def test_rule_editor_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("r")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.trigger_combo.setCurrentIndex(dialog.trigger_combo.findData("notify"))
    dialog.message_edit.setText("y")
    dialog.save_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted        # 成功 → 關閉
    assert storage.load("r").condition.pattern == "連線中斷"      # 確實有存


def test_rule_editor_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    dialog.name_edit.setText("")                                 # 空名稱 → 驗證失敗
    dialog.save_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted        # 失敗 → 不關
    assert "儲存失敗" in dialog.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_widget.py -k "closes_on_successful or stays_open_on_validation" -v`
Expected: `test_rule_editor_closes_on_successful_save` FAIL（result() 仍為 0，未 Accepted）；失敗案例可能已通過（本就不關）

- [ ] **Step 3: 最小實作**

`rule_editor.py` `_on_save` 尾端（`self.status_label.setText(f"已儲存：{path}")` 之後）加：
```python
        self.status_label.setText(f"已儲存：{path}")
        self.accept()                       # 儲存成功 → 自動關閉
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_widget.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor.py tests/app/test_rule_editor_widget.py
git commit -m "feat(rule-editor): 儲存成功自動關閉視窗"
```

---

### Task 2: 腳本編輯器儲存成功關閉

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（`_on_save` 尾端）
- Test: `tests/app/test_script_editor_widget.py`（既有檔，新增測試；沿用既有 `make_dialog`）

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_script_editor_widget.py` 末端新增：
```python
def test_script_editor_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog, _ = make_dialog(tmp_path)          # 甲：有目標視窗＋動作 → 有效
    dialog._on_save()
    assert dialog.result() == QDialog.DialogCode.Accepted        # 成功 → 關閉


def test_script_editor_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog, _ = make_dialog(tmp_path)
    dialog.name_edit.setText("")                                 # 空名稱 → 驗證失敗
    dialog._on_save()
    assert dialog.result() != QDialog.DialogCode.Accepted        # 失敗 → 不關
    assert "儲存失敗" in dialog.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_widget.py -k "closes_on_successful or stays_open_on_validation" -v`
Expected: `test_script_editor_closes_on_successful_save` FAIL（未 Accepted）

- [ ] **Step 3: 最小實作**

`script_editor.py` `_on_save` 尾端（`self.status_label.setText(f"已儲存：{path}")` 之後）加：
```python
        self.status_label.setText(f"已儲存：{path}")
        self.accept()                       # 儲存成功 → 自動關閉
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_widget.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(script-editor): 儲存成功自動關閉視窗"
```

---

### Task 3: 設定頁儲存成功關閉

**Files:**
- Modify: `src/keyboard_executor/app/settings_page.py`（`_on_save` 尾端）
- Test: `tests/app/test_settings_page_widget.py`（既有檔，新增測試）

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_settings_page_widget.py` 末端新增：
```python
def test_settings_page_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))     # 預設 f9/f10/auto/INFO 有效
    page.save_button.click()
    assert page.result() == QDialog.DialogCode.Accepted          # 成功 → 關閉


def test_settings_page_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    page.stop_edit.setText("")                        # 空熱鍵 → 驗證失敗
    page.save_button.click()
    assert page.result() != QDialog.DialogCode.Accepted          # 失敗 → 不關
    assert "儲存失敗" in page.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -k "closes_on_successful or stays_open_on_validation" -v`
Expected: `test_settings_page_closes_on_successful_save` FAIL（未 Accepted）

- [ ] **Step 3: 最小實作**

`settings_page.py` `_on_save` 尾端（`self.saved.emit(self._store.load())` 之後）加：
```python
        self.saved.emit(self._store.load())
        self.accept()                       # 儲存成功 → 自動關閉（saved 訊號已先發）
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -v`
Expected: PASS（新增 2 項與既有全數，含既有 `saved` 訊號測試）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings_page.py tests/app/test_settings_page_widget.py
git commit -m "feat(settings): 設定頁儲存成功自動關閉視窗"
```

---

### Task 4: 錄製面板儲存成功關閉

**Files:**
- Modify: `src/keyboard_executor/app/recorder_panel.py`（`_on_save_clicked` 尾端）
- Test: `tests/app/test_recorder_panel_widget.py`（既有檔，新增測試；沿用既有 `SpySession`、`FakeInputHook`、`FakeWindowManager`）

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_recorder_panel_widget.py` 末端新增：
```python
def test_recorder_panel_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.core.models import action_from_dict
    win = WindowInfo(handle=object(), title="記事本", app_name="App",
                     x=1, y=2, width=3, height=4, is_active=False)
    panel = RecorderPanel(FakeWindowManager([win]), ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    panel._win = win
    panel._actions = [action_from_dict({"type": "key_press", "key": "a"})]
    panel.name_edit.setText("錄我")
    panel._on_save_clicked()
    assert panel.result() == QDialog.DialogCode.Accepted         # 成功 → 關閉


def test_recorder_panel_stays_open_when_nothing_recorded(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    win = WindowInfo(handle=object(), title="記事本", app_name="App",
                     x=1, y=2, width=3, height=4, is_active=False)
    panel = RecorderPanel(FakeWindowManager([win]), ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    panel._on_save_clicked()                          # _actions 為 None → 無可儲存
    assert panel.result() != QDialog.DialogCode.Accepted         # 不關
    assert "沒有可儲存" in panel.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_recorder_panel_widget.py -k "closes_on_successful or nothing_recorded" -v`
Expected: `test_recorder_panel_closes_on_successful_save` FAIL（未 Accepted）

- [ ] **Step 3: 最小實作**

`recorder_panel.py` `_on_save_clicked` 尾端（`self.status_label.setText(f"已儲存：{path}（共 {len(self._actions)} 個動作）")` 之後）加：
```python
        self.status_label.setText(f"已儲存：{path}（共 {len(self._actions)} 個動作）")
        self.accept()                       # 儲存成功 → 自動關閉
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_recorder_panel_widget.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/recorder_panel.py tests/app/test_recorder_panel_widget.py
git commit -m "feat(recorder): 錄製面板儲存成功自動關閉視窗"
```

---

### Task 5: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 + 新增 8 項；容許既有 4 skipped）。既有「按存後讀 status_label／storage」測試不受 `accept()` 影響（不清文字、不銷毀物件）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~4); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重新打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺掉殘留程序，避免 cv2.pyd 被鎖）。實機驗收：四個視窗按儲存成功後即關閉；故意填不合法欄位按儲存則視窗留著並顯示錯誤。此步驟在計畫外，由使用者驅動。
