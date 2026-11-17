# 圖片順序輸入：20 秒確認期限（2026-10-03）

## 已實作

兩種圖片順序模式皆從**首次命中提示的畫面擷取時間**共用同一組絕對期限：

- **18 秒前**：收齊編號 1～3、通過提示／安全定位檢查並開始送出。
- **20 秒前**：輸入答案並按一次確認；超時不補送、不重播。
- **30 秒前**：確認後仍需兩次有效提示消失，再恢復腳本。確認不代表已驗證伺服器接受答案。

移除面板 AI 原本 `now + 10` 的單次工作上限。OCR、放鍵等待、多批次 AI 都消耗同一回合預算，
不重新起算。已於18秒前開始輸入時，定位安全觀察可持續至20秒；不因此延後準備期限。
原有前景、幾何、定位不超過2秒、單一輸入執行緒、F10、晚到結果隔離及不重播保護維持。
手動模式的啟動前合成圖片模型檢查仍為原本10秒，與偵測後的回合期限是不同流程。

在輸入步驟、阻塞視窗查詢後、滑鼠定位等待後，以及送出確認前，均檢查20秒截止時間。
清理時仍必須放開已按下的鍵；已進入的原生阻塞呼叫不能強制撤回，因此不是硬即時保證。

設定視窗、監看啟動 INFO 及偵測日誌顯示18／20／30秒政策。沒有新增模型、改動 API
推理參數或延長聊天的期限；沒有呼叫付費 API 進行實測。

## 驗證

- 原始 RED：14 failed、2 passed，重現舊10秒中止、18秒未拒絕、20秒仍確認等差異。
- 新回歸檔案最終：19 passed，含準備／確認／驗證邊界、非零起始時間、放鍵等待、多批次、
  晚到結果、實際輸入後端配 fake native API 的滑鼠等待、確認轉態後跨期限。
- 完整 Windows：**1930 passed、4 skipped、2 個既有 Qt deprecation warnings**，exit 0。
- 獨立 review 未發現 Critical／Important 安全回歸。兩個 Minor 均處理：
  - 測試的假排程器需實際執行排入的狀態通知，不能先對空通知佇列斷言。
  - AI 後視窗查詢跨期限時，保留真正的18秒階段失敗原因，不覆蓋成泛稱AI逾時。
  修正測試後再以備份原始方法做記憶體內替換，重新確認真正的 RED→GREEN；沒有回退工作區。
- 130 個原始碼／建置輸入在完整測試、clean build、產物檢查期間雜湊一致。
- 實際凍結 exe（不是原始碼／venv）執行18／20／30秒狀態與10秒不提前中止的檢查。
- 包內直接／子程序 OCR、三個模型雜湊與來源路徑驗證通過；不含舊 Paddle 引擎／模型。
- `--help` exit 0；隔離資料目錄 GUI 可回應、正常關閉 exit 0。

**未驗證 `gpt-6-luna` 的實際耗時，也不保證它能在20秒內解完。** API、遊戲、DPI、
完整輪播、真實輸入與 Discord 送達仍須實機驗收。先前372×230舊面板的「請→讀」漏辨
仍存在，最終保守判為unknown，不觸發也不當成提示消失；沒有為了速度放寬此保護。

## 產物／發布狀態

- 新版：`D:\keyboard-executor\packaging\dist\sequence-20s\KeyboardExecutor.exe`
- 134,560,003 bytes。
- SHA256：`19e5cc3ec7b3508f9279fa6ef86dd887f68a631cb279383dd1fe3d9bc3edc753`
- **原路徑尚未覆蓋**：檢查時 `dist\KeyboardExecutor.exe` 仍在執行（PID 47576、20256）。
  沒有強制關閉使用者程式；須關閉後才能替換。
- 已備份原 exe：`packaging/dist/KeyboardExecutor.before-sequence-20s-20261003-044308.exe`
- 原路徑／備份 SHA256：`4e65f333ece7af442db88c3889bd15a5d931a0a003ac8ef8f7ea18bff449e294`
- 原始碼備份：`/tmp/ke-before-sequence-20s-3c3wf8ew`。

直接修改既有main，保留並行修改、使用者設定／腳本及index.lock；沒有建立分支、commit或push。

## 證據

- `/tmp/ke-sequence-20s-red.log`
- `/tmp/ke-sequence-20s-review-red.log`
- `/tmp/ke-sequence-20s-corrected-red-green.log`
- `/tmp/ke-sequence-20s-windows-tests-final.log`
- `/tmp/ke-sequence-20s-windows-build.log`
- `/tmp/ke-sequence-20s-source-manifest.json`
- `/tmp/ke-sequence-20s-frozen-probe.log`
- `/tmp/ke-sequence-20s-package-smoke.log`
- `/tmp/ke-sequence-20s-publish.json`
- Windows Temp 下 `ke-sequence-20s-frozen-probe.json`、`ke-sequence-20s-package-smoke.json`
