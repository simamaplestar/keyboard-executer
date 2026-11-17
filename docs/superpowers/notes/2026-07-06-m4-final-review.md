# M4 全分支最終審查紀錄（90ad2f6..f842bbd）

- **結論**：With fixes → 修正批次（7a1c7c1）+ re-review 邊界修正（f842bbd）完成 → **簽核通過**。
- **套件狀態**：461 passed, 1 skipped（win32-gated），app 層 133 測試綠。
- **待驗收**：完整 GUI 實機操作（record/play/watch、熱鍵、權限、版面）交人工。
- **執行緒安全裁定**：雙 Worker 路徑（play/watch）signal 全連 QObject bound method、皆有 wait/cleanup；背景執行緒不直接碰 widget。Qt 隔離重驗通過（core/platforms/storage 零 Qt）。
- **spec §9 六畫面**：主視窗/錄製面板/腳本編輯器/規則編輯器/區域框選器/設定頁 全部present且接線。

## 已完成的最終修正批次

**7a1c7c1（三 Important + 三 Minor）：**
1. MainWindow.closeEvent 收尾 QThread（關窗前停 run/watch controller + wait 兩 worker）——先前關窗會 crash-on-exit + 背景續送輸入
2. RuleEngine._fire 的 run_script 失敗經 _emit_error 入 GUI 日誌（不再只 stderr，符合 §10 不可靜默）
3. 錄製面板 STOP 鈕點擊不再錄進腳本尾端（pressed 訊號設抑制旗標）
4. WindowInfo docstring x/y 單位更正（平台輸入座標：Win 實體像素 / mac 點）
5. 回放訊息用 settings.stop_key（不再硬編 F10）
6. __version__ 0.1.0→0.4.0（與 pyproject 同步）+ sanity 測試同步

**f842bbd（re-review 發現的邊界）：**
- 抑制旗標於點擊放開（MOUSE_UP）後解除——先前「按下 STOP 鈕後拖離取消」會讓旗標永久卡住、之後所有正常點擊被靜默丟棄。加回歸測試鎖住。

## M5 計畫必須吸收的待辦（審查列出）

1. **進入點**：pyproject 加 `[project.gui-scripts] keyboard-executor-gui = keyboard_executor.gui:main`（+ CLI `keyboard-executor = keyboard_executor.cli:main`）或 PyInstaller spec 指向
2. **logging 收斂**：stderr 三處來源（`_poll_until` 輪內失敗、`_fire` 失敗、guard 警告）打包後不可見——M5 統一走 logging，同時寫 GUI 日誌面板與滾動日誌檔（spec §10 末、§9 明列）
3. **macOS 打包**：三權限主動請求（`CGRequestScreenCaptureAccess`/`CGRequestListenEventAccess`）、`x-apple.systempreferences:` deep link（spec §10「直達系統設定連結」未做）、Info.plist usage descriptions、簽章/公證（未簽章降級路徑已完整）
4. **GUI 缺 delete 入口**：ScriptListController.delete_selected / RuleListController.delete / TemplateStore.delete 的 seam 已建但無按鈕——補 GUI CRUD（M3 待辦 2c 本意）
5. **模板擷取無影像預覽**（spec §8.2「框選→預覽→命名」的預覽段）——補或記 backlog
6. **run/watch worker 處理器重複** + `_cleanup_worker` wait() 最長凍 5s + 不歸零 self._worker——若打包後有第三種背景工作再抽共用 helper
7. **多螢幕**：RegionPickerOverlay 只涵蓋 primaryScreen；drag_scale devicePixelRatio 未實機驗——併 Windows backlog
8. **rule_editor.py 直接呼叫 get_platform()/MssScreenCapture()**（未注入）+ settings_page import 私名 `_default_permission_checks`——清理
9. **Qt 內建對話框英文按鈕**——載 qtbase_zh_TW translator
10. **_parse_number vs _get_positive_number 錯誤訊息格式統一**（Minor）

## Windows backlog（跨里程碑累積，M5-prep 或之後）

- winsdk OCR 實作（win32/ocr.py 目前薄適配）、pydirectinput 實機、I4（watch game_input_mode）、mss 多螢幕/DPI、drag_scale devicePixelRatio 實測、pydirectinput 未知按鍵行為

## 驗收注意事項（交人工，M4 面向）

- 完整 GUI：啟動 `python -m keyboard_executor.gui`、腳本清單/編輯/回放、規則編輯（含框選+模板擷取）、監看、錄製面板（用「按鈕停止」驗證無尾端點擊）、設定頁、權限橫幅
- 追加驗收：回放/監看進行中關閉主視窗，確認無 QThread 警告、無殘留背景輸入
- 規則觸發腳本失敗時，確認 GUI 日誌面板有顯示（非只終端機）

## 已裁定 drop

- check_accessibility pragma、橫幅硬編色、rows() 重驗、_overlay 競態/scale_rect 內聯、_default_recognizer 可變預設、_fail_streak 不清（鍵集有界）
