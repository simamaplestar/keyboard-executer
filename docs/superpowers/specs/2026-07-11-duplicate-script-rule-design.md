# 複製腳本 / 複製規則 — 設計文件

- **日期**：2026-07-11
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

使用者常需要以既有腳本／規則為基礎做小調整。目前只能從頭新增，或手動重建。加一個「複製」動作：把選取的腳本／規則整份複製一份、自動給唯一新名稱並存檔，之後再編輯即可。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 命名 | 新名稱＝`原名 - 複製`；已存在則 `原名 - 複製 2`、`原名 - 複製 3`…（純函式產生唯一名） |
| UI | 腳本清單頁尾、規則清單頁尾各加一個「複製」按鈕（編輯／刪除旁）；複製「目前選取」那條 |
| 確認 | 非破壞性 → **不需**確認對話框 |
| 腳本版面 | 複製腳本時，若原腳本有編輯器版面（node 位置）→ 一併複製到新名下 |
| 未選取 | 提示「請先選取要複製的腳本／規則」 |
| 範圍 | 一次複製一條；不做剪貼簿／跨機器貼上、不做多選批次 |

## 3. 命名規則

純函式 `unique_copy_name(base: str, existing) -> str`（`app/naming.py`）：
- 候選 = `f"{base} - 複製"`；若不在 `existing` → 回候選。
- 否則 `n` 從 2 遞增，回第一個不在 `existing` 的 `f"{候選} {n}"`。
- `existing` 接受任何可疊代的名稱集合（呼叫端傳 `storage.list_names()`）。
- 產生的名稱不含 `/`、`\`（`base` 本身已通過名稱驗證，加的後綴無分隔字元）→ 通過 `Script`/`Rule` 的既有名稱驗證。

## 4. 元件改動

### 4.1 `app/naming.py`（新檔，純邏輯）
```python
def unique_copy_name(base: str, existing) -> str:
    """回一個不在 existing 內的複製名：「base - 複製」，衝突則加序號。"""
```

### 4.2 `app/script_list.py`（`ScriptListController`）
- 新增 `duplicate_selected() -> str`：
  - `name = self.selected`；`None` 時拋 `ScriptValidationError("尚未選取腳本")`（呼叫端已先擋，這是保險）。
  - `new = unique_copy_name(name, self._storage.list_names())`。
  - `script = self._storage.load(name)`；`self._storage.save(replace(script, name=new))`。
  - `layout = self._storage.load_layout(name)`；`if layout is not None: self._storage.save_layout(new, layout)`。
  - 回 `new`。

### 4.3 `app/rule_list.py`（`RuleListController`）
- 新增 `duplicate(name: str) -> str`：
  - `new = unique_copy_name(name, self._storage.list_names())`。
  - `rule = self._storage.load(name)`；`self._storage.save(replace(rule, name=new))`。
  - 回 `new`。

### 4.4 `app/main_window.py`
- 腳本頁尾加 `self.script_duplicate_button = QPushButton("複製")`（放在 編輯 與 刪除 之間或旁邊），接 `_on_duplicate_script`。
- 規則頁尾加 `self.rule_duplicate_button = QPushButton("複製")`，接 `_on_duplicate_rule`。
- `_on_duplicate_script`：
  - `name = self._scripts.selected`；`None` → `append_log("請先選取要複製的腳本")`、return。
  - `try: new = self._scripts.duplicate_selected() except ScriptValidationError as e: append_log(f"腳本複製失敗：{e}")`、return。
  - `append_log(f"已複製為「{new}」")`；`refresh_scripts()`；`self._scripts.select(new)`（清單選到新複本）。
- `_on_duplicate_rule`：
  - `index = self.rule_list.currentRow()`；無效 → `append_log("請先選取要複製的規則")`、return。
  - `name = self._rules.names[index]`；`try: new = self._rules.duplicate(name) except ScriptValidationError ...`。
  - `append_log(f"已複製為「{new}」")`；`refresh_rules()`；（可選）把 `rule_list` 選到新複本那列。

## 5. 資料流

複製 → 讀選取名 → `unique_copy_name` 產生唯一新名 → `storage.load` → `replace(obj, name=新名)` → `storage.save`（腳本再 `save_layout`）→ 刷新清單 → 選取新複本 → 日誌。

## 6. 錯誤處理

- 未選取 → 面向使用者提示（繁中），不動作。
- `load`／`save` 失敗（`ScriptValidationError` 等）→ 捕捉、記錄「複製失敗：…」，不崩潰。
- 名稱衝突由 `unique_copy_name` 保證不覆蓋既有檔案。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `naming` | `unique_copy_name`：無衝突回「base - 複製」；「base - 複製」已存在回「base - 複製 2」；「base - 複製」「base - 複製 2」皆存在回「base - 複製 3」 |
| `script_list` | `duplicate_selected`：複本存檔且內容除 `name` 外與原相同（`target_window`/`actions`/`settings`）；回傳的新名在清單內；原腳本有 layout → 新名下也有相同 layout；未選取時拋錯 |
| `rule_list` | `duplicate`：複本存檔且內容除 `name` 外與原相同；新名唯一；回新名 |
| `main_window` | 腳本／規則頁尾各有「複製」按鈕；選取一條後點「複製」→ 清單多一條、日誌顯示「已複製為…」；未選取點複製 → 顯示「請先選取…」 |

## 8. 非目標（YAGNI）

- 複製到系統剪貼簿／跨機器貼上。
- 多選批次複製（一次一條）。
- 複製時就地改名對話框（先複製成預設名，之後用既有「編輯」改名即可）。
