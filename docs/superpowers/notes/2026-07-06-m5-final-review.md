# M5 全分支最終審查紀錄（422482f..616345c）

- **結論**：With fixes → 修正（616345c，兩處 GUI 可達 stderr→logger）完成 → **簽核通過**。
- **套件狀態**：494 passed, 1 skipped（win32-gated），0 GUI 可達 stderr（僅 cli.py/demo.py 保留 CLI 面向輸出）。
- **待驗收**：PyInstaller build→codesign→notarytool→staple→啟動→授權→端到端（macOS 實機，README + Task 5 Step 5 清單）交人工。

## 已完成的最終修正（616345c）
- `storage/rules.py` load_enabled 損毀規則跳過 + `app/settings.py` 設定檔損毀 → 由 print(stderr) 改 logger.warning（打包後 GUI 可見、進 app.log，符合 §10）；capsys→caplog 遷移。

## PyInstaller hiddenimports 裁定（紙上審查）
- 專案自身的 lazy import（Quartz/Vision/ApplicationServices/pywinctl/mss/cv2/winsdk 在函式內）是**靜態 import 陳述式**，PyInstaller bytecode 分析可偵測 → 自動納入。
- 真正動態載入的（pynput 後端、mss 後端、winsdk 子模組）已明列 hiddenimports。
- src 內零 `importlib.import_module`/`__import__` 動態字串。結論：不會「首次用到才 crash」。殘餘風險：qtbase_zh_TW.qm 是否入 bundle（安全靜默降級）、winsdk 實機（Windows backlog）。

## 已裁定 backlog（口頭裁定存此，避免流失）
1. GUI 日誌面板規則失敗可能重複兩行（logger + _emit_error additive 都到 log_view）——人工驗收裁定可接受度或 GUI 橋過濾
2. CLI 不讀 settings.json 的 log_level（永遠 INFO；GUI 有讀）——無害
3. Windows windowed 模式 StreamHandler stderr 可能為 None（logging handleError 靜默吞、無 crash）——可加守衛
4. worker helper 抽取（無第三種背景工作，延後條件未觸發）
5. 模板擷取影像預覽（spec §8.2 的預覽段，純視覺件）
6. README 可補 codesign --verify/spctl --assess 與「打包 App 僅 GUI、CLI 走 pip」兩行
7. request_missing_permissions 命名（無條件請求兩權限，已授予時 no-op）

## Windows backlog（跨里程碑累積）
- winsdk OCR 實作、pydirectinput 實機、I4（watch game_input_mode）、mss 多螢幕/DPI、drag_scale devicePixelRatio 實測、build.ps1 實機驗證、RegionPicker 多螢幕

## spec §15 v2 範圍外（確認不做）
- 背景視窗注入（PostMessage）、Linux、腳本市集、條件運算式 AND/OR、cron 排程器
