# 規則 Discord 通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 監看規則觸發 `notify` 時，除了寫進 GUI 日誌，若設定填了 Discord webhook 網址就同時把「訊息 + 時間」非同步 POST 到該 Discord 頻道。

**Architecture:** 傳輸與格式化放純模組 `core/discord_notify.py`（stdlib urllib，可注入測試）；`Settings` 加一欄 webhook 網址（空＝停用、向後相容）；設定頁加輸入框；`watch_controller` 把原本只進 GUI 的 notifier 包成「先 GUI、再 daemon thread 送 Discord」的扇出 notifier。規則模型不動。

**Tech Stack:** Python 3.13 / PySide6 / stdlib `urllib.request` + `threading` + `datetime`（**不新增任何套件**）/ pytest。

## Global Constraints

- 所有面向使用者訊息用**繁體中文**，沿用既有設定錯誤格式（例：`設定 xxx 不是…`）。
- **只用 stdlib**（urllib/threading/datetime/json）——不新增依賴，**打包 spec 不變**。
- **非阻塞**：Discord 送出走 daemon thread，絕不卡住規則輪詢迴圈；送出例外只記 log、**不得冒泡**。
- webhook 網址**留空＝停用**，行為與現況完全相同（回歸測試須守住）。
- **向後相容**：舊 `settings.json`（無 webhook 欄）須能載入，該欄回預設 `""`。
- **不得把 webhook 網址或內容寫進 log**。
- 檔案行尾 LF。
- 全程 TDD：先失敗測試 → 跑到失敗 → 最小實作 → 跑到通過 → commit。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/core/discord_notify.py` | 格式化、urllib 送出、扇出 notifier builder | Create |
| `src/keyboard_executor/app/settings.py` | `Settings.discord_webhook_url` + 驗證 | Modify |
| `src/keyboard_executor/app/settings_page.py` | webhook 輸入框 | Modify |
| `src/keyboard_executor/app/watch_controller.py` | 用扇出 notifier；接 webhook 參數 | Modify |
| `src/keyboard_executor/app/main_window.py` | 從設定帶 webhook 進 WatchController | Modify |
| 對應 `tests/…` | 各層測試 | Create/Modify |

執行順序即任務順序。

---

### Task 1: 格式化與送出 `discord_notify.format_message` / `post_discord`

**Files:**
- Create: `src/keyboard_executor/core/discord_notify.py`
- Test: `tests/core/test_discord_notify.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `format_message(message: str, when) -> str` — `when` 為 `datetime`；回 `f"{message}\n🕒 {when:%Y-%m-%d %H:%M:%S}"`。
  - `post_discord(webhook_url: str, content: str, *, poster=None, timeout: float = 5.0) -> None` — POST `{"content": content[:2000]}`；`poster(url, data_bytes, timeout)` 注入供測試，預設 urllib。

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_discord_notify.py`：
```python
import json
from datetime import datetime

from keyboard_executor.core.discord_notify import format_message, post_discord


def test_format_message_includes_message_and_time():
    out = format_message("驗證碼出現了", datetime(2026, 7, 8, 22, 30, 15))
    assert out == "驗證碼出現了\n🕒 2026-07-08 22:30:15"


