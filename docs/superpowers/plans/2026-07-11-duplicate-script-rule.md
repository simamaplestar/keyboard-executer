# 複製腳本／規則 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在腳本清單與規則清單各加一個「複製」按鈕，把選取的腳本／規則整份複製一份、自動給唯一新名並存檔。

**Architecture:** 純函式 `unique_copy_name` 產生唯一名；`ScriptListController.duplicate_selected` / `RuleListController.duplicate` 以 `dataclasses.replace(obj, name=新名)` 複製並存檔（腳本一併複製編輯器版面）；`main_window` 兩顆按鈕＋handler 呼叫控制器、刷新、選取新複本。

**Tech Stack:** Python 3.13 / PySide6 / pytest。

## Global Constraints

- 命名：新名＝`f"{原名} - 複製"`，衝突則 `f"{原名} - 複製 {n}"`（n 從 2 遞增）。
- 複製為**非破壞性**：不需確認對話框。未選取 → 面向使用者提示（繁中）、不動作。
- 腳本複製時，若原腳本有版面（`load_layout` 非 None）→ 一併 `save_layout(新名, 版面)`。
- 用 `dataclasses.replace(obj, name=新名)` 複製（`Script`/`Rule` 皆 dataclass）；載入/存檔失敗（`ScriptValidationError`/`ValueError`）→ 捕捉記錄「複製失敗：…」不崩潰。
- 面向使用者訊息維持繁中。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH，Qt 需 offscreen）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/app/naming.py` | `unique_copy_name` 純函式 | Create |
| `src/keyboard_executor/app/script_list.py` | `ScriptListController.duplicate_selected` | Modify |
| `src/keyboard_executor/app/rule_list.py` | `RuleListController.duplicate` | Modify |
| `src/keyboard_executor/app/main_window.py` | 兩顆「複製」按鈕＋handler＋wire | Modify |
| 對應 `tests/…` | 各層測試 | Create/Modify |

執行順序 **Task 1→4**：Task 2 消費 Task 1 的 `unique_copy_name`；Task 3 消費 Task 2 的控制器方法。

---

### Task 1: `app/naming.py` — `unique_copy_name`

**Files:**
- Create: `src/keyboard_executor/app/naming.py`
- Test: `tests/app/test_naming.py`

**Interfaces:**
- Produces: `unique_copy_name(base: str, existing) -> str`（`existing` 可為任何可疊代名稱集合）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/app/test_naming.py`：
```python
from keyboard_executor.app.naming import unique_copy_name


def test_no_conflict_returns_base_copy():
    assert unique_copy_name("甲", ["乙"]) == "甲 - 複製"


def test_single_conflict_appends_2():
    assert unique_copy_name("甲", ["甲", "甲 - 複製"]) == "甲 - 複製 2"


def test_multi_conflict_finds_next_free_number():
    assert unique_copy_name("甲", ["甲 - 複製", "甲 - 複製 2"]) == "甲 - 複製 3"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_naming.py -v`
Expected: FAIL（`ModuleNotFoundError: ...app.naming`）

- [ ] **Step 3: 最小實作**

Create `src/keyboard_executor/app/naming.py`：
```python
"""名稱工具（純邏輯，無 Qt）。"""
from __future__ import annotations


def unique_copy_name(base: str, existing) -> str:
    """回一個不在 existing 內的複製名：「base - 複製」，衝突則加序號 2、3…。"""
    existing = set(existing)
    candidate = f"{base} - 複製"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{candidate} {n}" in existing:
        n += 1
    return f"{candidate} {n}"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_naming.py -v`
