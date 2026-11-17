# 腳本列表顯示啟動快捷鍵實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 腳本列表在有設啟動快捷鍵的腳本名稱後顯示「   [首字大寫熱鍵]」；顯示文字與真名以 `Qt.UserRole` 解耦，選取改用 `currentItemChanged`。

**Architecture:** 新增純函式 `script_list_label(storage, name)` 產生列表文字（含熱鍵後綴、load 失敗容錯）；`refresh_scripts` 用它建 `QListWidgetItem` 並把真名存 `UserRole`；選取信號由 `currentTextChanged` 改 `currentItemChanged` + adapter 讀 UserRole 後沿用既有 `_on_script_selected(name)`。

**Tech Stack:** Python 3.13、PySide6（`QT_QPA_PLATFORM=offscreen` for GUI tests）。

## Global Constraints

- 格式：有熱鍵 → `f"{name}   [{pretty}]"`，`pretty = "+".join(part.capitalize() for part in hotkey.split("+"))`（`ctrl+shift+1`→`Ctrl+Shift+1`、`f8`→`F8`）；無熱鍵 → 只回 `name`。名稱與 `[` 之間為**三個空格**。
- 顯示文字與真名解耦：`QListWidgetItem` 顯示 `script_list_label(...)`，`item.setData(Qt.ItemDataRole.UserRole, name)` 存真名；選取讀 UserRole，不讀文字。
- load 失敗（腳本損毀）→ 只顯示名稱，不擋其他項目。
- 每步 TDD、小步提交。測試指令：`QT_QPA_PLATFORM=offscreen python.exe -m pytest <files> -q`。

---

## 檔案結構

- `src/keyboard_executor/app/script_list.py` — 新增 `script_list_label`（Task 1）
- `src/keyboard_executor/app/main_window.py` — import `QListWidgetItem`、`refresh_scripts` 建 item、`currentItemChanged` + adapter（Task 2）

---

## Task 1: `script_list_label` 純函式

**Files:**
- Modify: `src/keyboard_executor/app/script_list.py`（於 `summary_for_script` 之後新增）
- Test: `tests/app/test_script_list.py`

**Interfaces:**
- Produces: `script_list_label(storage, name: str) -> str` — 有熱鍵回 `f"{name}   [{pretty}]"`，無熱鍵或 load 失敗回 `name`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_list.py`；檔頭 import 加 `script_list_label`、`ScriptStorage` 已 import）

```python
def test_script_list_label_with_and_without_hotkey(tmp_path):
    from keyboard_executor.app.script_list import script_list_label
    storage = ScriptStorage(tmp_path)

    def save(name, hotkey):
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "x"},
            "settings": {"hotkey": hotkey},
            "actions": [{"type": "key_press", "key": "a"}]}))

    save("甲", "")
    save("乙", "ctrl+shift+1")
    save("丙", "f8")
    assert script_list_label(storage, "甲") == "甲"
    assert script_list_label(storage, "乙") == "乙   [Ctrl+Shift+1]"
    assert script_list_label(storage, "丙") == "丙   [F8]"
    (tmp_path / "壞.json").write_text("{不是json", encoding="utf-8")
    assert script_list_label(storage, "壞") == "壞"     # 載入失敗 → 純名稱
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_list.py -q`
Expected: FAIL（無 `script_list_label`）。

- [ ] **Step 3: 實作 `script_list.py`**（於 `summary_for_script` 之後）

```python
def script_list_label(storage, name: str) -> str:
    """腳本列表項目文字：有設啟動快捷鍵時加「   [Ctrl+Shift+1]」後綴（每段首字大寫）。
    載入失敗（腳本損毀）→ 只顯示名稱。"""
    try:
        hotkey = storage.load(name).settings.hotkey
    except ScriptValidationError:
        hotkey = ""
    if not hotkey:
        return name
    pretty = "+".join(part.capitalize() for part in hotkey.split("+"))
    return f"{name}   [{pretty}]"
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_list.py -q`
Expected: PASS（既有 script_list 測試續過）。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/script_list.py tests/app/test_script_list.py
git commit -m "feat(script-list): script_list_label 產生含熱鍵後綴的列表文字"
```

---

## Task 2: 主視窗列表接線（顯示＋UserRole 解耦＋選取信號）

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`（import 約 14–20；`refresh_scripts` 約 472–475；`_wire` 約 453；`_on_script_selected` 附近新增 adapter）
- Test: `tests/app/test_main_window.py`

**Interfaces:**
- Consumes: `script_list_label`（Task 1）、`ScriptSettings.hotkey`。
- Produces: 列表項目文字含 `[熱鍵]`、`UserRole`＝真名；`_on_script_current_changed(current, previous)` adapter。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_main_window.py`）

```python
def test_script_list_shows_hotkey_suffix_and_selects_by_userrole(qapp, tmp_path):
    from PySide6.QtCore import Qt
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "settings": {"hotkey": "ctrl+shift+1"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=FakeRunController(), worker_factory=ImmediateWorker)
    item = window.script_list.item(0)
    assert item.text() == "甲   [Ctrl+Shift+1]"
    assert item.data(Qt.ItemDataRole.UserRole) == "甲"
    window.script_list.setCurrentRow(0)                 # 觸發 currentItemChanged
    assert window._scripts.selected == "甲"             # 用 UserRole 真名 select
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_main_window.py -q -k "hotkey_suffix or lists_scripts"`
Expected: 新測試 FAIL（item 文字無 `[熱鍵]`、無 UserRole）。

- [ ] **Step 3: import 加入 `QListWidgetItem`**

`main_window.py` 的 `from PySide6.QtWidgets import (...)` 清單加入 `QListWidgetItem`（與 `QListWidget` 同處）。`Qt`（第 13 行）與 `script_list_label`（由 `keyboard_executor.app.script_list` 匯入，與既有 `summary_for_script` 同一 import）確認可用；`from keyboard_executor.app.script_list import ScriptListController, summary_for_script` 改為 `..., summary_for_script, script_list_label`。

- [ ] **Step 4: `refresh_scripts` 建 item + UserRole**

```python
    def refresh_scripts(self) -> None:
        self.script_list.clear()
        for name in self._scripts.refresh():
            item = QListWidgetItem(script_list_label(self._script_storage, name))
            item.setData(Qt.ItemDataRole.UserRole, name)   # 真名與顯示文字解耦
            self.script_list.addItem(item)
        self._refresh_script_hotkeys()
```

- [ ] **Step 5: 選取信號改 `currentItemChanged` + adapter**

`_wire` 裡把
```python
        self.script_list.currentTextChanged.connect(self._on_script_selected)
```
改為
```python
        self.script_list.currentItemChanged.connect(self._on_script_current_changed)
```

在 `_on_script_selected` 之前（或附近）新增 adapter：
```python
    def _on_script_current_changed(self, current, previous) -> None:
        name = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._on_script_selected(name)
```
（`_on_script_selected(name)` 不變，已 `if not name: return`。）

- [ ] **Step 6: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_main_window.py -q`
Expected: PASS（含既有 `test_window_lists_scripts_from_storage`——無熱鍵腳本文字＝名稱；`setCurrentRow`-based 選取/刪除/複製測試因 UserRole 已設而續過）。

- [ ] **Step 7: 提交**

```bash
git add src/keyboard_executor/app/main_window.py tests/app/test_main_window.py
git commit -m "feat(main-window): 腳本列表顯示熱鍵後綴，選取改用 UserRole"
```

---

## 收尾：全套件驗證

- [ ] **執行完整測試套件**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest -q`
Expected: 全綠（724 passed / 4 skipped 之上加本計畫新增測試）。
