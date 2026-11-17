# 規則「Discord 通知」— 設計文件

- **日期**：2026-07-08
- **狀態**：已與需求方確認設計方向，待審閱
- **相關**：延伸自監看規則引擎（`2026-07-06-keyboard-executor-design.md` §8）的 `notify` 觸發

## 1. 動機

規則觸發 `notify` 時目前只寫進 GUI 日誌面板，離開電腦就看不到。使用者希望重要事件（例如遊戲跳出人機驗證 CAPTCHA）能即時通知到手機上的 Discord。

Discord Webhook 是最簡方案：在頻道設定建一個 webhook 取得網址，程式往該網址 POST 一段 JSON 即可，不需 bot、不需 OAuth。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 選擇範圍 | **全域**：所有 `notify` 觸發都兼發 Discord；規則模型不改 |
| 開關方式 | 設定頁填 webhook 網址＝開；留空＝關（行為與現況完全相同） |
| 訊息內容 | **純文字**：使用者填的通知訊息（2026-07-09 依需求方要求移除原本附加的觸發時間戳） |
| 傳輸方式 | Discord Webhook + stdlib `urllib`（**不新增套件、打包不變**） |
| 阻塞處理 | 非同步（daemon thread）送出，網路慢/失敗不卡輪詢迴圈 |
| 規則名 | 暫不帶入訊息（notifier 介面只收訊息字串；YAGNI，使用者可自行寫進訊息） |

> **扇出範圍註記**：實作是包裹 `notifier` callable 本身，因此**所有經 notifier 的訊息**都會兼發 Discord——除了 `notify` 觸發，也包含規則引擎的「連續失敗健康告警」（`_record_failure`，同一失敗串最多發一次）。這是刻意的：監看在你離開時默默壞掉時，手機收到告警反而最有價值。

## 3. 設定（`app/settings.py` + `app/settings_page.py`）

- `Settings` frozen dataclass 新增 `discord_webhook_url: str = ""`。
- `validate_settings`：
  - 空字串＝停用，直接通過。
  - 非空則須符合 Discord webhook 形態：以 `https://` 開頭且路徑含 `/webhooks/`；否則拋 `ScriptValidationError`（繁中，例：`設定 discord_webhook_url 不是合法的 Discord webhook 網址: …`）。
- 向後相容：舊 `settings.json` 無此欄 → `Settings(**data)` 以預設 `""` 補上，照常載入。
- 設定頁新增「Discord Webhook 網址」`QLineEdit`（一般顯示，方便貼上核對）；與現有設定一致，**重啟監看後生效**。

## 4. Discord 發送（新檔 `core/discord_notify.py`）

純傳輸 + 格式化，無 Qt、無平台差異、可完整單元測試。用 stdlib，不加依賴。

```python
def format_message(message: str, when) -> str:
    """when: datetime → 'YYYY-MM-DD HH:MM:SS'。回傳要送到 Discord 的內容。"""
    return f"{message}\n🕒 {when:%Y-%m-%d %H:%M:%S}"

def post_discord(webhook_url: str, content: str, *, poster=None,
                 timeout: float = 5.0) -> None:
    """POST {"content": content} 到 webhook。poster 注入供測試，預設 urllib。
    網路/HTTP 例外上拋，由呼叫端（扇出 notifier）隔離並記錄。"""
```

- 預設 `poster` 以 `urllib.request.Request`（`Content-Type: application/json`）+ `urlopen(timeout=…)` 送出後關閉回應。
- Discord 內容上限 2000 字元；`content` 過長時截斷（保險，一般訊息很短）。

## 5. 扇出 notifier（`app/watch_controller.py`）

- `WatchController.__init__` 新增參數 `discord_webhook_url: str = ""`（由 `main_window` 從設定帶入，與現有 `stop_key` 同模式）。
- `build_job` 內原本的
  `notifier=lambda message: progress({"kind": "notify", "message": message})`
  改為呼叫一個扇出 notifier：
  1. 先 `progress({"kind": "notify", "message": message})`（GUI，快速、同步）。
  2. 若 `discord_webhook_url` 非空：組 `format_message(message, now())`，丟一個 **daemon thread** 執行 `post_discord`；例外於該 thread 內 `try/except` 記 log，**絕不冒泡**。
- 扇出邏輯抽成可注入的 builder（注入 `dispatch`＝送出執行器、`now`＝時間來源、`sender`＝`post_discord`），預設 `dispatch` 為 daemon-thread 產生器，讓測試能同步執行、時間可決定。

放置：扇出 builder 與 `format_message`/`post_discord` 一起放 `core/discord_notify.py`（純邏輯），`watch_controller` 只做接線。

## 6. 接線（`app/main_window.py`）

讀 `settings.discord_webhook_url`，建構 `WatchController` 時傳入（與 `stop_key` 相同位置）。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `discord_notify` | `post_discord` 以注入 poster 驗證帶對的 URL 與 `{"content": …}` body；`format_message` 內含訊息與時間；內容過長截斷 |
| 扇出 notifier | 有 webhook → GUI progress 與 Discord sender 都被呼叫、內容含時間；無 webhook → 只 GUI、不呼叫 sender；sender 拋例外被吞、progress 仍執行 |
| `settings` | 驗證接受空字串與合法 webhook、拒非 https / 缺 `/webhooks/`；round-trip；舊檔（無欄位）以預設載入 |
| `settings_page` | 欄位存在且能存回設定 |

## 8. 安全性

webhook 網址為機密，以**明文**存於本機 `settings.json`（與熱鍵等設定同檔）。對本機個人工具可接受；持有該網址者即可向該頻道發訊息，故不應外流此檔或網址。程式不記錄 webhook 內容到日誌。

## 9. 非目標（YAGNI）

- Discord bot / OAuth / 私訊 API（webhook 已足夠）
- 附截圖或 embed 卡片（純文字即可）
- 每條規則各自的 webhook 或訊息路由（全域單一 webhook）
- 規則名自動帶入（需改 notifier 介面）
- 其他平台（Telegram、Slack、Email）
