# 「出現時／消失時」泛化到所有條件類型 — 設計文件

- **日期**：2026-07-10
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

規則的「偵測：出現時／消失時」選項目前只在**顏色**條件出現（由 `RuleCondition.absent` 旗標驅動）。需求方希望**文字**與**圖像**條件也能選「消失時」——例如「某文字消失時通知」「某圖示不再出現時通知」。`absent` 語意（條件在目標**不存在**時成立）對三種條件都通用，只是過去僅接線到顏色。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 適用範圍 | 「出現時／消失時」下拉在**文字／圖像／顏色**三種條件都顯示 |
| 旗標 | 沿用既有共用欄位 `RuleCondition.absent`（無需新欄位）；`True`＝消失時、`False`＝出現時 |
| 判定 | 引擎算出 `present`（找到文字／模板命中／顏色夠多）後，`matched = present != absent` |
| UI 文案 | 沿用「出現時／消失時」（對三種條件皆通順） |
| 向後相容 | 舊規則檔文字／圖像無 `absent` → 預設 `False`（出現時），行為不變；舊顏色規則照舊 |

## 3. 語意對照

| 條件 | 出現時（`absent=False`） | 消失時（`absent=True`） |
|------|--------------------------|--------------------------|
| 文字 | 找到符合的文字就觸發 | 找不到符合的文字才觸發 |
| 圖像 | 模板命中（≥ 閾值）就觸發 | 模板未命中才觸發 |
| 顏色 | 符合像素 ≥ 最少像素就觸發（**現況不變**） | 符合像素 < 最少像素才觸發（**現況不變**） |

## 4. 各元件改動

### 4.1 `core/models.py`
`RuleCondition` 已有共用欄位 `absent: bool = False`，無需改資料類別。
- `_validate_rule_condition`：
  - 「文字」允許鍵加入 `"absent"`：`{"type", "pattern", "mode", "absent"}`；建構時帶 `absent=_get_bool(data, "規則 condition", "absent")`。
  - 「圖像」允許鍵加入 `"absent"`：`{"type", "template", "threshold", "absent"}`；建構時帶 `absent=_get_bool(...)`。
  - 「顏色」維持現況（已含 `absent`）。
  - `_get_bool` 缺鍵回 `False`（沿用既有行為），達成向後相容。
- `rule_to_dict`：
  - 文字 cond dict 加 `"absent": rule.condition.absent`。
  - 圖像 cond dict 加 `"absent": rule.condition.absent`。
  - 顏色維持現況（已輸出 `absent`）。

### 4.2 `core/rule_engine.py`（`_matches`）
- 文字分支：
  ```python
  if rule.condition.type == "text":
      boxes = self._platform.ocr_engine.recognize(image)
      present = find_text(boxes, rule.condition.pattern, rule.condition.mode) is not None
      return present != rule.condition.absent, image
  ```
- 圖像分支：
  ```python
  template = self._templates(rule.condition.template)
  present = match_template(image, template, threshold=rule.condition.threshold).found
  return present != rule.condition.absent, image
  ```
- 顏色分支維持現況（`count < min if absent else count >= min`，語意等同 `present != absent`）。

### 4.3 `app/rule_editor_model.py`
- 欄位 `color_absent` 泛化更名為 `absent`（不再顏色專屬），`__init__` 預設 `False`。
- `from_rule`：對所有條件類型 `model.absent = rule.condition.absent`（移出「僅 color 時」的判斷）。
- `to_dict`：三種條件的 dict 都帶 `"absent": self.absent`（文字、圖像、顏色）。

### 4.4 `app/rule_editor.py`
- 「偵測」下拉（`detect_combo`）初始化改讀 `model.absent`（更名）。
- `_update_condition_fields`：把 `detect_combo` 從「僅顏色顯示」的隱藏清單移除，讓它在**所有條件類型**都顯示。
- `_apply_to_model`：`m.absent = self.detect_combo.currentData()`（更名）。

## 5. 資料流

規則存檔：UI `detect_combo` → model `absent` → `to_dict` 寫入該條件的 `"absent"` → `rule_from_dict` 驗證 → `RuleCondition.absent`。
規則比對：`_matches` 依條件類型算 `present`，回 `present != condition.absent`。

## 6. 錯誤處理

- `absent` 型別非布林 → `_get_bool` 沿用既有錯誤（繁中）拒絕。
- 其餘不變：擷取／OCR／模板載入失敗仍由 `evaluate_once` 的 try/except 隔離。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `models` | 文字／圖像 `absent` round-trip；文字／圖像缺 `absent` → 預設 `False`；`rule_to_dict` 文字／圖像含 `absent`；`absent` 非布林拒絕；既有顏色 `absent` 續過 |
| `rule_engine` | 文字 `absent=True`：**找不到**文字才 `matched`；文字 `absent=False`：找到才 `matched`（現況）；圖像 `absent=True`：模板**未命中**才 `matched`；圖像 `absent=False`：命中才 `matched`（現況）；顏色兩向續過 |
| `rule_editor_model` | 文字／圖像規則設 `absent=True` → `to_dict` 對應條件含 `absent=True`；`from_rule` 由文字／圖像規則還原 `absent` |
| `rule_editor` | 「偵測」下拉在文字／圖像條件類型也顯示（`isVisibleTo` 或未被隱藏）；選「消失時」存文字規則 → 規則 `condition.absent=True`；載入既有文字規則的 `absent` 反映到下拉 |

既有以文字／圖像 condition（無 `absent`）建規則、或斷言 `rule_to_dict` 舊格式的測試，因缺鍵預設 `False` 且新增鍵不影響 round-trip 而續可用；斷言顏色 `absent` 者不受影響。

## 8. 非目標（YAGNI）

- 針對每種條件給不同的「出現／消失」文案（統一「出現時／消失時」即可）。
- 「維持 N 秒才算出現／消失」之類的時間去抖（本次只做布林反轉）。
- 針對遊戲反外掛／反作弊畫面的偵測設定（超出範圍且不做）。
