# 迴圈顯示換行 ＋ 迴圈內新增動作實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 迴圈方塊內的動作依最大列寬換成多列（列內保留 → 箭頭）；迴圈框內末端加「＋ 新增」方塊，單擊即可在該迴圈末尾新增動作。

**Architecture:** 新增純函式 `wrap_rows`（依累計寬度切列）；`_LoopGroup` 用它把內含 chip＋末端 `_InnerAddChip` 排成多列；`ScriptEditorModel.add_to_loop` 末尾追加重驗；對話框 `_add_to_loop`（modal）→ 可測 `add_to_loop_action` → `model.add_to_loop` → refresh。

**Tech Stack:** PySide6/Qt6（`QT_QPA_PLATFORM=offscreen` headless tests）、pytest。

## Global Constraints

- 換行：`wrap_rows(widths, max_width, gap)` 依累計寬度切列，單一超寬元素自成一列（不硬切）。
- 列內 chip 間保留 `→` 箭頭；跨列不畫。左對齊（`addStretch(1)`）。
- 「＋ 新增」為 `_InnerAddChip`（`objectName="loopAddChip"`、**非** `_InnerChip`），加在內含 chip 末端；單擊 → `_LoopGroup.addClicked(loop_index)`。
- `add_to_loop` 一律加該迴圈 `actions` 末尾、整份過 `action_from_dict` 重驗；非 loop no-op；無效動作拋 `ScriptValidationError` 且不改狀態。
- 所有使用者可見字串繁體中文。既有 loop 測試須續過（`inner_count()` 仍不含「＋」；`findChildren(_InnerChip)`／`objectName=="chip"` 仍等於內含動作數）。
- 每步 TDD、小步提交。測試指令：`QT_QPA_PLATFORM=offscreen python.exe -m pytest <files> -q`（以 `<venv-py>` 代稱該 python）。

---

## 檔案結構

- `src/keyboard_executor/app/script_editor.py` — `wrap_rows`（Task 1）、`_arrow_label`＋`_InnerAddChip`＋`_LoopGroup` 換行（Task 3）、`_add_to_loop`＋`add_to_loop_action`＋refresh 接線（Task 4）
- `src/keyboard_executor/app/script_editor_model.py` — `add_to_loop`（Task 2）

---

## Task 1: `wrap_rows` 純函式

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（於 `even_layout` 附近新增模組函式）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Produces: `wrap_rows(widths: list[int], max_width: int, gap: int) -> list[list[int]]`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`；`even_layout` 已於檔頭 import，加入 `wrap_rows`）

```python
def test_wrap_rows_breaks_by_width():
    assert wrap_rows([100, 100, 100], 250, 10) == [[0, 1], [2]]


def test_wrap_rows_single_row_when_fits():
    assert wrap_rows([50, 50, 50], 500, 10) == [[0, 1, 2]]


def test_wrap_rows_wide_item_self_row():
    assert wrap_rows([300, 100], 250, 10) == [[0], [1]]


def test_wrap_rows_empty():
    assert wrap_rows([], 250, 10) == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k wrap_rows`
Expected: FAIL（無 `wrap_rows`）。

- [ ] **Step 3: 實作 `wrap_rows`**（`script_editor.py` 模組層，`even_layout` 附近）

```python
def wrap_rows(widths: list[int], max_width: int, gap: int) -> list[list[int]]:
    """把 widths（各元素寬度）依 max_width 切成多列，回傳每列的索引清單。
    單一元素超過 max_width 時自成一列（不硬切）。"""
    rows: list[list[int]] = []
    cur: list[int] = []
    cur_w = 0
    for i, w in enumerate(widths):
        if cur and cur_w + gap + w > max_width:
            rows.append(cur)
            cur, cur_w = [], 0
        cur_w += (gap if cur else 0) + w
        cur.append(i)
    if cur:
        rows.append(cur)
    return rows
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k wrap_rows`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor): wrap_rows 依最大列寬把索引切成多列"
```

---

## Task 2: `ScriptEditorModel.add_to_loop`

**Files:**
- Modify: `src/keyboard_executor/app/script_editor_model.py`（於 `update_loop_inner` 之後新增）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Produces: `ScriptEditorModel.add_to_loop(index: int, action_dict: dict) -> None`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`）

```python
def _loop_model():
    model = ScriptEditorModel.new("x")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    return model


def test_add_to_loop_appends_and_revalidates():
    model = _loop_model()
    model.add_to_loop(0, {"type": "delay", "ms": 80})
    inner = model.action_at(0)["actions"]
    assert len(inner) == 3
    assert inner[2] == {"type": "delay", "ms": 80}
    assert model.action_at(0)["count"] == 3         # 次數保留


def test_add_to_loop_non_loop_noop():
    model = ScriptEditorModel.new("x")
    model.insert(0, {"type": "key_press", "key": "a"})
    model.add_to_loop(0, {"type": "delay", "ms": 80})   # index 0 非 loop
    assert model.action_at(0)["type"] == "key_press"


