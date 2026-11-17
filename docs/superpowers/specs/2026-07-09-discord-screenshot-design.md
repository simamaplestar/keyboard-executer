# Discord 通知附辨識截圖 — 設計文件

- **日期**：2026-07-09
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

規則觸發時會送 Discord 通知，但目前只有純文字（`{"content": ...}`）。需求方希望通知能**附上觸發當下的辨識截圖**——也就是規則比對時實際擷取、送進 OCR／模板／顏色比對的那張框選區域畫面——好在 Discord 上一眼看出「為什麼觸發」。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 附哪張圖 | **框選的辨識區域**（`_matches` 擷取、比對當下的那張 BGR 影像；規則沒框選區域時即整個視窗畫面）。不另外重新擷取視窗／螢幕。 |
| 開關範圍 | **每條規則各自一個開關**（規則編輯器一個勾選框「附截圖」）。 |
| GUI 通知 | 不變，維持純文字（截圖只上 Discord）。 |
| 只有勾了才附 | `attach_screenshot=True` 且有擷取到影像時才編碼、附圖；否則走純文字路徑。 |
| 相依 | 不新增第三方套件：PNG 編碼用既有的 cv2（在 `vision.py`），multipart 用 stdlib（`discord_notify.py` 維持無 cv2）。 |

## 3. 資料流

```
_matches(rule) 擷取 BGR 影像 image ──┐
                                     ├─ (matched, image)
evaluate_once：matched 且過冷卻 ─────┘
   └─ _fire(rule, image)
        └─ _fire_one(rule, notify_trig, image)
             ├─ rule.attach_screenshot 且 image 非 None：
             │     png = encode_png(image)   # 失敗則 png=None
             │     notifier(trig.message, image_png=png)
             └─ 否則：notifier(trig.message)  # 單參數，既有行為
                  └─ make_notifier.notify：base_notifier(message) + （有 webhook 時）
                       非同步 _safe_send(sender, url, message, image_png)
                         └─ post_discord：image_png 有 → multipart；無 → JSON
```

## 4. 各元件改動

### 4.1 `core/models.py`（`Rule`）
- `Rule` 新增欄位 `attach_screenshot: bool = False`。
- `rule_to_dict`：輸出 `"attach_screenshot"`。
- `rule_from_dict`：讀 `"attach_screenshot"`，缺鍵預設 `False`（舊規則檔向後相容）；型別須為 bool，否則沿用現有欄位驗證機制拒絕。
- `_check_no_extra` 的允許鍵集合加入 `attach_screenshot`。

### 4.2 `core/vision.py`（新純函式）
```python
def encode_png(image_bgr: np.ndarray) -> bytes:
    """BGR 影像編碼成 PNG bytes（cv2.imencode，維持 OpenCV BGR 慣例，顏色正確）。"""
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ValueError("PNG 編碼失敗")
    return buf.tobytes()
```
- 純函式、可單元測試（給小 numpy 影像，斷言回傳非空 bytes 且以 PNG magic `\x89PNG` 開頭）。

### 4.3 `core/rule_engine.py`
- `_matches(rule)` 改回傳 `(matched: bool, image: np.ndarray | None)`：
  - 找不到視窗：回 `(False, None)`。
  - 有擷取：回 `(matched, image)`（`image` 即 `cap.capture(rect)` 的結果）。
- `evaluate_once`：`matched, image = self._matches(rule)`；後續分支照舊（失敗時 `matched=False, image=None`）。過冷卻後 `self._fire(rule, image)`。
- `_fire(rule, image)`：`on_fire` 不變；逐一 `self._fire_one(rule, trig, image)`（沿用第 4.x 的每個動作各自例外隔離）。
- `_fire_one(rule, trig, image)`：
  - `run_script` / `stop_all` 分支不變（忽略 image）。
  - `notify` 分支：
    ```python
    png = None
    if rule.attach_screenshot and image is not None:
        try:
            png = encode_png(image)
        except Exception as e:
            logger.warning("規則 %r 截圖編碼失敗，改送純文字通知：%s", rule.name, e)
            png = None
    if png is not None:
        self._notifier(trig.message, image_png=png)
    else:
        self._notifier(trig.message)
    ```
  - **關鍵**：不附圖時維持單參數呼叫，既有 1 參數 notifier（cli、測試、連續失敗警告 `_record_failure`）完全不受影響。
- `_record_failure` 的 `self._notifier(...)` 維持單參數（無截圖）。

