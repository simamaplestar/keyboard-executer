# 全入口 OCR 遷移報告（2026-10-03）

## 結論與已知限制

所有正式 OCR 入口已改用 PP-OCRv6 tiny／ONNX Runtime，舊引擎、宣告依賴及模型已從
程式和新版包移除。**這不代表辨識準確率或完整遊戲流程已通過驗收。**

兩張使用者提供的離線圖片，原始碼與最終 EXE 的直接／子程序路徑結果一致：

| 圖片 | 原始辨識 | 結果 |
|---|---|---|
| 246×59 文字裁圖 | `请按照號碼順序输入文字。`，0.97013 | 繁簡正規化後 `present` |
| 372×230 舊完整面板圖 | `讀按照號碼顺序輸入文字。`，0.87994 | 最終判定 `unknown`，仍不能觸發 |

第二張是字形錯讀，不是繁簡轉換問題。單次縮放實驗中，1.5 倍有改善，2／3 倍沒有，
所以未加入未經充分驗證的自動縮放重試，也沒有放寬正向觸發白名單。

新增保護：命中提示主體、但開頭「請」錯讀或漏字時，只能判為不確定，不能據此認定
提示消失。仍須完整白名單及每個相關文字框信心值至少 0.8，才會觸發 AI。
完整比對先於不確定性檢查，避免後者耗盡搜尋預算而遮蔽有效完整提示。
**此保護避免錯誤判定消失，不會修好該圖片的漏觸發。**

## 遷移範圍

- Windows／macOS 平台工廠統一建立惰性載入的 `RapidOcrEngine`。
- Player 的文字等待、文字點擊、文字條件，以及規則文字條件都使用此介面。
- 聊天與兩種圖片順序模式共用 `ProcessOcrEngine` 的單一 v6 子程序引擎；移除聊天專用 profile。
- 保留程序取消、關閉與回收路徑，以及單一輸入執行緒、放鍵握手、截止時間和焦點保護。
- 手動提示和單框提示使用 OpenCC t2s 比較繁體／簡體／混寫；不改寫原始 OCR、姓名、一般文字或正則。
- 設定頁顯示固定自動模型；舊設定中的 OCR 語言值仍保留，但不再切換模型。
- 移除 `ocr_paddle.py`、舊模型包與 Paddle／PaddleOCR／PaddleX 的依賴及打包 hooks。
- 明列 `psutil` 依賴，保留快速視窗程序名稱查詢；OpenCV 宣告統一為 `opencv-python`。
- 模型初始化／缺檔／校驗錯誤仍明確失敗；一般 Player 文字動作保留暫時推論錯誤視為未命中的舊行為。
  聊天／圖片程序不把推論錯誤偽裝成有效空白辨識。

模型維持既有 `models/chat-ocr-v6-tiny` 使用者快取路徑，凍結包改用 `ocr_models/`。
初始化所需的分類模型仍在包內，方向分類推論關閉。使用者腳本、設定、舊模型快取及
舊 exe 備份均未刪除；既有建置 venv 的舊套件也未做破壞性卸載。

## 驗證

- 最終 Windows 全套：**1910 passed、4 skipped、2 個既有 Qt deprecation warnings**。
- 全入口接線、取消／回收、繁簡比較、UI 舊設定保存、離線模型與打包排除測試。
- 獨立 review 的暫時推論錯誤相容性、直接依賴，以及完整提示優先權問題皆已修正並驗證。
- RED→GREEN 證明首字錯讀不能當消失；有效完整提示不受不確定性搜尋預算影響。
- 130 個 runtime／建置輸入檔案的建置前後 SHA256 一致。
- EXE archive 含必要功能模組、三個 ONNX 模型、OpenCC 設定／字典；不含舊模組、舊權重及 Paddle runtime。
- 用發布 exe 的 multiprocessing 入口執行真實 OCR，將 Python 搜尋路徑限制在凍結包；
  確認 RapidOCR、ONNX 原生模組、OpenCC、OpenCV 與應用 OCR 模組均來自 `_MEIPASS`，不是建置 venv。
  直接與子程序辨識皆使用包內模型；模型 SHA256 正確，沒有載入 Paddle。
- `--help` exit 0；隔離資料目錄的 GUI 可回應並正常關閉，exit 0。
- 未執行真實遊戲輸入、AI／Discord 線上驗收；macOS 新依賴組合未實機驗證。

曾有一個新增測試使用非法空 `if_text.then`；已修正並重新證明真正的推論錯誤回歸，
不把原本的設定驗證失敗算作該回歸的 RED 證據。

## 發布

- 正式路徑：`D:\keyboard-executor\packaging\dist\KeyboardExecutor.exe`
- 同版獨立產物：`D:\keyboard-executor\packaging\dist\unified-ocr\KeyboardExecutor.exe`
- 大小：134,559,333 bytes。
- SHA256：`4e65f333ece7af442db88c3889bd15a5d931a0a003ac8ef8f7ea18bff449e294`
- 原版備份：`packaging/dist/KeyboardExecutor.before-unified-ocr-20261003-011911.exe`
- 首字保護更新前備份：`packaging/dist/KeyboardExecutor.before-ocr-prompt-guard-20261003-013824.exe`

原路徑已替換並校驗雜湊；未強制關閉任何使用者程式。
本次直接修改既有 `main`，保留並行變更及 `.git/index.lock`，沒有建立分支或 commit／push。

## 證據位置

- `/tmp/ke-unified-ocr-windows-tests-safe-final.log`
- `/tmp/ke-unified-ocr-windows-build-safe-final.log`
- `/tmp/ke-unified-ocr-source-manifest-final.json`
- `/tmp/ke-unified-ocr-review-corrected-red-green.log`
- `/tmp/ke-unified-ocr-uncertain-red.log`、`/tmp/ke-unified-ocr-priority-red.log`
- `/tmp/ke-unified-ocr-real-safe-final.log`
- `/tmp/ke-unified-ocr-frozen-probe-safe-final.log`
- `/tmp/ke-unified-ocr-package-smoke-safe-final.log`
- `/tmp/ke-unified-ocr-publish-final.json`
- Windows Temp 下 `ke-unified-ocr-real.json`、`ke-unified-ocr-frozen-probe.json`、`ke-unified-ocr-package-smoke.json`
