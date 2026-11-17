# Keyboard Executor — 設計文件

- **日期**：2026-07-06
- **狀態**：已與需求方確認設計方向，待審閱
- **平台**：Windows 10/11、macOS 13+

## 1. 概述

Keyboard Executor 是一個跨平台桌面自動化工具，提供：

1. 模擬鍵盤與滑鼠動作
2. 錄製鍵盤與滑鼠動作（全域熱鍵控制）
3. 對指定視窗執行錄製或手動編輯的動作腳本
4. 定時截圖，以 OCR 與圖像模板比對判斷畫面內容，驅動規則觸發與腳本內流程控制
5. Windows 與 macOS 皆可運作

**使用情境**：通用自動化工具（類 AutoHotkey）、辦公重複性作業、遊戲輔助/掛機。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 視窗控制模式 | 自動將目標視窗切到前景再執行（不做背景視窗注入） |
| 介面形式 | 桌面 GUI 應用程式 |
| 技術棧 | Python 3.11+ / PySide6 |
| OCR 用途 | 獨立監看規則引擎 + 腳本內流程控制 |
| 圖像模板比對 | v1 就納入（遊戲美術字 OCR 不可靠） |
| 反偵測/反外掛繞過 | 明確不做。標準 API 輸入被目標程式阻擋時如實回報 |

## 3. 技術棧

| 能力 | 套件 |
|------|------|
| GUI | PySide6 |
| 輸入模擬 | pynput；Windows 遊戲補充 pydirectinput（SendInput scan codes） |
| 全域輸入監聽（錄製/熱鍵） | pynput |
| 視窗控制 | pywinctl（必要時直呼 win32gui / Quartz） |
| 螢幕截圖 | mss |
| OCR | Windows：Windows.Media.Ocr（winsdk）；macOS：Apple Vision（pyobjc） |
| 圖像模板比對 | opencv-python-headless + numpy |
| 打包 | PyInstaller |
| 測試 | pytest |

## 4. 架構

三層架構，平台差異全部隔離在 `platforms/` 層：

```
keyboard-executor/
├── src/keyboard_executor/
│   ├── app/                  # GUI 層（PySide6）
│   │   ├── main_window.py    #   主視窗：腳本清單、執行控制、即時日誌
│   │   ├── recorder_panel.py #   錄製控制面板
│   │   ├── script_editor.py  #   腳本步驟編輯器（表格式增刪改）
│   │   ├── rule_editor.py    #   監看規則編輯器
│   │   └── region_picker.py  #   螢幕區域框選覆蓋層（兼模板擷取工具）
│   ├── core/                 # 核心邏輯層（純 Python，不碰平台 API）
│   │   ├── models.py         #   Script / Action / Rule 資料模型
│   │   ├── recorder.py       #   錄製引擎（原始事件 → Action 序列）
│   │   ├── player.py         #   回放引擎（狀態機，於 QThread 執行）
│   │   ├── rule_engine.py    #   監看規則引擎（比對 → 觸發）
│   │   ├── watcher.py        #   定時截圖排程器
│   │   └── vision.py         #   OCR 結果模型 + OpenCV 模板比對（跨平台純演算法）
│   ├── platforms/            # 平台抽象層（唯一允許判斷 OS 的地方）
│   │   ├── base.py           #   抽象介面定義
│   │   ├── win32/            #   Windows 實作
│   │   └── darwin/           #   macOS 實作（含 permissions.py 權限檢查）
│   ├── storage/              # 腳本 / 規則 / 模板圖檔的檔案存取
│   └── main.py               # 進入點
└── tests/                    # pytest；core 層注入 fake 平台實作
```

### 平台抽象介面（platforms/base.py）

| 介面 | 職責 | Windows 實作 | macOS 實作 |
|------|------|-------------|-----------|
| `InputBackend` | 模擬鍵盤滑鼠事件 | pynput；遊戲模式用 pydirectinput | pynput（CGEvent） |
| `InputHook` | 全域監聽（錄製與熱鍵） | pynput listener | pynput listener（需輸入監控權限） |
| `WindowManager` | 尋找 / 啟用 / 查詢視窗幾何 | pywinctl + win32gui | pywinctl + Quartz |
| `ScreenCapture` | 擷取視窗或區域影像 | mss | mss（需螢幕錄製權限） |
| `OcrEngine` | 影像 → 文字 + 座標框 | Windows.Media.Ocr | Apple Vision |

模板比對不在此層：OpenCV 對截圖矩陣運算無平台差異，實作於 `core/vision.py`。

## 5. 資料模型

腳本以 JSON 儲存於使用者資料目錄；規則存於同目錄的 `rules/` 子目錄；模板圖檔（PNG）存於 `templates/` 子目錄；GUI 設定存於同目錄的 `settings.json`。

### 5.1 Script

```json
{
  "name": "每日簽到",
  "target_window": { "title_pattern": ".*遊戲名稱.*", "app_name": null },
  "settings": {
    "speed": 1.0,
    "repeat": 1,
    "humanize_jitter_pct": 0,
    "game_input_mode": false
  },
  "actions": [ ... ]
}
```

