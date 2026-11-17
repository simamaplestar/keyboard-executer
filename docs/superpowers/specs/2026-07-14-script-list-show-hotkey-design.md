# 腳本列表顯示啟動快捷鍵 — 設計文件

- **日期**：2026-07-14
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

腳本可設定「啟動快捷鍵」（`ScriptSettings.hotkey`），但腳本列表只顯示名稱，看不出哪個腳本綁了哪個熱鍵。要在列表上顯示每個腳本設定的熱鍵（若有設）。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 顯示格式 | 名稱後加「  [首字大寫熱鍵]」，如 `乙腳本   [Ctrl+Shift+1]`、`丙腳本   [F8]`；`ctrl+shift+1`→`Ctrl+Shift+1`、`f8`→`F8`（每段 `capitalize()`） |
| 何時顯示 | 只有設了熱鍵的腳本加後綴；沒設的只顯示名稱 |
| 顯示與名稱解耦 | 列表項目顯示文字含後綴，但**真正腳本名存 `Qt.UserRole`**；選取邏輯讀 UserRole，不讀顯示文字 |

## 3. 架構總覽

兩個改動點：

1. **`app/script_list.py`** — 新增純函式 `script_list_label(storage, name) -> str`（回傳列表顯示文字，含熱鍵後綴）。
2. **`app/main_window.py`** — `refresh_scripts` 用 `script_list_label` 建 `QListWidgetItem`、把真名存 `UserRole`；選取信號由 `currentTextChanged` 改 `currentItemChanged`，新增 adapter 讀 UserRole 後轉呼叫既有 `_on_script_selected(name)`。

## 4. 單元一：`script_list_label`（`app/script_list.py`）

此模組為純 Python（無 Qt import）。新增（仿既有 `summary_for_script` 的 load＋容錯）：
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
（`ScriptValidationError` 已於該檔 import。）

## 5. 單元二：主視窗接線（`app/main_window.py`）

### 5.1 import
`from PySide6.QtWidgets import (... QListWidget, ...)` 加入 `QListWidgetItem`；`Qt`、`script_list_label` 皆已可用（`Qt` 於第 13 行已 import；`script_list_label` 由 `keyboard_executor.app.script_list` 匯入，與既有 `summary_for_script` 同處）。

### 5.2 `refresh_scripts`
```python
    def refresh_scripts(self) -> None:
        self.script_list.clear()
        for name in self._scripts.refresh():
            item = QListWidgetItem(script_list_label(self._script_storage, name))
            item.setData(Qt.ItemDataRole.UserRole, name)   # 真名與顯示文字解耦
            self.script_list.addItem(item)
        self._refresh_script_hotkeys()
```

### 5.3 選取信號改用 `currentItemChanged` ＋ adapter
`_wire` 裡：
```python
        self.script_list.currentItemChanged.connect(self._on_script_current_changed)
```
（取代原 `self.script_list.currentTextChanged.connect(self._on_script_selected)`。）

新增 adapter，讀 UserRole 後沿用既有 `_on_script_selected(name)`：
```python
    def _on_script_current_changed(self, current, previous) -> None:
        name = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._on_script_selected(name)
```
`_on_script_selected(name)` 不變（已 `if not name: return`；清空/重建列表時 current 為 None → adapter 傳 None → 安全略過）。

### 5.4 不受影響處
- 複製後 `self.script_list.setCurrentRow(self._scripts.names.index(new))` 用 row index，維持不變。
- `itemDoubleClicked` → `_on_edit_script`（不依賴 item 文字）不變。
- 編輯腳本改熱鍵→存檔→`refresh_scripts` 重建 label，自動反映。

## 6. 資料流

```
refresh_scripts → 逐一 script_list_label(storage, name)（load settings.hotkey）
  → QListWidgetItem(顯示文字), item.setData(UserRole, 真名)

選取：currentItemChanged(current, prev)
  → _on_script_current_changed 讀 current.data(UserRole)=真名
  → _on_script_selected(真名) → _scripts.select(真名) + summary
```

## 7. 錯誤處理

- 單一腳本 load 失敗（損毀）→ `script_list_label` 回純名稱（不整批壞掉、不擋其他項目）。
- current 為 None（列表清空/無選取）→ adapter 傳 None → `_on_script_selected` 略過。

## 8. 效能備註

`refresh_scripts` 逐一 `storage.load` 每個腳本取 hotkey；`_refresh_script_hotkeys`（poller 綁定）亦逐一 load 一次，故每次 refresh 每腳本 load 兩次。腳本數少、refresh 非熱路徑，可接受，不特別合併（YAGNI）。

## 9. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `script_list_label`（`tests/app/test_script_list.py`） | 無熱鍵→純名稱；有熱鍵→`名稱   [Ctrl+Shift+1]`（首字大寫、`f8`→`F8`）；load 失敗（存壞腳本）→純名稱 |
| `main_window`（offscreen） | refresh 後某項目文字含 `[熱鍵]`、`item.data(UserRole)` 為真名；`setCurrentRow` 觸發 `currentItemChanged`→`_scripts.select(真名)` 正確、summary 更新；既有 `test_window_lists_scripts_from_storage`（無熱鍵腳本文字＝名稱）續過 |

## 10. 非目標（YAGNI）

- 熱鍵靠右對齊 / 自訂 delegate 繪製（採名稱後綴，簡單）。
- 規則列表顯示熱鍵（規則目前無啟動熱鍵）。
- 合併 `script_list_label` 與 `_refresh_script_hotkeys` 的 load（腳本數少，不優化）。
- 列表即時反映外部改動（沿用既有 refresh 時機：新增/編輯/刪除/複製後）。
