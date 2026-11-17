# 圖片順序輸入：實作與驗證紀錄

## 20 秒確認期限（2026-10-03，最新）

- 共用首次命中畫面的時間：18秒前準備／20秒前確認／30秒前完成消失驗證；取消面板單次AI固定10秒上限。不保證外部API一定準時完成。
- 最終 Windows：1930 passed、4 skipped；實際凍結包的截止邏輯、OCR與GUI smoke 已驗證。
- 新產物在 `packaging/dist/sequence-20s/KeyboardExecutor.exe`。**原路徑因舊程式仍在執行，尚未覆蓋**；未強制關閉使用者程式，已備份。
- 細節、SHA256、驗證證據與實機限制見 [20秒確認期限報告](sequence-20s-budget-report.md)。

## 全入口 OCR 升級（2026-10-03，先前版本）

- 全入口改為 v6 tiny／ONNX，舊引擎與新包內的舊權重已移除；保留使用者資料及快取。
- 最終 Windows：1910 passed、4 skipped；包內 OCR、模型／來源雜湊和 GUI smoke 已驗證。
- 原 `packaging/dist/KeyboardExecutor.exe` **已替換**，舊版已備份，未強制關閉任何使用者程式。
- **辨識限制仍在**：較新的文字裁圖可觸發；舊 372×230 面板圖的「請」被讀成「讀」，只能判為不確定，不會觸發，也不能當作提示消失。
- 最新產物、SHA256、完整證據與限制見 [全入口 OCR 遷移報告](unified-ocr-migration-report.md)。以下內容保留為歷史紀錄，不代表目前原路徑仍未更新。

## 立即暫停升級（2026-10-02，歷史）

- 直接在原 `main` 開發，來源備份 `/tmp/ke-before-immediate-pause-iiCnsU`；既有修改與 index.lock 保留，未提交或推送。
- OCR 命中後立即要求中途暫停，唯一輸入執行緒先釋放長按／組合鍵，再以同回合 acknowledgment 允許 AI；Discord 仍在 OCR 命中時並行啟動。
- 長按／等待接續剩餘時間，暫停耗時不扣 action 預算，但不改動 watcher 的25／30秒絕對期限。文字／點擊進度不重播，短點按不再按一次，已開始的拖曳放開後解題並停止。
- 新增監看啟動 INFO（區域及 Discord 設定狀態，不含 URL）。未启用／已停止不誤報；前景視窗保護不放寬。
- 獨立唯讀 gpt-6-astra 審查的三項 Important 均已重現並 RED→GREEN：恢復時跨越 deadline、尚未產生效果的條件分支失效、組合鍵各键之間檢查暫停。另補恢復日誌回呼後取消的回歸，避免先復按再被日誌阻塞。
- Windows 完整測試：**1754 passed、4 skipped、2 則既有 Qt 警告**，`/tmp/ke-pause-windows-tests-final.log`（exit 0）。未以此宣稱 Linux 全套或真實遊戲驗收完成。
- 真實離線 OCR：使用者提供的 372×230 PNG 辨識到「請按照號碼順序輸入文字」，信心值 **0.9810178**、分類 present；首次含模型初始化約10.1秒。無 AI、Discord 或原生輸入。使用者確認測試時由另一個看圖視窗佔前景，因此會被現行前景檢查跳過。
- **已完成 clean build 與成品檢查**：`D:\keyboard-executor\packaging\dist\immediate-pause\KeyboardExecutor.exe`，264,698,925 bytes；SHA256 `5abf861b5de7484fbbd3f551d2902c0b2cce8c4b5ab76f7d0f1e6e36d3cfe7fc`。建置前後128個來源／建置檔雜湊一致。
- 已檢查8個相關模組、2個 OCR 模型權重，以及包內啟動 INFO／恢復期限檢查；`--help` exit 0，獨立空資料目錄 GUI 可回應、正常關閉 exit 0。Linux 最後聚焦回歸333 passed。
- **原路徑尚未覆蓋**：Windows 拒絕替換正在執行的 `packaging/dist/KeyboardExecutor.exe`，已確認該路徑的舊版仍開著；沒有強制終止使用者程式。舊版備份 `packaging/dist/KeyboardExecutor.before-immediate-pause-20261002-071830.exe`。需先關閉舊版，才能將已驗證的成品替換至原路徑。
- 證據：`/tmp/ke-pause-windows-build.log`、`/tmp/ke-pause-package-smoke.log`、`/tmp/ke-pause-package-source-manifest.json`、`/tmp/ke-pause-final-focused.log`。下列 exe 雜湊為歷史版本。