- `target_window`：以標題 regex 或應用程式名稱擇一指定
- `speed`：延遲倍率；`repeat`：整體重複次數（-1 = 無限）
- `humanize_jitter_pct`：每個延遲加上 ± 百分比的隨機抖動
- `game_input_mode`（僅 Windows 有效）：改用 pydirectinput scan code 輸入

### 5.2 Action 類型

| 分類 | 類型 | 主要欄位 |
|------|------|---------|
| 輸入 | `key_press` | key, hold_ms |
| 輸入 | `key_combo` | keys（如 ctrl+shift+s） |
| 輸入 | `text_input` | text |
| 輸入 | `mouse_move` | x, y（視窗相對座標） |
| 輸入 | `mouse_click` | x, y, button, count |
| 輸入 | `mouse_drag` | from, to, button |
| 輸入 | `scroll` | x, y, dx, dy |
| 時間 | `delay` | ms 或 [min_ms, max_ms] 隨機區間 |
| 流程 | `wait_text` | region, pattern, mode(contains/regex), timeout_ms, on_timeout(abort/continue/goto), goto_index |
| 流程 | `wait_image` | region, template, threshold(預設 0.85), timeout_ms, on_timeout, goto_index |
| 流程 | `if_text` / `if_image` | region, pattern/template, then:[Action], else:[Action] |
| 流程 | `loop` | count(-1=無限), actions:[Action] |
| 流程 | `run_script` | script_name |
| 視覺互動 | `click_text` | region, pattern —— OCR 找到文字後點擊其中心 |
| 視覺互動 | `click_image` | region, template, threshold —— 比對命中後點擊其中心 |

**座標系統**：所有座標一律為「目標視窗左上角為原點」的相對座標。錄製時由絕對座標自動換算；回放時再依當下視窗位置換算回絕對座標。視窗移動後腳本仍可用。`region` 同樣以視窗相對座標表示，`null` 代表整個視窗。

### 5.3 Rule（獨立監看規則）

```json
{
  "name": "斷線自動重連",
  "target_window": { "title_pattern": ".*遊戲名稱.*" },
  "region": null,
  "condition": { "type": "text", "pattern": "連線中斷", "mode": "contains" },
  "interval_sec": 5,
  "cooldown_sec": 60,
  "trigger": { "type": "run_script", "script_name": "重連流程" },
  "enabled": true
}
```

- `condition.type`：`text`（contains/regex）或 `image`（template + threshold）
- `trigger.type`：`run_script` / `stop_all` / `notify`（系統通知）
- `cooldown_sec`：觸發後的冷卻時間，避免同一畫面連續觸發

## 6. 錄製設計

- **控制方式**：全域熱鍵（預設 `F9` 開始/停止，可於設定變更），GUI 面板亦有按鈕
- **錄製流程**：開始前先點選目標視窗（或從清單挑選）→ 錄製期間 `InputHook` 收集事件 + 時間戳 → 停止後轉換為 Action 序列，座標換算為視窗相對座標，事件間隔轉為 `delay` 動作
- **滑鼠軌跡**：預設「簡化模式」——只保留點擊、拖曳起迄、捲動等關鍵事件；可切換「完整軌跡模式」保留移動路徑（以取樣間隔抽稀）
- **自我過濾**：錄製控制熱鍵本身不會被錄進腳本

## 7. 回放設計

- **前置**：以 `WindowManager` 尋找目標視窗 → 不存在時依設定重試 N 次或中止 → `activate()` 拉到前景 → 確認取得焦點後才開始
- **執行**：`player.py` 為狀態機，逐 Action 執行；於 QThread 執行，GUI 保持可操作並即時顯示目前步驟與日誌
- **緊急停止（雙保險）**：
  1. 全域熱鍵 `F10`（可自訂）立即停止所有腳本與監看
  2. Failsafe：使用者手動將滑鼠甩到螢幕左上角即中斷
- **執行期防護**：每次視覺類動作前重新查詢視窗位置；偵測到目標視窗關閉或消失時安全中止

## 8. 視覺辨識與規則引擎

### 8.1 擷取與辨識管線

```
watcher（每規則各自間隔計時）
  → ScreenCapture 擷取目標視窗/區域（mss）
  → 依 condition.type 分流：
      text  → OcrEngine（原生引擎）→ [文字 + bounding box]
      image → core/vision.py matchTemplate → [命中位置 + 信心值]
  → rule_engine 比對 → 命中且不在冷卻期 → 執行 trigger
```

腳本內的 `wait_*` / `if_*` / `click_*` 動作重用同一條管線，由 player 直接呼叫。

### 8.2 模板比對細節

- OpenCV `matchTemplate`（`TM_CCOEFF_NORMED`），閾值預設 0.85，逐動作可調
- 模板由 GUI 區域框選器擷取：框選 → 預覽 → 命名存檔（PNG，存於腳本目錄 `templates/`）
- 灰階比對為預設（對亮度變化較穩健），可選彩色
- 多尺度搜尋（0.8x–1.2x）作為進階選項，預設關閉（效能考量）

### 8.3 OCR 引擎

