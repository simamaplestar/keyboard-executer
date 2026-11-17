# 規則多動作觸發 — 設計文件

- **日期**：2026-07-09
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

一條監看規則目前只能選單一觸發類型（notify / run_script / stop_all）。需求方希望一次觸發能**同時做多件事**，至少「顯示通知 + 全部停止」要能一起發生（例：偵測到 CAPTCHA → 停掉所有自動化並通知我）。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 觸發模型 | 從單一觸發改為**一組觸發動作**（可勾選多個，任意組合） |
| 動作種類 | 沿用現有三種：顯示通知（訊息）、全部停止、執行腳本（名稱） |
| UI | 「觸發類型」下拉改為三個**勾選框** + 訊息欄 + 腳本下拉 |
| 執行順序 | 固定 **通知 → 執行腳本 → 全部停止**（先通知才收得到，停止放最後） |
| 向後相容 | 舊規則檔的單物件 `"trigger"` 載入時自動遷移為一元素清單 |

## 3. 資料模型（`core/models.py`）

- `RuleTrigger`（單一動作：`type` + `script_name`/`message`）**維持不變**。
- `Rule` 的 `trigger: RuleTrigger` 改為 `triggers: tuple[RuleTrigger, ...]`（一組動作）。
- `rule_from_dict`：
  - `_check_no_extra` 的規則允許鍵加入 `triggers`（並仍接受舊 `trigger`）。
  - 解析：`"triggers"` 存在 → 逐項 `_validate_rule_trigger`；否則 `"trigger"` 存在 → 包成 `(_validate_rule_trigger(...),)`（遷移）；兩者皆無 → 拋「規則缺少欄位 triggers」。
  - 驗證：`triggers` 為非空清單（至少一個動作），每個動作各自驗證（notify 需 message、run_script 需 script_name，沿用現有 `_validate_rule_trigger`）。
- `rule_to_dict`：輸出 `"triggers": [trigger_to_dict(t) for t in rule.triggers]`（新格式）。舊規則載入後下次存檔即升級。

## 4. 引擎（`core/rule_engine.py`）

- `_fire(rule)` 改為：先 `on_fire(rule.name, "+".join(t.type for t in rule.triggers))`（GUI「觸發」日誌顯示組合），再**依序**對每個 `trig in rule.triggers` 呼叫 `_fire_one(rule, trig)`。
- `_fire_one(rule, trig)`：沿用現有 per-type 邏輯（run_script 載入播放、stop_all `stop_event.set()` + `on_stop_all()`、notify `self._notifier(trig.message)`），不改各自行為。
- 清單順序由編輯器以固定順序（notify、run_script、stop_all）建立，故通知先於停止發生。
- 例外隔離（**每個動作各自隔離**）：`_fire` 逐一以 try/except 呼叫 `_fire_one`；單一動作拋例外只記錄該動作失敗（`_log_fire_failure`）並**續做後面的動作**——確保安全性的 `stop_all`（排在最後）不會被前面失敗的動作（如 `run_script` 載入失敗）連帶跳過。`evaluate_once` 外層的 try/except 仍保留作最後防線。

## 5. 規則編輯器（`app/rule_editor_model.py` + `app/rule_editor.py`）

- **Model**：以三個布林旗標＋既有欄位表示：`notify_enabled`、`message`、`stop_all_enabled`、`run_script_enabled`、`script_name`。
  - `from_rule`：依 `rule.triggers` 內各動作設定對應旗標與欄位。
  - `to_dict`：依旗標**按固定順序（notify、run_script、stop_all）**組出 `"triggers"` 清單。
  - 驗證交由 `rule_from_dict`（至少一動作、各欄位）。
- **UI**：移除單一 `trigger_combo`；改為
  ```
  觸發動作：
    [ ] 顯示通知      訊息：[__________]
    [ ] 全部停止
    [ ] 執行腳本      [腳本名稱 ▼]
  ```
  勾選框對應旗標；訊息欄／腳本下拉沿用既有 `message_edit`／`script_edit`。

## 6. 其他接線

- `app/watch_controller.py`：`on_fire` 回呼參數已是字串（`ttype`），引擎改傳組合字串即可，watch_controller 不需改。
- 觸發動作內容（通知走 GUI＋Discord 扇出、stop_all 停執行中腳本）皆沿用既有機制，不改。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `models` | 新 `triggers` 清單 round-trip；舊單物件 `"trigger"` 遷移為一元素清單；空 `triggers` 拒絕；notify 缺 message／run_script 缺 script_name 拒絕 |
| `rule_engine` | 多動作依序執行：`triggers=[notify, stop_all]` 觸發時 notifier 被呼叫 **且** stop_event 被 set／on_stop_all 被呼叫；`run_script` 動作照舊 |
| `rule_editor_model` | 勾選旗標 → `to_dict` 產生對的 `triggers`（固定順序）；`from_rule` 由 triggers 還原旗標 |
| `rule_editor` | 三個勾選框存在；勾「通知+停止」存檔 → 規則 `triggers` 含兩者；載入既有規則顯示對應勾選；未勾任何 → 存檔失敗提示 |

既有以 `rule_from_dict({… "trigger": {…}})` 建規則的測試因遷移仍可用；存取 `rule.trigger` 屬性或斷言 `rule_to_dict` 舊格式的測試須改為 `triggers`。

## 8. 非目標（YAGNI）

- 動作可拖曳排序（固定順序即可）。
- 同種動作重複多次（一種各一，勾選框天然去重）。
- 新增動作種類（播放音效等），未來要時再加。
- 條件式動作（if…then 多分支），超出範圍。