## 單一框選升級（2026-10-01，歷史版本）

- 直接在原專案 `main` 開發，保留既有及同期的其他修改，未新增分支、未提交或推送。
- 新模式只框選完整面板；本機 OCR 命中提示才送 AI，自動辨識編號／字元與輸入框／確認按鈕。啟動及等待期間不做此功能的 AI 請求。
- OCR 命中同時啟動 Discord 文字通知，沿用現有 Webhook，每回合至多一次；背景傳輸、5 秒逾時、不重試，不阻塞 AI 或原本 30 秒時限。
- 保留舊手動模式、匯入匯出、CLI 防呆、共享 OCR、聊天優先權與 F10 行為。取消框選不轉換舊設定。
- 獨立唯讀審查已執行（gpt-6-astra）；三項 Important 均已重現並完成 RED→GREEN：固定提交點對抗漸進漂移、OS 視窗查詢後重驗回合、圖片編碼後送 AI 前重驗取消。無被擱置的 Minor。
- 修正後 Windows 完整測試：**1721 passed、4 skipped、2 則既有 Qt 警告**（`/tmp/ke-sequence-panel-windows-tests-final.log`）；本功能與舊流程的 Linux 聚焦回歸：**206 passed**（`/tmp/panel-final-focused.log`）。未執行本輪 Linux 完整套件，不以此消除先前 Linux pynput 平台限制。
- 開工備份：`/tmp/ke-before-panel-59q8_g53`；過程紀錄：`.superpowers/sdd/2026-10-01-sequence-single-region/progress.md`。既有 `.git/index.lock` 未移除。
- **已依使用者要求於 2026-10-02 重新打包**：`D:\keyboard-executor\packaging\dist\KeyboardExecutor.exe`，264,685,463 bytes；SHA256：`744b8e97771657c0b3b18dd4bc458fcacea54a02ed6787cc58c9707dc5346dd3`。
- 舊版備份：`packaging/dist/KeyboardExecutor.before-panel-20261002-024147.exe`。建置前後 127 個原始碼／建置檔雜湊一致，正式檔與驗證用成品雜湊一致。
- 已直接檢查 exe 內嵌 archive：7 個單一面板功能模組與 2 個 OCR 模型權重皆存在。`--help` exit 0；以獨立空資料目錄啟動，主視窗回應正常，正常關閉 exit 0。
- 打包日誌：`/tmp/ke-panel-windows-build.log`；啟動檢查：`/tmp/ke-panel-package-smoke.log`。下方前一輪 exe 雜湊僅為歷史紀錄。
- 真實 OCR 命中率、AI 定位／延遲、Discord 實際送達與 Windows 目標程式操作仍待 `docs/sequence-input-manual-checklist.md` 驗收；未呼叫真實服務或操作目標程式冒充實測。

## 前一輪交付位置（2026-10-01）

- 已依使用者要求直接整合至 `/mnt/d/keyboard-executor`（`D:\keyboard-executor`），維持 `main`，此次整合未新增分支。
- 以 `fc3d074..7b7ffcb` 功能差異套用，保留原有未提交修改；未建立 merge commit、未推送。
- 新版執行檔：`D:\keyboard-executor\packaging\dist\KeyboardExecutor.exe`。
- 舊版備份：`packaging/dist/KeyboardExecutor.before-sequence-20261001-190753.exe`。
- 先前隔離開發工作區與功能分支仍保留。基線 `fc3d074` 是原有未提交修改的安全快照。

## 已實作

GUI「圖片順序輸入」設定、框選及取點；每秒取樣、提示OCR、AI字元／編號辨識、依1→2→3輸入、確認只點一次。從觸發影像擷取起共用30秒，25秒前未能開始輸入即停止。背景工作與輸入權分離，OCR／AI晚到結果無法補送。

支援聊天優先權交接、腳本進度保留、F10取消、匯出入及CLI防呆。若聊天已打到一半被提示中斷，解完後仍停止，保留現場讓人確認焦點。

## 隔離工作區驗證（Linux 歷史紀錄）

