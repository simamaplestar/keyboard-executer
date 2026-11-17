# 迴圈顯示換行 ＋ 迴圈內新增動作 — 設計文件

- **日期**：2026-07-15
- **狀態**：已與需求方確認設計方向

## 1. 動機

腳本編輯器把動作「組成迴圈」後：
1. 迴圈方塊內的動作排成單一橫列、不換行，動作一多就變成很長一條、難查看。
2. 想在迴圈內新增動作時，目前只能先在外面新增再框選組成迴圈，沒有「直接在迴圈裡加」的途徑。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 換行 | 迴圈內含 chip（含末端「＋ 新增」）依最大列寬**換成多列** |
| 列內箭頭 | **保留列內 → 箭頭**；跨列不畫（上到下、左到右閱讀順序即先後） |
| 迴圈內新增 | 迴圈框內末端放一個「**＋ 新增**」方塊，單擊 → 選動作類型 → 填 → **加到該迴圈末尾** |
| 插入位置 | 一律加末尾（不指定位置） |

## 3. 架構總覽

四個改動單元，皆為現有 loop 顯示/模型的延伸：

1. **`wrap_rows`（`app/script_editor.py` 模組純函式）** — 依累計寬度把 chip 索引切成多列（仿 `even_layout` 為純函式）。
2. **`ScriptEditorModel.add_to_loop`（`app/script_editor_model.py`）** — 把動作加到指定迴圈 `actions` 末尾、整份重驗（比照 `update_loop_inner`）。
3. **`_InnerAddChip` ＋ `_LoopGroup` 換行渲染（`app/script_editor.py`）** — 新「＋ 新增」chip；`_LoopGroup` 用 `wrap_rows` 把內含 chip＋「＋」排成多列、列內加箭頭；新增 `addClicked` 訊號。
4. **對話框接線（`app/script_editor.py`）** — `_LoopGroup.addClicked` → `_add_to_loop`（開對話框）→ 可測的 `add_to_loop_action` → `model.add_to_loop` → refresh。

## 4. 單元一：`wrap_rows`（純函式）

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

## 5. 單元二：`ScriptEditorModel.add_to_loop`

比照 `update_loop_inner`（同檔）：
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

## 6. 單元三：`_InnerAddChip` ＋ `_LoopGroup` 換行

### 6.1 `_arrow_label(zoom)`（抽出既有內聯箭頭）
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

### 6.2 `_InnerAddChip`（仿 `_InnerChip`）
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
`objectName="loopAddChip"` 而非 `"chip"`、類別非 `_InnerChip`——確保既有以 `findChildren(_InnerChip)`／`objectName=="chip"` 計數（各期望 2）的測試不受影響。

### 6.3 `_LoopGroup`
- 新增 `addClicked = Signal(int)`（迴圈索引）。
- `__init__` 保留 header；把原單一 `QHBoxLayout` 換成：建立內含 `_InnerChip` 清單（連 `doubleClicked`→`innerDoubleClicked`）＋末端 `_InnerAddChip`（連 `clicked`→`addClicked.emit(self.index)`）；以各 chip `sizeHint().width()` 呼叫 `wrap_rows(widths, _LOOP_MAX_ROW_WIDTH*zoom, gap+arrow_w)` 得多列；每列一個 `QHBoxLayout`（列內 `pos>0` 時前置 `_arrow_label`）、`addStretch(1)` 左對齊，疊進 `QVBoxLayout`。
- 模組常數 `_LOOP_MAX_ROW_WIDTH = 520`（px，隨 zoom 縮放）。
- `inner_count()` 維持 `len(self._inner)`（不含「＋」），既有測試不受影響。

## 7. 單元四：對話框接線

`refresh()` 建 loop 節點處（既有連 `innerDoubleClicked`）加：`node.addClicked.connect(self._add_to_loop)`。

可測 seam（比照既有 `add_action`）：
```python
def add_to_loop_action(self, loop_index: int, atype: str, values: dict) -> None:
    """表單字串值 → 驗證 → 加到 loop_index 迴圈末尾（可直接測試，不開對話框）。"""
    action = to_action_dict(atype, values)
    self._push_undo()
    self._model.add_to_loop(loop_index, action)
    self.refresh()
```
Modal 處理器（比照 `_on_add`）：
```python
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

## 8. 資料流

```
「＋ 新增」單擊 → _InnerAddChip.clicked → _LoopGroup.addClicked(loop_index)
  → ScriptEditorDialog._add_to_loop：選類型 + ActionForm
  → add_to_loop_action(loop_index, atype, values)：to_action_dict → _push_undo
  → model.add_to_loop(loop_index, action)（末尾追加、整份重驗）→ refresh()

顯示：_LoopGroup.__init__ → wrap_rows(chip 寬度) → 多列 QHBoxLayout（列內 → 箭頭）
```

## 9. 錯誤處理

- 無效動作（`to_action_dict`／`add_to_loop` 的 `action_from_dict` 拋 `ScriptValidationError`）→ `_add_to_loop` 顯示「無效的動作：…」；比照 `_on_add`。
- `add_to_loop` 對非 loop 索引不動作。
- 空迴圈（模型驗證禁止空 actions，實務不會發生）→ 仍顯示「＋ 新增」chip。

## 10. 測試（全程 TDD，皆於 `tests/app/test_script_editor_widget.py`）

| 層 | 測試 |
|----|------|
| `wrap_rows` | 依寬度換多列（`[100,100,100],250,10`→`[[0,1],[2]]`）；放得下不切；單一超寬自成一列（`[300,100],250,10`→`[[0],[1]]`）；空清單→`[]` |
| `add_to_loop`（model） | 末尾追加＋重驗（迴圈 actions 多一個、count 不變）；非 loop no-op；無效動作拋 `ScriptValidationError` 且狀態不變 |
| `_LoopGroup`（widget） | 有一個 `_InnerAddChip`；`addClicked` 帶迴圈索引；`findChildren(_InnerChip)`／`objectName=="chip"` 仍等於內含動作數（不含「＋」）；多內含動作不遺漏 |
| 對話框 | `add_to_loop_action(0, "delay", {"ms":"80"})` → 迴圈多一個 delay 動作、refresh 後 `_nodes[0].inner_count()` 增加 |

既有 loop 測試（`test_loop_group_shows_inner_actions`、`test_loop_inner_double_click_emits_signal`、`test_loop_group_wraps_full_chips_not_mini`、`test_update_loop_inner_...`）續過。

## 11. 非目標（YAGNI）

- 指定插入位置（一律加末尾）。
- 拖曳把動作拉進／拉出迴圈。
- 迴圈內刪除單一動作（另議）。
- 跨列箭頭。
