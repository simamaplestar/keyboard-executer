# 設定存檔免重開 — 設計文件

- **日期**：2026-07-09
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

目前多數設定（緊急停止/切換熱鍵、OCR 語言、Discord webhook）改完必須**重啟程式**才生效。原因：`main_window.__init__` 開機時只讀一次 `self._settings`，把值「烤進」開機就建好、之後一直活著的物件——平台工廠 partial（OCR）、RunController／WatchController（stop_key、webhook）、系統級緊急停止熱鍵（stop_key）。設定頁存檔只寫 `settings.json`，不會回頭更新這些物件。

目標：**存檔後免重開即生效**，且「進行中的執行/監看維持原設定，不中途抽換」。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 進行中行為 | 只套用到**下一次**執行/監看；進行中的那一次維持原設定（最安全） |
| 生效時機 | 日誌等級＝立即；系統級緊急停止熱鍵＝立即重註冊；stop_key(控制器)/webhook/OCR＝下一次執行/監看 |
| 控制器更新方式 | **就地更新欄位（不重建實例）**，避免停止鈕指向新實例而停不掉進行中的那次 |

## 3. 生效時機總表

| 設定 | 生效 | 機制 |
|------|------|------|
| `log_level` | 立即 | 三處一起調級：`main_window` 日誌過濾（`:413`）即時讀 `self._settings`；並在 `_apply_settings` 重定套件根 logger（`PACKAGE_LOGGER`）與 GUI 日誌 handler 的等級——否則 `logger.debug`／檔案日誌要重開才變詳細 |
| 系統級緊急停止熱鍵 | 立即 | `WindowsHotkey.unregister()` → `register(new stop_key)` |
| 控制器 `stop_key` | 下一次執行/監看 | 就地更新 `RunController`/`WatchController` 欄位 |
| Discord `webhook` | 下一次監看 | 就地更新 `WatchController` 欄位 |
| OCR 語言 | 下一次執行/監看 | 重建 `self._get_platform` partial（`get_platform` 不快取，每次 build_job 重建平台/OCR 引擎） |

## 4. 各元件改動

### 4.1 `app/settings_page.py`
- 加 `saved = Signal(object)`（PySide6 Signal）。
- `_on_save` 儲存成功後 `self.saved.emit(settings)`（驗證失敗時不發）。
- 狀態訊息由「已儲存，重新啟動程式後生效」改為「已儲存，已即時套用（執行中的維持原設定）」。

### 4.2 `app/run_controller.py`
- 加 `apply_settings(self, *, stop_key: str, get_platform) -> None`：就地更新 `self._stop_key`、`self._get_platform`。不重建、不動進行中的 `_stop_event`。

### 4.3 `app/watch_controller.py`
- 加 `apply_settings(self, *, stop_key: str, get_platform, discord_webhook_url: str) -> None`：就地更新 `self._stop_key`、`self._get_platform`、`self._discord_webhook_url`。

### 4.4 `app/main_window.py`
- `_on_open_settings`：建立 `SettingsPage` 後先 `page.saved.connect(self._apply_settings)`，再 `.exec()`。
- 新增 `_apply_settings(self, new: Settings) -> None`：
  1. `self._settings = new`（log 等級即時生效）。
  2. 重建 `self._get_platform = partial(get_platform, ocr_lang=ocr_lang_from_setting(new.ocr_language))`。
  3. `self._run_controller.apply_settings(stop_key=new.stop_key, get_platform=self._get_platform)`。
  4. `self._watch_controller.apply_settings(stop_key=new.stop_key, get_platform=self._get_platform, discord_webhook_url=new.discord_webhook_url)`。
  5. 重新註冊系統級緊急停止熱鍵（見 4.5）。
  6. 刷新畫面上顯示熱鍵的標籤（緊急停止鍵、錄製切換鍵）。
- 顯示熱鍵的標籤改存成實例屬性（目前是區域變數）以便刷新。

### 4.5 熱鍵重註冊（`main_window`）
```
hk = getattr(self, "_global_hotkey", None)
if hk is None:            # 非 win32／離屏／原本註冊就失敗 → 無事可做
    return
hk.unregister()
if hk.register(new_stop_key): 記 log 成功
else: 記 log 失敗（保留：仍可用滑鼠角落停止）
```
沿用既有唯一的 `WindowsHotkey` 實例（`register` 可重複呼叫）。

## 5. 安全性（進行中不動）

進行中的執行/監看在 `build_job` 當下已捕獲自己的 `stop_event` 與 `platform`；`apply_settings` 只改「下一次 `build_job` 才讀的欄位」，`stop()` 用的 `_stop_event` 未被更動 → 停止鈕對進行中的那次仍有效，其設定不變。系統熱鍵重註冊後，進行中的那次「舊鍵（in-session guard）與新鍵（系統級）皆可停」，屬安全的多重保險。

## 6. 錯誤處理

- 熱鍵重註冊失敗：記 log、不中斷（存檔已成功寫入磁碟；仍有滑鼠角落等停止途徑）。
- 設定驗證：維持現況於 `_on_save`（不合法就不存、不發 `saved`）。
- `_apply_settings` 各步皆為賦值或有 guard 的呼叫（`unregister()` 內部自吞例外、`register()` 回傳 bool、`setLevel`/`setText` 對已建立的物件不拋、hotkey 為 None 時提早返回），依構造不拋例外，故不需額外 try/except；GUI 不會因此崩潰。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `settings_page` | 存檔成功發 `saved(Settings)`（帶新值）；驗證失敗不發；狀態訊息更新 |
| `run_controller` | `apply_settings` 後 `build_job` 用新 stop_key（guard 收到）與新 get_platform |
| `watch_controller` | `apply_settings` 後 `build_job` 用新 stop_key、webhook、get_platform |
| `main_window` | `_apply_settings` 更新 `self._settings`、呼叫兩控制器 `apply_settings`（帶新值）、以注入的假熱鍵重註冊、刷新標籤文字 |

## 8. 非目標（YAGNI）

- 把設定套用到**進行中**的執行/監看（明確不做）。
- 設定檔外部變動的即時監看（inotify 等）。
- OCR 引擎熱抽換的最佳化（沿用「下一次重建」即可）。
- 設定分類的細緻「哪些需重啟」提示（本次全部做到免重啟）。