- 基線全套：1402 passed、14 skipped、2 failed。
- 最終全套：**1485 passed、14 skipped、同樣2項既有失敗**，另有2則既有Qt deprecated警告。
- 新增的獨立審查安全回歸：10 passed。
- `git diff --check` 通過。
- 測試環境：Linux／Python 3.14.7，`PYTHONPATH=src QT_QPA_PLATFORM=offscreen /tmp/ke-sequence-venv/bin/python -m pytest -q`。

既有失敗（pynput在此Linux環境不接受Windows `_scan` 參數）：
1. `tests/platforms/test_hook_pynput.py::test_numpad_bypasses_canonical_and_keeps_its_identity`
2. `tests/platforms/test_hook_pynput.py::test_main_row_digit_still_records_as_plain_digit`

此階段因未達全套綠燈，曾暫停整合。後續依使用者要求直接整合，Windows 驗證結果如下。

## Windows 整合與打包驗證

- 環境：Windows／Python 3.13.7／PyInstaller 6.21.0。
- 修正新增匯出測試的 `Path.read_text(encoding="utf-8")`，避免 Windows CP950 誤讀 UTF-8 JSON；產品匯出邏輯不變。
- 原專案完整 `pytest -q`：**1497 passed、4 skipped、2 則 Qt deprecated 警告**。上述兩項 pynput 測試在 Windows 通過。
- 以既有 `packaging/keyboard-executor.spec` clean build 成功；確認新功能八個模組列入 PYZ。
- 打包 exe 的 `--help` exit code 0；另以獨立暫存資料目錄啟動 GUI，確認 `Keyboard Executor` 視窗可回應，正常關閉且 exit code 0。
- 正式 exe：264,649,653 bytes；SHA256：`4adceec5555031d6c0794f6a8207aabc17a5b5b1e9541c6e6ffa4da9808e68df`。替換前備份舊版，並核對新舊複本雜湊。
- 測試日誌：`/tmp/ke-sequence-windows-tests-final.log`；打包日誌：`/tmp/ke-sequence-windows-build.log`。
- 真實目標程式、PaddleOCR 辨識、AI 延遲、DPI／IME、F10 與實際 30 秒完成率仍須依 `docs/sequence-input-manual-checklist.md` 驗收。GUI 啟動成功不代表這些流程已驗收。

## 獨立審查與修正

以gpt-6-astra做一次獨立、唯讀全分支審查，再執行一次修正流程。已重現並用測試修正：
- OCR完成後重新驗證焦點與幾何；接續腳本前再次確認。
- 填字途中偵測到提示消失，撤銷剩餘字元及確認。
- 真實輸入後端在滑鼠移動等待後重新檢查截止／F10，才送click。
- 啟用優先監看時，聊天不再呼叫不可取消的視窗啟用／強制前景操作。
- 提示文字經正規化後不能是空字串，拒絕只有標點的設定。

## 執行裁定（依記錄順序）

1. 使用隔離快照作基線，而不是假設HEAD包含原有聊天功能。理由：保護既有未提交工作。代價：整合時需對照主工作區後續變更。
2. 不順手改動兩項基線pynput測試失敗。理由：不是本次引入，且與主機平台有關。代價：整體綠燈仍需適當平台驗證／另行處理。
3. 聊天已開始輸入後被搶占，解完提示也停止，不直接續跑。理由：無法保證草稿／輸入焦點已恢復。代價：此例外需要人工確認並重啟。
4. 不以無頭Linux測試宣稱Windows／真實AI驗收成功。理由：缺少實機觀測。代價：使用者需確認真實30秒成功率及輸入相容性。
5. 將「只有標點的提示」由審查Minor提升為Important並修正。理由：空比對字串會在任何畫面觸發，干擾自動化。代價：設定必須包含實際文字。
6. 審查未判定的Windows／DPI／IME／OCR準確率／模型延遲／完整遮罩識別／打包／伺服器接受狀態，保留為明確驗收限制。理由：不能由fake證明。代價：部署前仍需人工測試。
7. 啟用圖片優先監看後，聊天只使用已在前景的目標，不搶回焦點。理由：消除取消後原生啟用重試仍搶焦點的風險。代價：使用者切走視窗時會停止，而非自動切回。

無已知被擱置的Minor程式碼項目；Windows 測試及打包已完成，實際辨識流程未驗收項目與 Linux 平台限制仍保留。
