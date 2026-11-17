# M1 全分支最終審查紀錄（b0770bd..1a6117f）

- **結論**：Ready to merge — Yes。無 Critical；三項 Important 均為 plan/spec 層級設計缺口（非 M1 程式缺陷），落入 M2/M3 規劃。
- **套件狀態**：46 passed, 1 skipped（win32-gated）於 macOS。
- **待驗收**：macOS 手動 smoke（plan Task 10 Step 6）；Windows smoke 記入 backlog（M5 前必補，含 125%/150% DPI 與 pydirectinput 未知按鍵行為驗證）。

## M3 規劃前必須解決（架構風險）

1. **macOS Retina 座標單位**：pywinctl/pynput 在 macOS 用的是 Cocoa points（Retina 上 1 pt = 2 px），spec §5.2「一律實體像素」在 macOS 不成立。M1 內部單位一致故可動，但 M3 的 mss 截圖是實體像素——OCR/模板 bounding box 換算回點擊座標時 Retina 會錯位一半。動作：spec §5.2/§14 補「平台輸入座標空間 + ScreenCapture scale factor」設計；修 geometry.py docstring 措辭。

## M2 規劃時的決策點

1. **game_input_mode 覆蓋不對稱**：目前僅 key_press/key_combo/mouse_click 走 pydirectinput；`text_input`/`mouse_drag`/`scroll` 仍走 SendInput，在攔截虛擬鍵碼的遊戲中會靜默失效。決策：game mode 下 text 改逐鍵 pdi 序列或文件化不支援；drag 走 pdi.moveTo + mouseDown/Up。
2. **settle/最小 hold 統一政策**：pdi click 無 settle、scroll 無 _SETTLE、game-mode hold_ms=0 零間隔可能被幀輪詢遊戲漏接——一併決策。
3. **InputEvent.kind 型別化**（Literal/StrEnum），避免字串 typo 流進錄製存檔格式。
4. **keymap 單字元 .lower() 遺失大小寫**：M2 錄製引擎處理 shift 時必須面對。
5. **補測**（fold-in）：parse_combo("") 與 "ctrl+" 邊界、find_windows title+app 交集、game-mode 測試斷言 pynput spy 為空。
6. **target_window 驗證**：空字串 pattern 匹配所有視窗、非法 regex 直接 traceback——M2 正式選取器加驗證。

## M4/M5 備忘

- macOS 權限引導需涵蓋「自動化（Automation/System Events）」與「螢幕錄製」，不只「輔助使用」（pywinctl 首次執行會觸發 Automation 對話框；smoke 失敗先查權限再判 bug）。
- Qt6 會自行設定 DPI awareness，factory 的 ensure_dpi_awareness 呼叫順序屆時確認。
- win32/dpi.py 的 ctypes.windll 不會對失敗 HRESULT 拋例外，fallback 分支實際到不了（無害但與註解意圖不符）——可改檢查回傳值或 OleDLL。
- 測試重構：SpyKeyboard/SpyMouse 兩份重複，上移 tests/fakes.py。
- find_windows 對每視窗呼叫 getAppName()（macOS AppleScript 可能百 ms 級），M3 watcher 輪詢時考慮先過 title。

## 已裁定 drop 的項目

- Rect frozen 未測、future import 冗餘、mouse_move 無獨立測試、demo main() 無自動化覆蓋（拋棄式驗收工具，人工 smoke 即驗收）。
