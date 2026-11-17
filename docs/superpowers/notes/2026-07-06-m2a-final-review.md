# M2a 全分支最終審查紀錄（5f92e13..e2fd2ba）

- **結論**：With fixes → 修正批次（e2fd2ba）完成並經 re-review 確認 → **簽核通過**。
- **套件狀態**：122 passed, 1 skipped（win32-gated）於 macOS。
- **待驗收**：手動驗收（textedit-demo 回放 + Ctrl+C 中斷）交由用戶執行。

## 已完成的最終修正批次（e2fd2ba）

1. `play()` 接殺意外例外（key typo 通過驗證但 keymap 拋錯 → PlayResult 而非 traceback）
2. `run_script` 返回後 refresh + activate 父視窗（防止後續輸入打進子腳本視窗；M3 規則引擎觸發也走 run_script，此缺口已封）
3. `ScriptStorage.load` 攔 `UnicodeDecodeError`/`OSError`（cp950 手編檔不再 traceback）
4. `path_for` 路徑防呆（封 CLI `play "../x"` 穿越）
5. 補 run_script 深度 >8 邊界測試

## M2b 計畫必須吸收的約束（Global Constraints 候選）

1. **可中斷 sleep**：Player 的 delay/retry 改用 `stop_event.wait(timeout)` 型等待——F10 緊急停止不能被長 delay 卡住（Player 進執行緒後 SIGINT 不再救場）
2. **`WindowManager.is_alive(window) -> bool` 輕量契約** + 純鍵盤動作的存活檢查（目前鍵盤動作不查視窗，掛機時視窗關閉輸入會流向焦點視窗；不能天真每鍵 refresh——macOS getAppName 是百 ms 級 AppleScript）
3. **Player stop_event 重用語義定案**：同實例第二次 play 目前會立即中止（stop 未清）；文件化「一次性」或 play 開頭 clear
4. **key 名稱驗證前移**：keymap 名單抽到 core 或注入 validator，讓 `key_press.key` 在載入時就驗證
5. list/tuple 容忍度統一（delay vs _get_point）；`title_pattern: ""` 正規化；window_retry 驗證獨測；`main()` 分支測試（record 子命令重構時一併）

## M3 計畫預告

- `wait_*` 的 `on_timeout: goto` 需要 `_run_actions` 改索引機、`_run_one` 回傳控制訊號（結構性但範圍可控：兩個方法簽名）
- `action_to_dict` 的動作清單特例鍵需擴充（`then`/`else`），考慮 per-type serializer
- dispatch 本身（if/elif + `_VALIDATORS`）加分支即可，不需手術
- 檔名與 JSON 內部 name 背離：`load()` 可檢查 `stem == data["name"]`

## 已裁定 drop

- `--dir` help 字串重複（過度 DRY）
- mouse_drag 雙 refresh（一動作一 refresh 的優化留 M2b 順手做，非必要）

## 驗收注意事項

- Ctrl+C 中斷測試：焦點切回終端機到按下 Ctrl+C 之間，`text_input` 會打進終端機——這是前景模型的預期行為（鍵盤動作存活檢查列 M2b），不是 bug。