def test_add_to_loop_invalid_raises_and_keeps_state():
    model = _loop_model()
    with pytest.raises(ScriptValidationError):
        model.add_to_loop(0, {"type": "delay"})          # 缺 ms
    assert len(model.action_at(0)["actions"]) == 2       # 狀態不變
```

（`ScriptValidationError` 由 `keyboard_executor.core.models` import；若測試檔尚未 import，於檔頭加入。）

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k add_to_loop`
Expected: FAIL（無 `add_to_loop`）。

- [ ] **Step 3: 實作 `add_to_loop`**（`script_editor_model.py`，`update_loop_inner` 之後）

```python
    def add_to_loop(self, index: int, action_dict: dict) -> None:
        """把動作加到 index 迴圈的 actions 末尾（次數不變；整份仍過驗證）。非 loop 則不動。
        無效動作 → action_from_dict 於改動 self._actions 前拋 ScriptValidationError，狀態不變。"""
        d = self._actions[index]
        if d.get("type") != "loop":
            return
        inner = list(d.get("actions", []))
        inner.append(action_to_dict(action_from_dict(action_dict)))
        self._actions[index] = action_to_dict(action_from_dict(
            {"type": "loop", "count": d.get("count", 1), "actions": inner}))
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k add_to_loop`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/script_editor_model.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor-model): add_to_loop 把動作加到迴圈末尾並重驗"
```

---

## Task 3: `_InnerAddChip` ＋ `_LoopGroup` 換行渲染

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（`_arrow_label` 新增、`_InnerAddChip` 新增、`_LoopGroup` `__init__` 改寫、`addClicked` 訊號、模組常數 `_LOOP_MAX_ROW_WIDTH`）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `wrap_rows`（Task 1）、`_fill_keycap`、`_InnerChip`。
- Produces: `_InnerAddChip`（`clicked: Signal`, `objectName="loopAddChip"`）；`_LoopGroup.addClicked: Signal(int)`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`）

```python
def test_loop_group_has_add_chip_emitting_index(qapp):
    from keyboard_executor.app.script_editor import _InnerAddChip, _InnerChip, _LoopGroup
    action = {"type": "loop", "count": 3, "actions": [
        {"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]}
    loop = _LoopGroup(0, action, 1.0)
    adds = loop.findChildren(_InnerAddChip)
    assert len(adds) == 1                              # 末端一個「＋新增」
    assert len(loop.findChildren(_InnerChip)) == 2     # 內含動作 chip 仍是 2（不含「＋」）
    captured = []
    loop.addClicked.connect(captured.append)
    adds[0].clicked.emit()
    assert captured == [0]                             # 帶迴圈索引


def test_loop_group_renders_all_inner_chips_when_many(qapp):
    from keyboard_executor.app.script_editor import _InnerChip, _LoopGroup
    action = {"type": "loop", "count": 2,
              "actions": [{"type": "delay", "ms": 10}] * 8}
    loop = _LoopGroup(0, action, 1.0)
    assert len(loop.findChildren(_InnerChip)) == 8     # 多動作換列不遺漏
    assert loop.inner_count() == 8
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k "loop_group_has_add or renders_all_inner"`
Expected: FAIL（無 `_InnerAddChip`／`addClicked`）。

- [ ] **Step 3: 新增 `_LOOP_MAX_ROW_WIDTH`、`_arrow_label`、`_InnerAddChip`**

模組常數（`_LoopGroup` 之前）：
```python
_LOOP_MAX_ROW_WIDTH = 520      # 迴圈內含動作換列的最大列寬（px，隨 zoom 縮放）
```

抽出箭頭 helper（模組層，`_InnerChip` 之後）：
```python
def _arrow_label(zoom: float) -> QLabel:
    arrow = QLabel("→")
    arrow.setObjectName("chipArrow")
    arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    af = arrow.font()
    af.setPointSizeF(max(9.0, 12.0 * zoom))
    af.setBold(True)
    arrow.setFont(af)
    return arrow
```

新增「＋ 新增」chip（`_InnerChip` 之後）：
```python
class _InnerAddChip(QFrame):
    """迴圈框內末端的「＋ 新增」方塊：單擊 → 在該迴圈末尾新增動作。"""

    clicked = Signal()

    def __init__(self, zoom: float = 1.0):
        super().__init__()
        self.setObjectName("loopAddChip")     # 與一般 chip（objectName "chip"）區隔
        _fill_keycap(self, "＋", "新增", zoom)
        self.setToolTip("在這個迴圈末尾新增動作")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):   # noqa: N802
        self.clicked.emit()
        event.accept()
```

- [ ] **Step 4: 改寫 `_LoopGroup`**

在 class 宣告加訊號：
```python
class _LoopGroup(_DraggableNode):
    innerDoubleClicked = Signal(int, int)    # (迴圈索引, 迴圈內索引)
    addClicked = Signal(int)                  # 迴圈索引（末端「＋新增」被點）
```