Expected: PASS（3 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/naming.py tests/app/test_naming.py
git commit -m "feat(naming): unique_copy_name 產生唯一複製名"
```

---

### Task 2: 控制器複製方法（腳本＋規則）

**Files:**
- Modify: `src/keyboard_executor/app/script_list.py`（import＋`duplicate_selected`）
- Modify: `src/keyboard_executor/app/rule_list.py`（import＋`duplicate`）
- Test: `tests/app/test_script_list.py`、`tests/app/test_rule_list.py`（沿用檔內 `make_storage`）

**Interfaces:**
- Consumes: `unique_copy_name`（Task 1）。
- Produces: `ScriptListController.duplicate_selected() -> str`（未選取拋 `ValueError`）；`RuleListController.duplicate(name: str) -> str`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_script_list.py` 末端新增（沿用檔內 `make_storage`；`make_storage(tmp_path, names=("甲",))` 只建一個「甲」）：
```python
import dataclasses


def test_duplicate_selected_copies_content_and_layout(tmp_path):
    storage = make_storage(tmp_path, names=("甲",))
    storage.save_layout("甲", {"node": [1, 2]})
    controller = ScriptListController(storage)
    controller.refresh()
    controller.select("甲")
    new = controller.duplicate_selected()
    assert new == "甲 - 複製"
    assert new in controller.names                      # 複製後清單含新名
    copy = storage.load(new)
    assert copy == dataclasses.replace(storage.load("甲"), name=new)   # 除名稱外一模一樣
    assert storage.load_layout(new) == {"node": [1, 2]}  # 版面一併複製


def test_duplicate_selected_raises_when_nothing_selected(tmp_path):
    controller = ScriptListController(make_storage(tmp_path))
    controller.refresh()
    with pytest.raises(ValueError):
        controller.duplicate_selected()
```

在 `tests/app/test_rule_list.py` 末端新增（沿用檔內 `make_storage`，其已建「乙」「甲」）：
```python
import dataclasses


def test_duplicate_copies_rule_with_unique_name(tmp_path):
    storage = make_storage(tmp_path)
    controller = RuleListController(storage)
    new = controller.duplicate("甲")
    assert new == "甲 - 複製"
    copy = storage.load(new)
    assert copy == dataclasses.replace(storage.load("甲"), name=new)   # 除名稱外一模一樣
    assert new in storage.list_names()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_list.py tests/app/test_rule_list.py -k "duplicate" -v`
Expected: FAIL（控制器無 `duplicate_selected`／`duplicate`）

- [ ] **Step 3: 最小實作**

`script_list.py`：檔頭 import 改為（加 `dataclasses` 與 `unique_copy_name`）：
```python
from __future__ import annotations

import dataclasses

from keyboard_executor.app.naming import unique_copy_name
from keyboard_executor.core.models import ScriptValidationError
```
在 `delete_selected` 之後新增方法：
```python
    def duplicate_selected(self) -> str:
        if self._selected is None:
            raise ValueError("尚未選取腳本")
        name = self._selected
        new = unique_copy_name(name, self._storage.list_names())
        self._storage.save(dataclasses.replace(self._storage.load(name), name=new))
        layout = self._storage.load_layout(name)
        if layout is not None:
            self._storage.save_layout(new, layout)   # 版面（node 位置）一併複製
        self.refresh()
        return new
```

`rule_list.py`：檔頭 import 加一行（`dataclasses` 已 import）：
```python
from keyboard_executor.app.naming import unique_copy_name
```
在 `delete` 之後新增方法：
```python
    def duplicate(self, name: str) -> str:
        new = unique_copy_name(name, self._storage.list_names())
        self._storage.save(dataclasses.replace(self._storage.load(name), name=new))
        return new
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_list.py tests/app/test_rule_list.py -v`
Expected: PASS（新增 3 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/script_list.py src/keyboard_executor/app/rule_list.py tests/app/test_script_list.py tests/app/test_rule_list.py
git commit -m "feat(list): 控制器加複製方法（腳本含版面、規則）"
```

---

### Task 3: main_window 複製按鈕＋handler

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`（腳本頁尾 298-307、規則頁尾 338-343、`_wire` 388-405、handler 區）
- Test: `tests/app/test_main_window.py`（沿用檔內 `make_window`、`ScriptStorage`/`RuleStorage`/`script_from_dict`/`rule_from_dict`）

