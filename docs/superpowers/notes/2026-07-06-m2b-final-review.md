# M2b 全分支最終審查紀錄（90ad2f6..8840b3d）

- **結論**：With fixes → 修正批次（8840b3d）完成並經 re-review 確認 → **簽核通過**。
- **套件狀態**：213 passed, 1 skipped（win32-gated）於 macOS。
- **M2a carry-over 吸收**：5 項確認完成（可中斷 sleep、is_alive+存活檢查、stop 重用語義文件化、key 驗證前移、list/tuple 統一等）；唯 `cli.main()` 分支測試未做（計畫層縮水，見下方 M3 待辦）。

## 已完成的最終修正批次（8840b3d）

1. **修飾鍵字元正規化**（Windows 組合鍵錄製實質修復）：keynames.is_valid_key 收緊為可列印單字元；keymap.key_to_name 折控制字元（\x01–\x1a→字母）、非可列印→None；hook 走 listener.canonical()（對無 canonical 的 Spy 安全降級）
2. **dispatch 執行緒安全**：run_record 的 dispatch 加 threading.Lock（鍵盤/滑鼠兩 listener 執行緒序列化進 Recorder）；recorder docstring 標非執行緒安全
3. hook 半啟動回收（listener start 失敗 → 停已啟動的、重設 None、re-raise）
4. Recorder 異鍵 down/up 交錯測試
5. _emit TOCTOU 快照
6. key_to_name 家族首名斷言

## M3 計畫必須吸收的待辦

1. **`cli.main()` 分支測試**（M2a 第 5 項未竟部分 + M2b Important #3）：list/play/record 分派、--dir 傳遞、darwin 權限攔截皆無單元測試——M3 收尾批次補（fake Player/ScriptStorage + capsys）
2. **`storage.save` 的 OSError 對稱處理**（load 有攔、save 沒攔）+ run_record 存檔失敗的名稱重問迴圈——可併入 M4 GUI 存檔流程
3. **規則 trigger `stop_all` 的跨 session 停止廣播來源**：SessionGuard 單一 stop_event 模型相容，但 M3 需定義廣播來源（watcher 觸發 → 停止進行中的 play）
4. **origin 擷取時機**：目前選窗當下擷取，非 F9 開錄當下；M4 GUI（選窗→操作→開錄）窗口更大，on_toggle 開錄時 refresh origin

## M3 結構性預告（來自審查）

- `wait_text/if_text/click_text` 新 ActionType：Recorder 不需改（只映射 6 種 InputEvent）；dispatch 加 if/elif + _VALIDATORS 分支即可
- `on_timeout: goto` 需要 `_run_actions` 從 for 迴圈改索引機、`_run_one` 回傳控制訊號（兩方法簽名結構性改動，範圍可控）
- `action_to_dict` 的動作清單特例鍵需擴充（then/else），考慮 per-type serializer
- hook/guard 基礎設施 M3 watcher 不重用（watcher 是螢幕輪詢）；下一個重用者是 M4 GUI 錄製面板
- Retina 座標換算（M1 筆記既有）：ScreenCapture 是實體像素、pywinctl/pynput 是點——OCR/模板 bounding box 換算回點擊座標需處理

## 已裁定 drop

- _SPECIAL 結構性衍生（測試已鎖）、and None 慣用法、EventKind docstring、修飾鍵左右變體逐一測、角落 move self-filter 隱式測、wait(0.05) 魔術數字、dead-window guard

## 驗收注意事項（交人工）

- macOS 需開「輸入監控」權限錄製才收得到事件；F9/F10 若系統設定未開「將 F1/F2 作為標準功能鍵」需按 fn
- 驗收時特別加測 Cmd+組合鍵 與 Option+組合鍵各一次，打開存出的 JSON 檢查 keys 內容（Important #1 的 macOS 面向證據）