`__init__` 由 header 之後改為（取代原單一 `row = QHBoxLayout()` 段）：
```python
        outer.addWidget(header)

        # 內含動作 chip ＋ 末端「＋ 新增」chip
        chips: list[QFrame] = []
        for j, a in enumerate(self._inner):
            chip = _InnerChip(j, a, zoom)
            chip.doubleClicked.connect(
                lambda ii: self.innerDoubleClicked.emit(self.index, ii))
            chips.append(chip)
        add_chip = _InnerAddChip(zoom)
        add_chip.clicked.connect(lambda: self.addClicked.emit(self.index))
        chips.append(add_chip)

        # 依最大列寬換行；列內保留 → 箭頭、跨列不畫
        gap = int(7 * zoom)
        arrow_w = int(22 * zoom)      # 箭頭＋間距佔位，估算換列用
        widths = [c.sizeHint().width() for c in chips]
        rows = wrap_rows(widths, int(_LOOP_MAX_ROW_WIDTH * zoom), gap + arrow_w)
        rows_lay = QVBoxLayout()
        rows_lay.setSpacing(gap)
        for row_idx in rows:
            row = QHBoxLayout()
            row.setSpacing(gap)
            row.setContentsMargins(0, 0, 0, 0)
            for pos, ci in enumerate(row_idx):
                if pos > 0:
                    row.addWidget(_arrow_label(zoom))
                row.addWidget(chips[ci])
            row.addStretch(1)
            rows_lay.addLayout(row)
        outer.addLayout(rows_lay)
        self.setToolTip("迴圈：外框內為重複執行的動作（雙擊改次數、雙擊動作可編輯、＋新增動作）")
```
（移除原本的 `row = QHBoxLayout()`／內聯箭頭迴圈／`（空迴圈）` 分支——「＋ 新增」chip 一律存在。）

- [ ] **Step 5: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q`
Expected: PASS（含既有 `test_loop_group_shows_inner_actions`／`test_loop_inner_double_click_emits_signal`／`test_loop_group_wraps_full_chips_not_mini`——`_InnerChip`／`objectName=="chip"` 仍計 2、`inner_count()` 仍 2）。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor): 迴圈框內含動作換行顯示＋末端「＋新增」方塊"
```

---

## Task 4: 對話框接線（`_add_to_loop` ＋ `add_to_loop_action` ＋ refresh）

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（`refresh` 建 loop 節點處連 `addClicked`；新增 `add_to_loop_action` 與 `_add_to_loop`）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `_LoopGroup.addClicked`（Task 3）、`model.add_to_loop`（Task 2）、`to_action_dict`。
- Produces: `ScriptEditorDialog.add_to_loop_action(loop_index, atype, values)`（可測 seam）；`_add_to_loop(loop_index)`（modal）。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`）

```python
def test_add_to_loop_action_appends_and_refreshes(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    dialog = ScriptEditorDialog(model, storage)
    dialog.add_to_loop_action(0, "delay", {"ms": "80"})
    inner = model.action_at(0)["actions"]
    assert len(inner) == 3 and inner[2] == {"type": "delay", "ms": 80}
    assert dialog._nodes[0].inner_count() == 3        # refresh 後畫面反映
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q -k add_to_loop_action`
Expected: FAIL（無 `add_to_loop_action`）。

- [ ] **Step 3: refresh 連接 `addClicked`**

`refresh()` 的 loop 分支（既有 `node.innerDoubleClicked.connect(self._edit_loop_inner)` 之後）加：
```python
                node.addClicked.connect(self._add_to_loop)
```

- [ ] **Step 4: 新增 `add_to_loop_action` 與 `_add_to_loop`**（比照既有 `add_action` / `_on_add`）

```python
    def add_to_loop_action(self, loop_index: int, atype: str, values: dict) -> None:
        """表單字串值 → 驗證 → 加到 loop_index 迴圈末尾（可直接測試，不開對話框）。"""
        action = to_action_dict(atype, values)
        self._push_undo()
        self._model.add_to_loop(loop_index, action)
        self.refresh()

    def _add_to_loop(self, loop_index: int) -> None:
        label, ok = QInputDialog.getItem(
            self, "在迴圈內新增動作", "選擇動作類型", sorted(self._label_to_type), 0, False)
        if not ok:
            return
        atype = self._label_to_type.get(label, label)
        form = ActionForm(atype, parent=self)
        if form.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.add_to_loop_action(loop_index, atype, form.values())
            self.status_label.setText("")
        except ScriptValidationError as e:
            self.status_label.setText(f"無效的動作：{e}")
```

- [ ] **Step 5: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_script_editor_widget.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor): 迴圈「＋新增」接線，在迴圈末尾新增動作"
```

---

## 收尾：全套件驗證

- [ ] **執行完整測試套件**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest -q`
Expected: 全綠（726 passed / 4 skipped 之上加本計畫新增測試）。