**Interfaces:**
- Consumes: `ScriptListController.duplicate_selected()`、`RuleListController.duplicate(name)`（Task 2）。
- Produces: `MainWindow.script_duplicate_button` / `rule_duplicate_button`（`QPushButton`）、`_on_duplicate_script` / `_on_duplicate_rule`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_main_window.py` 末端新增：
```python
def test_duplicate_script_button_creates_copy(qapp, tmp_path):
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    window = make_window(tmp_path)
    window.script_list.setCurrentRow(0)          # 選「甲」
    window.script_duplicate_button.click()
    assert ScriptStorage(tmp_path).list_names() == ["甲", "甲 - 複製"]
    assert window.script_list.count() == 2


def test_duplicate_rule_button_creates_copy(qapp, tmp_path):
    RuleStorage(tmp_path).save(rule_from_dict({
        "name": "甲", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "x"},
        "triggers": [{"type": "notify", "message": "m"}]}))
    window = make_window(tmp_path)
    window.rule_list.setCurrentRow(0)
    window.rule_duplicate_button.click()
    assert RuleStorage(tmp_path).list_names() == ["甲", "甲 - 複製"]
```
（`make_window`、`ScriptStorage`、`RuleStorage`、`script_from_dict`、`rule_from_dict` 皆為檔內既有 import／helper。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -k "duplicate" -v`
Expected: FAIL（`MainWindow` 無 `script_duplicate_button`／`rule_duplicate_button`）

- [ ] **Step 3: 最小實作**

`main_window.py`：

3a. 腳本頁尾：在 `self.edit_button = QPushButton("編輯")`（299 行）之後加建立、並在 `foot.addWidget(self.edit_button)`（304 行）之後插入 addWidget：
```python
        self.edit_button = QPushButton("編輯")
        self.script_duplicate_button = QPushButton("複製")
        self.record_button = QPushButton("錄製")
```
```python
        foot.addWidget(self.edit_button)
        foot.addWidget(self.script_duplicate_button)
        foot.addWidget(self.record_button)
```

3b. 規則頁尾：在 `self.rule_edit_button = QPushButton("編輯 / 新增")`（338 行）之後加、並在 `foot.addWidget(self.rule_edit_button)`（341 行）之後插入：
```python
        self.rule_edit_button = QPushButton("編輯 / 新增")
        self.rule_duplicate_button = QPushButton("複製")
```
```python
        foot.addWidget(self.rule_edit_button)
        foot.addWidget(self.rule_duplicate_button)
        foot.addStretch(1)
```

3c. `_wire`：加兩行 connect：
```python
        self.script_duplicate_button.clicked.connect(self._on_duplicate_script)
        self.rule_duplicate_button.clicked.connect(self._on_duplicate_rule)
```

3d. 在 `_on_delete_rule` 附近新增兩個 handler：
```python
    def _on_duplicate_script(self) -> None:
        name = self._scripts.selected
        if name is None:
            self.append_log("請先選取要複製的腳本")
            return
        try:
            new = self._scripts.duplicate_selected()
        except (ScriptValidationError, ValueError) as e:
            self.append_log(f"腳本複製失敗：{e}")
            return
        self.append_log(f"已複製為「{new}」")
        self.refresh_scripts()
        self.script_list.setCurrentRow(self._scripts.names.index(new))

    def _on_duplicate_rule(self) -> None:
        index = self.rule_list.currentRow()
        if index < 0 or index >= len(self._rules.names):
            self.append_log("請先選取要複製的規則")
            return
        name = self._rules.names[index]
        try:
            new = self._rules.duplicate(name)
        except ScriptValidationError as e:
            self.append_log(f"規則複製失敗：{e}")
            return
        self.append_log(f"已複製為「{new}」")
        self.refresh_rules()
        self.rule_list.setCurrentRow(self._rules.names.index(new))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_main_window.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/main_window.py tests/app/test_main_window.py
git commit -m "feat(ui): 腳本/規則清單加「複製」按鈕"
```

---

### Task 4: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 681 + 新增約 8 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~3); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序）。實機驗收：選一條腳本／規則按「複製」→ 清單多一條「原名 - 複製」，可再進「編輯」改名調整。此步驟在計畫外，由使用者驅動。
