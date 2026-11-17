# M3 全分支最終審查紀錄（90ad2f6..52f9ec8）

- **結論**：With fixes → 修正批次（52f9ec8）完成並經 re-review 確認 → **簽核通過**。
- **套件狀態**：340 passed, 1 skipped（win32-gated），0 警告。
- **待驗收**：live vision（真實 mss 擷取 + 原生 OCR + 觸發腳本）交人工。

## 已完成的最終修正批次（52f9ec8）

- **C1**（Critical）：CLI play 接 `templates=TemplateStore(...).load_template`——先前所有 `*_image` 動作會中止「此動作需要模板來源」，直接讓 §13-M3「click_image 可用」驗收失敗。
- **C2**（Critical）：MssScreenCapture.capture 單位契約——mss 的 grab() 一律以「點」解讀 region，capture 先 ÷scale_factor() 換回點才 grab。pinned mss 10.2.0 因 nominal-resolution 旗標 scale=1.0（÷1 no-op），但 mss 9.x 會讓 Retina 點擊偏位。ABC 契約（region 為實體像素）不變、core scale=2 測試全綠、mss floor 提到 >=10。
- **I1**：RuleEngine._fire 移入 per-rule try/except + 繁中 stderr log；run_script 的 PlayResult ok=False 記錄（先前壞規則殺整個 watch、觸發腳本失敗無痕）。
- **I2**：watch live 路徑 best-effort SessionGuard（緊急停止），權限失敗印警告繼續。
- **I3**：VisionOcrEngine 設 recognitionLanguages ["zh-Hant","zh-Hans","en-US"]——先前未設，繁中 wait_text 實機會失敗。
- Minor #2：threshold==0 邊界測試 + mode==regex 的 pattern eager re.compile 驗證。
- Minor #6：巢狀 goto 不外溢的回歸測試。

## Retina 座標鏈裁定

端到端算術正確（Player 與 RuleEngine 一致），C2 修正後 grab 邊界的單位契約也正確（÷scale 換點）。人工驗收時記錄實機 scale_factor()（pinned mss 10.2.0 上預期 ≈1.0）與 Vision OCR bounding box 對齊。

## M4 計畫必須吸收的待辦

1. **Minor #1（動作前綴）**：`_get_str`/`_get_int`/`_get_region` 硬編「動作」，Rule 錯誤讀作「動作 規則 欄位…」——label 化（同 M2a _check_no_extra 修法），M4 GUI 會逐字顯示這些訊息。
2. **M6 GUI-readiness 缺口**（審查列出，非阻擋）：
   (a) Player 無進度/當前步驟 callback（§7/§9 日誌面板需要）
   (b) RuleEngine 無 on_fire/status hook（GUI 可包 notifier，但 run_script/stop_all 觸發不可見）
   (c) ScriptStorage/RuleStorage/TemplateStore 缺 delete（TemplateStore 也缺 list_names）供 GUI CRUD
   (d) wait_* 輪詢中 capture/OCR 例外目前會中止整個 play——§8.1 說 player 重用規則管線（§10 是 skip-and-log），M4 定案政策
3. **I4**：watch 觸發的腳本忽略 settings.game_input_mode（用一次性 get_platform 建的 platform）——Windows backlog（Windows live 已延到 M5-prep）。
4. **連續失敗 N 次通知**（spec §10）：M3 只 record+skip，plan 明文延到 M4 GUI 日誌面板。
5. **find_windows getAppName() 效能**（M1 筆記既有）：watcher 每 tick 對每視窗呼叫 AppleScript（~100ms/窗），多視窗多規則會秒級延遲——M4 或屆時先過 title 再查 app。
6. **run_record 名稱重問迴圈 + TemplateStore missing vs corrupt 區分**（M2b/M3 延後）：併入 M4 存檔/模板管理 UI。

## spec 待對齊

- §5 措辭：只說 templates 有子目錄，但 rules/ 也是子目錄（實作較佳）——寫 M4 時更新 spec §5。
- §14：補 mss nominal-resolution 的現實（scale 在 pinned 版是 1.0）。

## 已裁定 drop

- find_text 未知 mode fallback（validation 已限）、_require_capture 重複呼叫（冪等）。

## 驗收注意事項（交人工）

- macOS 需「螢幕錄製」+「輸入監控」+「輔助使用」三權限；watch 用 stop_all trigger 或 Ctrl+C 停（F10 未接 watch）。
- 驗收 click_image：確認 play 現在會載入模板（C1 修正）；記錄實機 scale_factor 與點擊落點是否對齊。
- 驗收 wait_text 繁中：確認 Vision 語言設定（I3）讓「連線中斷」類文字辨識到。
