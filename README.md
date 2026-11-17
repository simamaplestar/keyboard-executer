# Keyboard Executor

Windows 與 macOS 的鍵盤、滑鼠自動化工具。可以錄製操作、編輯腳本並對指定視窗回放，也能透過 OCR、圖像比對與 AI，依畫面內容執行不同動作。

[快速開始](#快速開始) · [平台支援](#平台支援) · [AI 功能](#ai-功能) · [使用指南](docs/usage-guide.md) · [打包說明](packaging/README.md)

## 主要功能

| 功能 | 用途 |
| --- | --- |
| 錄製與回放 | 記錄鍵盤、滑鼠操作，支援速度調整、重複執行與視窗相對座標。 |
| 腳本編輯 | 編排按鍵、組合鍵、文字、滑鼠、延遲、巢狀迴圈與子腳本。 |
| 畫面辨識 | 等待文字或圖片出現、依辨識結果分支，或點擊找到的位置。 |
| 監看規則 | 定期檢查指定區域，符合條件時執行腳本、停止操作或發送通知。 |
| AI 助手 | 透過對話與圖片產生、修改腳本及規則，預覽後再套用。 |
| AI 進階操作 | 示範錄製、聊天自動回覆與圖片順序輸入。 |
| 匯入與匯出 | 將腳本、規則及相依模板整合為一個 JSON 檔，方便備份與分享。 |
| 自動更新 | Windows 打包版可檢查新版、下載並驗證 SHA-256，再於閒置時確認安裝。 |

回放期間可按 **F10** 緊急停止，也可將滑鼠移到螢幕左上角；CLI 另支援 **Ctrl+C**。

## 快速開始

已發布的安裝包可在 [Releases](https://github.com/simamaplestar/keyboard-executer/releases) 查找。若尚無適用版本，可依下列步驟從原始碼執行；自行產生 EXE 或 Mac App 的方式請見[打包說明](packaging/README.md)。

### 從原始碼啟動

先安裝 Git 與 Python 3.11 以上版本，再下載專案：

```bash
git clone https://github.com/simamaplestar/keyboard-executer.git
cd keyboard-executer
```

**Windows（PowerShell）**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe packaging\prepare_chat_ocr_models.py
.\.venv\Scripts\python.exe -m keyboard_executor.gui
```

**macOS（Apple Silicon）**

使用原生 arm64 Python，先確認系統符合需求：

```bash
python3 packaging/macos_support.py
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python packaging/prepare_chat_ocr_models.py
python -m keyboard_executor.gui
```

模型準備指令會下載並驗證離線 OCR 模型，完成後辨識在本機執行。打包版已包含模型。Mac 首次啟動另需完成下方的[權限設定](#mac-權限設定)。

### 建立第一個腳本

1. 開啟 GUI，建立腳本並選擇目標視窗。
2. 加入按鍵、滑鼠或延遲動作；也可以使用錄製功能，按 **F9** 開始與結束錄製，按 **F10** 放棄錄製。
3. 儲存後執行腳本，確認目標視窗與動作結果。
4. 需要依畫面判斷時，再加入文字、圖片條件或監看規則。

座標以目標視窗左上角為原點。更換電腦、畫面縮放或目標程式後，請重新核對視窗與框選區域。腳本範例、按鍵名稱及模板操作見[使用指南](docs/usage-guide.md)。

## 平台支援

| 平台 | 需求與使用方式 |
| --- | --- |
| Windows | 可從原始碼或 EXE 執行；提供四種鍵盤輸入模式，打包版支援自動更新。 |
| macOS | Apple Silicon（M 系列）、macOS 14 以上、原生 arm64 Python；提供標準輸入模式，可自行打包為 `.app`。 |

Mac 版已有相容處理與打包流程，原生 Mac 的錄製、回放、權限及 OCR 仍需依 [Mac 驗收表](docs/macos-manual-checklist.md) 實機確認。目前不支援 Intel Mac、Rosetta 或 Linux。

### Mac 權限設定

在「系統設定 → 隱私權與安全性」開啟以下權限，GUI 也會顯示引導：

| 權限 | 用途 |
| --- | --- |
| 輔助使用 | 模擬鍵盤與滑鼠輸入。 |
| 輸入監控 | 錄製操作與接收全域熱鍵。 |
| 螢幕錄製 | 截圖、OCR 與圖像比對。 |

原始碼執行時授權啟動程式的終端機；打包版授權 Keyboard Executor。視窗操作若要求控制「系統事件」，也需允許。授權完成後，完整結束程式再重新開啟。

F9／F10 若被系統功能占用，可搭配 **Fn**，或將 F1、F2 等按鍵設為標準功能鍵。

### Windows 腳本移到 Mac

Windows 專用鍵盤模式會改用 Mac 標準輸入，儲存後清除原模式。`insert`、`numlock` 等不支援的系統鍵會明確報錯，需要調整腳本。Windows 四種模式的差異見[鍵盤輸入模式](docs/usage-guide.md#windows-鍵盤輸入模式)。

## AI 功能

AI 是可選功能，先在設定頁選擇認證方式：

| 方式 | 支援來源 |
| --- | --- |
| API 金鑰 | Anthropic、OpenAI、OpenRouter；API 用量與訂閱分開計費。 |
| 訂閱登入 | ChatGPT 透過本機 Codex，Claude 透過本機 Claude Code 或 `setup-token`。 |

訂閱模式需先安裝對應的官方工具。安裝方式、模型選擇與憑證保存見 [AI 助手設定](docs/usage-guide.md#ai-助手設定)。

| 功能 | 從哪裡開始 |
| --- | --- |
| 示範錄製 | AI 助手面板的「示範錄製」，框選小地圖並示範操作，再試跑產生的腳本。 |
| 聊天自動回覆 | 腳本編輯器的「AI 自動回覆」，指定角色名稱、聊天區域與要回覆的頻道。 |
| 圖片順序輸入 | 腳本編輯器的「圖片順序輸入」，框選完整面板並啟用監看。 |

聊天自動回覆與圖片順序輸入需使用支援圖片的模型，並從 GUI 執行主腳本。設定步驟、辨識限制與停止條件分別見[聊天自動回覆](docs/usage-guide.md#聊天自動回覆)與[圖片順序輸入](docs/usage-guide.md#圖片順序輸入)。

## CLI 使用方式

在已安裝專案的 Python 環境中執行；Windows 可將 `python` 換成 `.\.venv\Scripts\python.exe`：

```bash
python -m keyboard_executor.cli list
python -m keyboard_executor.cli play <腳本名稱>
python -m keyboard_executor.cli record
python -m keyboard_executor.cli watch
python -m keyboard_executor.cli --version
```

安裝後也可使用 `keyboard-executor`（CLI）與 `keyboard-executor-gui`（GUI）兩個入口。需要指定資料目錄時，可使用 `--dir`，例如 `keyboard-executor list --dir <資料目錄>`。

## 資料與更新

預設資料目錄為 `~/.keyboard-executor/scripts/`，包含腳本 JSON、`rules/`、`templates/`、`logs/` 與 `settings.json`。聊天紀錄保存在同一資料目錄的 `.chat-history/`。

分享腳本時可使用 GUI 的「匯出／匯入」功能，相依模板與子腳本會一併處理。匯出不含 `settings.json` 與 AI 認證；遇到同名項目會先詢問。詳見[匯出與匯入](docs/usage-guide.md#匯出與匯入)。

Windows 打包版啟動後及每六小時檢查新版，設定頁可手動檢查或關閉自動更新；Mac 版以手動替換 App 更新。發布來源統一為 [simamaplestar/keyboard-executer](https://github.com/simamaplestar/keyboard-executer/releases)。

## 開發與文件

使用已安裝 `dev` 依賴的環境執行測試：

```bash
python -m pytest -q
```

| 文件 | 內容 |
| --- | --- |
| [使用指南](docs/usage-guide.md) | 腳本格式、按鍵、錄製、模板、AI 與進階操作。 |
| [打包與發布](packaging/README.md) | Windows EXE、Mac App、離線模型、簽章與發布流程。 |
| [Mac 驗收表](docs/macos-manual-checklist.md) | Mac 權限、錄製回放、Retina 與多螢幕檢查。 |
| [圖片順序輸入驗收表](docs/sequence-input-manual-checklist.md) | 圖片流程的實機操作與驗收項目。 |
| [OCR 遷移報告](docs/unified-ocr-migration-report.md) | 離線辨識結果與發布驗證。 |
| [架構與套件](docs/usage-guide.md#開發參考) | 專案目錄分工與主要依賴。 |
| [設計與實作紀錄](docs/superpowers/) | 各功能的設計、計畫與審查紀錄。 |

工具使用作業系統標準輸入介面，能否接收模擬輸入仍取決於目標程式。反偵測、反外掛繞過、背景視窗輸入、遠端控制與雲端同步不在功能範圍內。