### 4.4 `core/discord_notify.py`
- `make_notifier` 回傳的 `notify` 簽名改為 `notify(message: str, *, image_png: bytes | None = None)`：
  ```python
  def notify(message, *, image_png=None):
      base_notifier(message)                 # GUI 仍純文字
      if webhook_url:
          dispatch(lambda: _safe_send(sender, webhook_url, message, image_png))
  ```
- `_safe_send(sender, webhook_url, content, image_png=None)`：`sender(webhook_url, content, image_png=image_png)`；例外照舊只記「Discord 通知傳送失敗」（不含網址／內容／影像）。
- `post_discord(webhook_url, content, *, image_png=None, poster=None, timeout=5.0)`：
  - `image_png is None`：維持現況 `{"content": content[:2000]}` JSON，`content_type="application/json"`。
  - `image_png` 有值：建 `multipart/form-data`——欄位 `payload_json`（同一份 `{"content": ...}` JSON）＋ `files[0]`（`filename="screenshot.png"`, `Content-Type: image/png`, 內容為 PNG bytes），`content_type="multipart/form-data; boundary=..."`。
  - poster seam 擴為 `poster(url, data, timeout, content_type)`（`_urllib_post` 帶入 `content_type` 建 Request，取代寫死的 JSON header）；更新 2 個既有 poster 注入測試接受第 4 參數。User-Agent 仍帶 `KeyboardExecutor/1.0`（避免 403）。
  - multipart boundary 用**固定常數**（模組級，如 `----KeyboardExecutorBoundary`）或可注入值，讓 body 可重現、單元測試能斷言；不用亂數 boundary。boundary 幾乎不可能出現在 PNG／訊息中，固定值安全。

### 4.5 `app/rule_editor_model.py` + `app/rule_editor.py`
- **Model**：新增布林 `attach_screenshot`（預設 `False`）。
  - `from_rule`：`self.attach_screenshot = rule.attach_screenshot`。
  - `to_dict`：輸出 `data["attach_screenshot"] = self.attach_screenshot`。
- **UI**：在「通知訊息」欄下方加一個勾選框：`附上辨識截圖到 Discord 通知`（`attach_screenshot_check`）。`_apply_to_model` 依 `.isChecked()` 設旗標；`_load_from_model` 依旗標設勾選狀態。始終顯示（不隨通知勾選連動，保持簡單）。

## 5. 錯誤處理

- **PNG 編碼失敗**：`_fire_one` 內 try/except，退回純文字通知（記一次 warning），不中斷。
- **multipart 上傳失敗**（網路／HTTP 4xx/5xx）：由既有 `_safe_send` 吞掉，只記「Discord 通知傳送失敗」，不洩漏網址／內容／影像。
- **影像過大**：框選區域截圖為小圖（902×540 PNG 約數百 KB），遠低於 Discord 8MB webhook 上限，不另設限（YAGNI）；若未來需要再加壓縮／縮放。

## 6. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `models` | `attach_screenshot` round-trip；舊規則檔缺鍵 → 預設 `False`；`rule_to_dict` 含此鍵 |
| `vision` | `encode_png` 對小 BGR 影像回傳非空 bytes 且以 PNG magic `\x89PNG\r\n` 開頭 |
| `rule_engine` | `attach_screenshot=True` 且比對命中 → notifier 收到 `image_png`（非空 PNG bytes）；`attach_screenshot=False` → notifier 以單參數呼叫（無 image_png）；`encode_png` 拋例外 → 退純文字（notifier 單參數、不崩潰）；`stop_all`/`run_script` 動作忽略 image 照舊 |
| `discord_notify` | `post_discord` 帶 `image_png` → poster 收到 `multipart/form-data` content-type 且 body 含 `screenshot.png` 與 `payload_json`；不帶 → 維持 JSON；`make_notifier` 把 `image_png` 一路傳到 sender；既有 JSON／UA／不洩漏網址測試續過（更新 poster 簽名） |
| `rule_editor_model` | 勾「附截圖」→ `to_dict` 含 `attach_screenshot=True`；`from_rule` 由規則還原勾選 |
| `rule_editor` | 勾選框存在；勾選後存檔 → 規則 `attach_screenshot=True`；載入既有規則顯示對應勾選 |

既有以 `rule_from_dict({…})` 建規則、或注入單參數 notifier 的測試，因「不附圖時維持單參數呼叫」與「缺鍵預設 False」而續可用。

## 7. 非目標（YAGNI）

- GUI 通知內嵌顯示截圖（只上 Discord）。
- 上傳前壓縮／縮放／浮水印／畫框標註命中位置。
- 一次附多張圖、或附整個視窗＋區域兩張。
- 全域「所有通知都附圖」開關（已選每條規則各自設定）。
- 非規則來源通知（連續失敗警告）附圖（無自然對應畫面）。
