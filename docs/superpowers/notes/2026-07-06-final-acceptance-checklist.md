# Keyboard Executor — 最終人工總驗收清單

自動化部分（M1–M5，494 tests pass, 1 skipped）已全數完成並經雙層審查簽核。
以下是需要**你本人在 macOS 實機**執行的驗收項——因涉及真實滑鼠鍵盤、系統權限、螢幕內容、打包簽章，無法自動化。

前置：
```bash
cd /path/to/keyboard-executor
source .venv/bin/activate
```
首次執行任一項會要求 macOS 權限：**系統設定 → 隱私權與安全性**，開啟「輔助使用」「輸入監控」「螢幕錄製」給終端機（或打包後的 App），然後重跑。

---

## A. CLI 回放（M2a）
1. 開啟「文字編輯」新文件
2. `python -m keyboard_executor.cli play textedit-demo`（範例腳本已在 `~/.keyboard-executor/scripts/`；若無，見 §F 重建）
   - 預期：TextEdit 切前景 → 輸入標題行 → loop 三次「loop! 」(隨機間隔) → 「完成」；印「回放完成」
3. 中斷測試：把腳本 `repeat` 改 -1，執行中按 Ctrl+C → 印「已中斷」

## B. CLI 錄製（M2b）
4. `python -m keyboard_executor.cli record`（選 TextEdit 視窗）→ 按 **F9** 開始 → 手動操作幾下 → 按 **F9** 停止 → 命名存檔
5. `python -m keyboard_executor.cli play <剛存的名稱>` → 確認回放重現你的操作
6. **組合鍵驗證**（重要）：錄一段含 Cmd+A、Option+字母的操作，打開存出的 JSON 檢查 `key_combo`/`text_input` 內容正確（非控制字元/亂碼）——這是 M2b 修正批次的重點
7. F10 放棄：record 中按 **F10** → 確認不存檔

## C. CLI 監看 + OCR/模板（M3）
8. 建一條規則（可先用 GUI §D 建，或手寫 JSON 到 `~/.keyboard-executor/scripts/rules/`）：condition text「某畫面文字」→ trigger run_script 或 notify
9. `python -m keyboard_executor.cli watch` → 讓畫面出現該文字 → 確認規則觸發
10. **繁中 OCR 驗證**：規則用繁體中文 pattern（如「連線中斷」）→ 確認 Vision 辨識到（M3 修正批次設了 zh-Hant 語言）
11. **click_image/click_text 驗證**：腳本用 click_image（先用 GUI 框選擷取模板）→ 確認點到模板中心（Retina 螢幕特別留意落點是否精準——這是 M1/M3 座標鏈的重點）
12. watch 停止：Ctrl+C 或 stop_all trigger（注意：watch 迴圈**未接 F10**，只能 Ctrl+C 或 stop_all）

## D. GUI 完整操作（M4）
13. `python -m keyboard_executor.gui` → 主視窗開啟
14. 若有權限缺失 → 確認頂部橫幅顯示 + 「開啟系統設定」按鈕能跳到對應分頁
15. 腳本清單：選腳本 → 執行 → 即時日誌面板逐步顯示進度 + 最終結果
16. 腳本編輯器：新增/刪除/排序各類動作 → 存檔 → 確認可回放
17. 規則編輯器：建規則（含「框選區域」「框選並擷取模板」）→ 存檔
18. 區域框選器：拖曳框選 → 確認回傳的區域正確（Retina 上尤其注意）
19. 監看：從 GUI 啟動 → on_fire 狀態列更新 → 規則觸發腳本失敗時**日誌面板要顯示**（非只終端機——M4 修正批次重點）
20. 錄製面板：**用面板「停止」按鈕**停止（非 F9）→ 確認腳本尾端**沒有**多出點擊停止鈕的雜散 click（M4 re-review 邊界修正重點）
21. 設定頁：改熱鍵/OCR 語言/日誌等級 → 確認持久化（重開 GUI 仍在）
22. 刪除入口：腳本/規則/模板管理的刪除鈕 → 確認確認對話框、取消不刪、確認才刪
23. **關窗收尾**：回放或監看進行中直接關閉主視窗 → 確認無 crash、無殘留背景輸入（M4 修正批次 closeEvent）

## E. 打包發布（M5）
> ⚠️ PyInstaller 對 venv 的 Python 3.14 相容性未實機驗證；若 build 失敗，依 `packaging/README.md` 用 Python 3.12/3.13 另建打包 venv。
24. `bash packaging/build.sh` → 產出 `packaging/dist/Keyboard Executor.app`
25. 簽章/公證：依 `packaging/README.md` 執行 codesign → notarytool → staple（或 ad-hoc 簽章供本機測試，README 有降級說明）
26. 啟動 .app → 授予三權限 → 從打包 App 跑 record/play/watch 端到端
27. 確認日誌落地 `~/.keyboard-executor/.../logs/app.log`（打包後 stderr 不可見，全走這裡——M5 logging 收斂重點）
28. `keyboard-executor --version` / `keyboard-executor-gui`（pip 安裝後的 entry points）

## F. 範例腳本重建（若 §A 找不到）
```bash
mkdir -p ~/.keyboard-executor/scripts
cat > ~/.keyboard-executor/scripts/textedit-demo.json << 'EOF'
{"name":"textedit-demo","target_window":{"title_pattern":"未命名|Untitled"},
 "settings":{"speed":1.0,"repeat":1,"humanize_jitter_pct":10},
 "actions":[{"type":"mouse_click","x":200,"y":200},
   {"type":"text_input","text":"M2a 回放測試："},{"type":"key_press","key":"enter"},
   {"type":"loop","count":3,"actions":[{"type":"text_input","text":"loop! "},{"type":"delay","ms":[200,500]}]},
   {"type":"key_press","key":"enter"},{"type":"text_input","text":"完成"}]}
EOF
```

---

## Windows 驗收（需 Windows 機器，跨里程碑 backlog）
- M1 demo 高 DPI、pydirectinput 遊戲模式、winsdk OCR、build.ps1 打包、多螢幕框選
- 詳見各 milestone final-review notes 的 Windows backlog 段

## 已知範圍界線（v1 不做，spec §15）
- 背景視窗注入、Linux、腳本市集、條件運算式 AND/OR、cron 排程