def test_post_discord_posts_content_json_to_url():
    captured = {}

    def fake_poster(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["timeout"] = timeout

    post_discord("https://discord.com/api/webhooks/1/a", "嗨", poster=fake_poster)
    assert captured["url"] == "https://discord.com/api/webhooks/1/a"
    assert json.loads(captured["data"].decode("utf-8")) == {"content": "嗨"}
    assert captured["timeout"] == 5.0


def test_post_discord_truncates_to_2000_chars():
    captured = {}
    post_discord("https://x/webhooks/1/a", "x" * 5000,
                 poster=lambda u, d, t: captured.setdefault("data", d))
    assert len(json.loads(captured["data"].decode("utf-8"))["content"]) == 2000
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -v`
Expected: FAIL（`ModuleNotFoundError: keyboard_executor.core.discord_notify`）

- [ ] **Step 3: 最小實作**

`src/keyboard_executor/core/discord_notify.py`：
```python
"""Discord webhook 通知（純傳輸與格式化，無 Qt、無平台差異，可完整單元測試）。

只用 stdlib（urllib/threading/datetime/json），不新增依賴。傳輸例外由呼叫端隔離。"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

_MAX_LEN = 2000   # Discord 訊息內容上限


def format_message(message: str, when: datetime) -> str:
    """回傳要送到 Discord 的內容：訊息 + 觸發時間。"""
    return f"{message}\n🕒 {when:%Y-%m-%d %H:%M:%S}"


def _urllib_post(url: str, data: bytes, timeout: float) -> None:
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=timeout).close()


def post_discord(webhook_url: str, content: str, *, poster=None,
                 timeout: float = 5.0) -> None:
    """POST {"content": content}（截到 2000 字）到 webhook。poster 注入供測試。"""
    poster = poster or _urllib_post
    body = json.dumps({"content": content[:_MAX_LEN]}).encode("utf-8")
    poster(webhook_url, body, timeout)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/discord_notify.py tests/core/test_discord_notify.py
git commit -m "feat(discord): format_message 與 post_discord（urllib，可注入）"
```

---

### Task 2: 扇出 notifier `discord_notify.make_notifier`

**Files:**
- Modify: `src/keyboard_executor/core/discord_notify.py`
- Test: `tests/core/test_discord_notify.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: `format_message`、`post_discord`（Task 1）
- Produces: `make_notifier(base_notifier, webhook_url, *, dispatch=None, now=None, sender=post_discord) -> callable`。回傳 `notify(message)`：先 `base_notifier(message)`；若 `webhook_url` 非空，用 `dispatch` 執行 `sender(webhook_url, format_message(message, now()))`，`sender` 例外被吞並記 log。`dispatch` 預設丟 daemon thread；`now` 預設 `datetime.now`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_discord_notify.py` 末端新增：
```python
import logging

from keyboard_executor.core.discord_notify import make_notifier


def test_make_notifier_no_webhook_only_calls_base():
    calls = []
    n = make_notifier(lambda m: calls.append(("base", m)), "",
                      dispatch=lambda fn: fn(),
                      sender=lambda *a: calls.append(("send", a)))
    n("嗨")
    assert calls == [("base", "嗨")]          # 無 webhook → 不送 Discord


def test_make_notifier_with_webhook_fans_out_with_time():
    sent = []
    n = make_notifier(lambda m: None, "https://discord.com/api/webhooks/1/a",
                      dispatch=lambda fn: fn(),
                      now=lambda: datetime(2026, 7, 8, 22, 30, 15),
                      sender=lambda url, content: sent.append((url, content)))
    n("驗證碼出現了")
    assert sent == [("https://discord.com/api/webhooks/1/a",
                     "驗證碼出現了\n🕒 2026-07-08 22:30:15")]


def test_make_notifier_send_failure_is_isolated(caplog):
    calls = []

    def boom(*a):
        raise RuntimeError("網路掛了")

    n = make_notifier(lambda m: calls.append(m),
                      "https://discord.com/api/webhooks/1/a",
                      dispatch=lambda fn: fn(), sender=boom,
                      now=lambda: datetime(2026, 1, 1))
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        n("嗨")                                # 不應拋例外
    assert calls == ["嗨"]                     # base 仍執行
    assert "Discord" in caplog.text            # 失敗有記 log
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -k make_notifier -v`
Expected: FAIL（`ImportError: cannot import name 'make_notifier'`）

- [ ] **Step 3: 最小實作**

在 `src/keyboard_executor/core/discord_notify.py` 末端新增：
```python
def _daemon_dispatch(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _safe_send(sender, webhook_url: str, content: str) -> None:
    try:
        sender(webhook_url, content)
    except Exception:
        # 不記 webhook 網址與內容，只記事實（spec §8）；網路/HTTP 失敗不得中斷監看
        logger.warning("Discord 通知傳送失敗", exc_info=True)


def make_notifier(base_notifier, webhook_url: str, *, dispatch=None, now=None,
                  sender=post_discord):
    """把「只進 GUI」的 notifier 包成扇出：先 base_notifier，再（有 webhook 時）
    非同步送 Discord。dispatch/now/sender 注入供測試，預設 daemon thread + 現在時間。"""
    dispatch = dispatch or _daemon_dispatch
    now = now or datetime.now

    def notify(message: str) -> None:
        base_notifier(message)
        if webhook_url:
            content = format_message(message, now())
            dispatch(lambda: _safe_send(sender, webhook_url, content))

    return notify
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -v`
Expected: PASS（新增 3 項與 Task 1 的 3 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/discord_notify.py tests/core/test_discord_notify.py
git commit -m "feat(discord): make_notifier 扇出（GUI + 非同步 Discord，失敗隔離）"
```

---

### Task 3: 設定欄位 `Settings.discord_webhook_url` + 驗證

**Files:**
- Modify: `src/keyboard_executor/app/settings.py`
- Test: `tests/app/test_settings.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: 無
- Produces: `Settings` 新增 `discord_webhook_url: str = ""`；`validate_settings` 對非空值要求 `https://…/webhooks/…`，並 strip 正規化。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_settings.py` 末端新增：
```python
def test_discord_webhook_defaults_empty():
    assert Settings().discord_webhook_url == ""


def test_validate_accepts_valid_and_empty_webhook():
    ok = validate_settings(Settings(
        discord_webhook_url="https://discord.com/api/webhooks/1/abc"))
    assert ok.discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert validate_settings(Settings(discord_webhook_url="")).discord_webhook_url == ""


def test_validate_strips_and_rejects_malformed_webhook():
    stripped = validate_settings(Settings(
        discord_webhook_url="  https://discord.com/api/webhooks/1/abc  "))
    assert stripped.discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    with pytest.raises(ScriptValidationError, match="discord_webhook_url"):
        validate_settings(Settings(discord_webhook_url="http://example.com/nope"))


def test_load_old_settings_without_webhook_field(tmp_path):
    import json
    (tmp_path / "settings.json").write_text(json.dumps(
        {"toggle_key": "f9", "stop_key": "f10",
         "ocr_language": "auto", "log_level": "INFO"}), encoding="utf-8")
    assert SettingsStore(tmp_path).load().discord_webhook_url == ""
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings.py -k webhook -v`
Expected: FAIL（`TypeError: Settings.__init__() got an unexpected keyword argument 'discord_webhook_url'`）

- [ ] **Step 3: 最小實作**

3a. `Settings` dataclass（約 `settings.py:29`）加欄位：
```python
@dataclass(frozen=True)
class Settings:
    toggle_key: str = "f9"
    stop_key: str = "f10"
    ocr_language: str = "auto"
    log_level: str = "INFO"
    discord_webhook_url: str = ""
```

3b. `validate_settings`（約 `settings.py:37`）在 `log_level` 檢查後、`return` 前插入 webhook 驗證，並把它加進 `replace`：
```python
    webhook = settings.discord_webhook_url.strip()
    if webhook and not (webhook.startswith("https://") and "/webhooks/" in webhook):
        raise ScriptValidationError(
            f"設定 discord_webhook_url 不是合法的 Discord webhook 網址: {webhook!r}")
    return replace(settings, toggle_key=toggle, stop_key=stop,
                   discord_webhook_url=webhook)
```
（把原本的 `return replace(settings, toggle_key=toggle, stop_key=stop)` 換成上面這段。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings.py -v`
Expected: PASS（新增 4 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings.py tests/app/test_settings.py
git commit -m "feat(discord): Settings 加 discord_webhook_url 欄位與驗證"
```

---

### Task 4: 設定頁 webhook 輸入框

**Files:**
- Modify: `src/keyboard_executor/app/settings_page.py`
- Test: `tests/app/test_settings_page_widget.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: `Settings.discord_webhook_url`（Task 3）
- Produces: `SettingsPage.discord_edit`（QLineEdit）；`_on_save` 把它存進 `Settings`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_settings_page_widget.py` 末端新增：
```python
def test_settings_page_has_discord_field_default_empty(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    assert page.discord_edit.text() == ""


def test_settings_page_saves_discord_webhook(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store)
    page.discord_edit.setText("https://discord.com/api/webhooks/1/abc")
    page.save_button.click()
    assert store.load().discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert "已儲存" in page.status_label.text()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -k discord -v`
Expected: FAIL（`AttributeError: 'SettingsPage' object has no attribute 'discord_edit'`）

- [ ] **Step 3: 最小實作**

4a. `__init__` 在 OCR 欄位那列（約 `settings_page.py:38`）之後加：
```python
        self.discord_edit = QLineEdit(settings.discord_webhook_url)
        layout.addRow("Discord Webhook 網址（留空＝停用）", self.discord_edit)
```

4b. `_on_save`（約 `settings_page.py:63`）的 `Settings(...)` 加入該欄：
```python
            self._store.save(Settings(
                toggle_key=self.toggle_edit.text().strip(),
                stop_key=self.stop_edit.text().strip(),
                ocr_language=self.ocr_edit.text().strip(),
                log_level=self.level_combo.currentText(),
                discord_webhook_url=self.discord_edit.text().strip()))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_settings_page_widget.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/settings_page.py tests/app/test_settings_page_widget.py
git commit -m "feat(discord): 設定頁加 Discord Webhook 網址輸入框"
```

---

### Task 5: 接線 `watch_controller` + `main_window`

**Files:**
- Modify: `src/keyboard_executor/app/watch_controller.py`
- Modify: `src/keyboard_executor/app/main_window.py:73-78`
- Test: `tests/app/test_watch_controller.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: `discord_notify.make_notifier`（Task 2）、`Settings.discord_webhook_url`（Task 3）
- Produces: `WatchController.__init__` 新增 `discord_webhook_url: str = ""` 與 `notifier_factory=make_notifier`；`build_job` 把 `notifier` 換成 `notifier_factory(base_notifier, discord_webhook_url)`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_watch_controller.py` 末端新增（沿用檔內既有 `SpyEngine`、`SpyGuard`、`make_rule_storage`、`FakeInputHook`）：
```python
def test_build_job_wires_webhook_into_notifier_factory(tmp_path):
    captured = {}

    def fake_notifier_factory(base, webhook):
        captured["base"] = base
        captured["webhook"] = webhook
        return "SPY_NOTIFIER"

    controller = WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=lambda *a, **k: object(),
        hook_factory=FakeInputHook, guard_factory=SpyGuard,
        discord_webhook_url="https://discord.com/api/webhooks/1/abc",
        notifier_factory=fake_notifier_factory)
    records = []
    controller.build_job()(records.append)
    assert captured["webhook"] == "https://discord.com/api/webhooks/1/abc"
    assert SpyEngine.last.notifier == "SPY_NOTIFIER"     # 引擎拿到扇出後的 notifier
    captured["base"]("嗨")                                # base 仍把 notify 轉 progress
    assert records == [{"kind": "notify", "message": "嗨"}]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_watch_controller.py -k webhook -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'discord_webhook_url'`）

- [ ] **Step 3: 最小實作**

3a. `watch_controller.py` 匯入區加：
```python
from keyboard_executor.core.discord_notify import make_notifier
```

3b. `WatchController.__init__`（約 `watch_controller.py:23-26`）簽名加兩個參數並保存：
```python
    def __init__(self, rule_storage, script_storage, templates, *,
                 get_platform=get_platform, engine_factory=RuleEngine,
                 player_factory=Player, hook_factory=PynputInputHook,
                 guard_factory=SessionGuard, stop_key: str = "f10",
                 discord_webhook_url: str = "", notifier_factory=make_notifier):
```
在既有 `self._stop_key = stop_key` 後加：
```python
        self._discord_webhook_url = discord_webhook_url
        self._notifier_factory = notifier_factory
```

3c. `build_job` 內把原本的 `notifier=lambda message: progress(...)`（約 `watch_controller.py:55-56`）改成先建 base、再扇出：
```python
            def base_notifier(message):
                progress({"kind": "notify", "message": message})

            engine = self._engine_factory(
                platform, storage=self._script_storage, templates=self._templates,
                notifier=self._notifier_factory(base_notifier,
                                                self._discord_webhook_url),
                on_fire=lambda name, ttype: progress(
                    {"kind": "fire", "rule": name, "trigger": ttype}),
                on_error=lambda name, message: progress(
                    {"kind": "error", "message": f"規則「{name}」：{message}"}),
                player_factory=player_factory_with_stop,
                stop_event=stop_event)
```

3d. `main_window.py`（約 `:73-78`）的 `WatchController(...)` 加一行帶入設定：
```python
        self._watch_controller = (watch_controller if watch_controller is not None
                                  else WatchController(
                                      self._rule_storage, self._script_storage,
                                      self._template_store.load_template,
                                      get_platform=self._get_platform,
                                      stop_key=self._settings.stop_key,
                                      discord_webhook_url=self._settings.discord_webhook_url))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_watch_controller.py tests/app/test_main_window.py -v`
Expected: PASS（新增 1 項；既有 `test_on_fire_and_notifier_become_progress_records` 仍通過——webhook 預設空、扇出等同只呼叫 base）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/watch_controller.py src/keyboard_executor/app/main_window.py tests/app/test_watch_controller.py
git commit -m "feat(discord): 監看 notifier 扇出到 Discord（webhook 由設定帶入）"
```

---

### Task 6: 全套件回歸與收尾

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 + 新增約 12 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~5); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0（新檔與改檔皆 LF）。如有 CRLF 用 `sed -i 's/\r$//' <file>` 正規化後 `git add` 修補。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

**不需改打包 spec**（純 stdlib）。實作完成後重新打包 exe，於實機驗收：
1. Discord 頻道設定建 webhook → 複製網址 → 貼進設定頁「Discord Webhook 網址」→ 儲存 → 重啟。
2. 建一條 `notify` 規則（例如偵測 CAPTCHA），觸發後確認 Discord 頻道收到「訊息 + 🕒 時間」。
3. 網路中斷時觸發 → 監看不中斷、GUI 日誌照常、只是 Discord 沒送到。
此步驟在計畫外，由使用者驅動。