- 平台原生引擎：中文辨識品質佳、無額外模型下載、離線可用
- `OcrEngine.recognize(image) -> list[TextBox(text, x, y, w, h, confidence)]`
- 語言依系統語言自動選擇，可於設定指定

## 9. GUI 設計

| 畫面 | 內容 |
|------|------|
| 主視窗 | 左側：腳本清單 + 規則清單（可啟用/停用）；右側：所選項目摘要 + 執行控制；下方：即時日誌面板 |
| 錄製面板 | 目標視窗選擇（下拉 + 重新整理）、軌跡模式切換、開始/停止、錄後預覽 |
| 腳本編輯器 | 表格式步驟清單，支援增/刪/改/排序/複製，各 Action 類型有對應編輯表單 |
| 規則編輯器 | 條件（文字/圖像）、區域選取、間隔、冷卻、觸發設定 |
| 區域框選器 | 半透明全螢幕覆蓋層拖曳框選；兼作模板擷取（框選後裁圖存檔） |
| 設定頁 | 熱鍵自訂、OCR 語言、日誌等級、macOS 權限狀態顯示 |

## 10. 錯誤處理

| 情境 | 處理 |
|------|------|
| 找不到目標視窗 | 依腳本設定：重試 N 次（間隔可設）→ 中止並記錄 |
| `wait_text` / `wait_image` 逾時 | 依 `on_timeout`：abort / continue / goto（跳至 `goto_index` 指定的同層步驟索引，0 起算） |
| 執行中視窗被關閉 | 偵測後安全中止，絕不對其他視窗送輸入 |
| macOS 權限缺失 | 啟動時檢查「輔助使用、螢幕錄製、輸入監控」，缺少時顯示引導畫面（附直達系統設定的連結） |
| OCR / 截圖失敗 | 記錄並依規則跳過該輪；連續失敗 N 次發通知 |
| 腳本 JSON 損壞 | 載入時 schema 驗證，報錯不崩潰 |

所有事件寫入 GUI 日誌面板與滾動日誌檔。

## 11. 範圍界線

- 不實作任何反偵測、反外掛繞過、驅動層注入。輸入一律走作業系統標準 API（SendInput / CGEvent），被目標程式阻擋時如實回報
- 不做背景視窗注入（PostMessage 類），v1 僅前景模式
- 不做網路功能（遠端控制、雲端同步）

## 12. 測試策略

- **core 層**：pytest 單元測試。`InputBackend` / `OcrEngine` / `ScreenCapture` / `WindowManager` 以 fake 實作注入，回放狀態機、座標換算、規則比對、模板比對（用固定測試圖）皆可自動化驗證
- **platforms 層**：兩平台手動 smoke 測試清單（錄製→回放→OCR→模板→規則觸發 端到端）
- **CI**：core 層測試可在無頭環境跑；platforms 層不進 CI

## 13. 里程碑

| 階段 | 交付物 | 驗收標準 |
|------|--------|---------|
| M1 | 平台抽象層 + 輸入模擬 + 視窗控制 | 以 Python 程式碼對指定視窗執行一段寫死的動作序列（兩平台） |
| M2 | 錄製引擎 + JSON 腳本 + 回放引擎 | F9 錄一段操作 → 存檔 → 回放成功；流程控制動作（loop/delay）可用 |
| M3 | 截圖 + OCR + 模板比對 + 規則引擎 | wait_text / click_image 可用；獨立規則能定時監看並觸發腳本 |
| M4 | GUI 完整整合 | 全部功能可從 GUI 操作，含區域框選器 |
| M5 | 打包與發布 | PyInstaller 產出兩平台可執行檔；macOS 權限引導完整 |

## 14. 風險

| 風險 | 影響 | 緩解 |
|------|------|------|
| Windows 高 DPI 縮放座標偏移 | 點錯位置 | 進程宣告 Per-Monitor DPI Aware；座標統一用實體像素 |
| macOS 權限（輔助使用/螢幕錄製/輸入監控） | 功能靜默失效 | 啟動時主動檢查 + 引導畫面；打包時正確簽章 |
| 遊戲反外掛阻擋 SendInput | 輸入無效 | 提供 pydirectinput scan code 模式；仍被擋則如實回報（不繞過） |
| 模板比對對解析度敏感 | 換機器/改解析度後失效 | 文件明確告知模板需在執行機器擷取；提供多尺度搜尋選項；mss 10.x 於 macOS 以 nominal-resolution 擷取（`scale_factor()`≈1.0，模板以「點」解析度儲存），換用會回傳實體像素的後端時由 capture 層 ÷scale 換算吸收 |
| OCR 對美術字辨識差 | 規則不觸發 | 已納入模板比對作為替代條件 |
| PyInstaller 打包體積與誤報 | 發布體驗差 | 接受 50–100MB；macOS 簽章、Windows 可考慮自簽 |

## 15. v2 候選擴充（本版不做）

- 背景視窗輸入模式（PostMessage / 事件注入）
- Linux 支援（platforms 層新增 x11/wayland 實作）
- 腳本市集 / 匯入匯出打包格式
- 條件運算式（多條件 AND/OR 組合）
- 排程器（cron 式定時啟動腳本）
