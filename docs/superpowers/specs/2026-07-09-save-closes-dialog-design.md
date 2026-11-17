# 儲存成功自動關閉視窗 — 設計文件

- **日期**：2026-07-09
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

有「儲存」按鈕的編輯視窗（規則編輯器、腳本編輯器、設定頁、錄製面板）目前按儲存成功後只顯示狀態文字、視窗停留，需要使用者再手動關閉。需求方希望**儲存成功即自動關閉**。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 觸發時機 | **只有儲存成功才關**；驗證失敗維持開著並顯示錯誤，讓使用者修正 |
| 範圍 | 四個有主「儲存」按鈕的 QDialog：規則編輯器、腳本編輯器、設定頁、錄製面板 |
| 機制 | 成功路徑最後呼叫 `self.accept()`（QDialog 標準確認並關閉；四者皆以 `.exec()` 開啟） |
| 子動作不關 | 規則編輯器的「框選並擷取模板」（`_on_capture_template`）是子動作，不關整個視窗——只動主 `_on_save` |

## 3. 各元件改動（皆為在成功路徑末端加一行 `self.accept()`）

| 檔案 | 方法 | 現況成功路徑末端 | 改動 |
|------|------|------------------|------|
| `app/rule_editor.py` | `_on_save` | `self.status_label.setText(f"已儲存：{path}")` | 其後加 `self.accept()` |
| `app/script_editor.py` | `_on_save` | `self.status_label.setText(f"已儲存：{path}")` | 其後加 `self.accept()` |
| `app/settings_page.py` | `_on_save` | `self.saved.emit(...)` 之後 | 其後加 `self.accept()`（`saved` 訊號仍先發） |
| `app/recorder_panel.py` | `_on_save_clicked` | `self.status_label.setText(f"已儲存：{path}…")` | 其後加 `self.accept()` |

驗證失敗路徑不變：`ScriptValidationError` 時 `setText(儲存失敗…)` 後 `return`，不呼叫 `accept()`。

## 4. 錯誤處理

失敗即維持視窗開著並顯示繁中錯誤（現況行為），使用者可修正後再存。`accept()` 只在成功路徑呼叫。

## 5. 測試（全程 TDD）

每個視窗一條「成功→關閉、失敗→不關」測試。以 `QDialog.result()`（`accept()` 後為 `QDialog.DialogCode.Accepted`）或 `isVisible()` 判定是否關閉；測試中對話框未 `.exec()`，`accept()` 只設定 result 並隱藏，物件與 `status_label` 仍可讀取。

| 層 | 測試 |
|----|------|
| `rule_editor` | 有效規則存檔後 `result()==Accepted`；驗證失敗（如空 pattern）後未 Accepted、狀態顯示失敗 |
| `script_editor` | 有效腳本存檔後 Accepted；失敗後未 Accepted |
| `settings_page` | 有效設定存檔後 Accepted 且 `saved` 有發；驗證失敗後未 Accepted、不發 `saved` |
| `recorder_panel` | 有動作可存時存檔後 Accepted；無法存（如無動作）時未 Accepted |

既有「按存後讀 status_label／storage」的測試仍成立（`accept()` 不清文字、不銷毀物件）；實作時跑全套件確認無回歸。

## 6. 非目標（YAGNI）

- 非「儲存」的子動作（框選區域、擷取模板、滴管取色）維持現有關閉行為，不改。
- 儲存後不加確認對話框或「未存變更」提示（超出範圍）。
- 不改各視窗其餘行為（欄位、驗證、`saved` 訊號等）。
