# Discord 通知附辨識截圖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 規則觸發「顯示通知」時，若該規則勾了「附截圖」，把比對當下擷取的框選區域畫面當附件上傳到 Discord。

**Architecture:** `_matches` 把擷取的 BGR 影像連同 matched 一起回傳；`_fire_one` 的 notify 分支在 `rule.attach_screenshot` 時用 `vision.encode_png` 編碼並以 `notifier(msg, image_png=png)` 呼叫，否則維持單參數呼叫（既有 notifier/測試零影響）；`discord_notify` 收到 `image_png` 時改用 stdlib multipart 上傳。每條規則一個 `attach_screenshot` 開關（規則編輯器勾選框）。

**Tech Stack:** Python 3.13 / PySide6 / OpenCV(cv2) / PaddleOCR / pytest。PNG 用既有 cv2；multipart 用 stdlib（urllib）。

## Global Constraints

- 不新增第三方依賴：PNG 編碼用既有 cv2（在 `vision.py`）；multipart 用 stdlib；`discord_notify.py` 維持**不 import cv2/numpy**。
- **不附圖時維持 notifier 單參數呼叫**（`self._notifier(msg)`），既有 1 參數 notifier（cli、連續失敗警告、測試）零影響。
- 舊規則檔缺 `attach_screenshot` → 預設 `False`（向後相容）。
- multipart boundary 用固定常數 `----KeyboardExecutorBoundary`（可重現、好測試），不用亂數。
- Discord 傳送失敗只記「Discord 通知傳送失敗」，**不得洩漏 webhook 網址／訊息內容／影像**；`_build_request` 仍帶 `User-Agent: KeyboardExecutor/1.0`（避免 403）。
- 面向使用者訊息維持繁中。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/core/models.py` | `Rule` 加 `attach_screenshot` 欄位 + 序列化/遷移 | Modify |
| `src/keyboard_executor/core/vision.py` | 新純函式 `encode_png` | Modify |
| `src/keyboard_executor/core/rule_engine.py` | `_matches` 回傳影像；`_fire`/`_fire_one` 帶 image；notify 編碼附圖 | Modify |
| `src/keyboard_executor/core/discord_notify.py` | `notify`/`post_discord`/`_safe_send` 支援 `image_png` multipart | Modify |
| `src/keyboard_executor/app/rule_editor_model.py` | `attach_screenshot` 旗標 | Modify |
| `src/keyboard_executor/app/rule_editor.py` | 「附截圖」勾選框 | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

執行順序 **Task 1 → 5**：Task 3 依賴 Task 1（`Rule.attach_screenshot`）與 Task 2（`encode_png`）；Task 4 需在 Task 5（UI 能開啟旗標）之前，確保 production `make_notifier` 先支援 `image_png`。

---

### Task 1: `Rule.attach_screenshot` 欄位 + 序列化/遷移

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`Rule` 資料類別 520-533、`rule_from_dict` 605-633、`rule_to_dict` 648-658）
- Test: `tests/core/test_models_rule.py`

**Interfaces:**
- Produces: `Rule.attach_screenshot: bool`（預設 `False`）；`rule_from_dict` 讀 `"attach_screenshot"`（缺鍵 False）；`rule_to_dict` 輸出 `"attach_screenshot"`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_models_rule.py` 末端新增：
```python
def _min_rule_dict(**over):
    d = {"name": "r", "target_window": {"title_pattern": "x"},
         "condition": {"type": "text", "pattern": "p"},
         "triggers": [{"type": "notify", "message": "m"}]}
    d.update(over)
    return d


def test_attach_screenshot_defaults_false_when_absent():
    rule = rule_from_dict(_min_rule_dict())
    assert rule.attach_screenshot is False


def test_attach_screenshot_round_trips_and_serializes():
    rule = rule_from_dict(_min_rule_dict(attach_screenshot=True))
    assert rule.attach_screenshot is True
    assert rule_to_dict(rule)["attach_screenshot"] is True
    assert rule_from_dict(rule_to_dict(rule)).attach_screenshot is True


def test_attach_screenshot_must_be_bool():
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_min_rule_dict(attach_screenshot="yes"))
```
（`pytest`、`rule_from_dict`、`rule_to_dict`、`ScriptValidationError` 皆已於檔頭 import。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py -k "attach_screenshot" -v`
Expected: FAIL（`TypeError: unexpected keyword`／`AttributeError: attach_screenshot`／`_check_no_extra` 拒絕多餘鍵）

- [ ] **Step 3: 最小實作**

3a. `models.py` 的 `Rule` 資料類別，在 `enabled: bool = True`（528 行）之後加一欄：
```python
    enabled: bool = True
    attach_screenshot: bool = False
```

3b. `rule_from_dict` 的 `_check_no_extra` 允許鍵集合（605-607 行）加入 `"attach_screenshot"`：
```python
    _check_no_extra(data, "規則", {"name", "target_window", "region", "condition",
                                   "interval_sec", "cooldown_sec", "trigger",
                                   "triggers", "enabled", "attach_screenshot"})
```

3c. `rule_from_dict` 在 `enabled` 驗證（629-631 行）之後、`return Rule(...)` 之前加：
```python
    attach_screenshot = data.get("attach_screenshot", False)
    if not isinstance(attach_screenshot, bool):
        _err("規則欄位 attach_screenshot 必須是布林值")
```
並把 `return Rule(...)`（632-633 行）補上此參數：
```python
    return Rule(name=name, target_window=target, condition=condition, triggers=triggers,
                region=region, interval_sec=interval, cooldown_sec=cooldown,
                enabled=enabled, attach_screenshot=attach_screenshot)
```

3d. `rule_to_dict` 的回傳 dict（648-658 行），在 `"enabled": rule.enabled,` 之後加一行：
```python
        "enabled": rule.enabled,
        "attach_screenshot": rule.attach_screenshot,
    }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py -v`
Expected: PASS（新增 3 項與既有全數；既有 round-trip 測試因兩側都 `attach_screenshot=False` 仍相等）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_rule.py
git commit -m "feat(rule): Rule 加 attach_screenshot 欄位（舊規則檔預設 False）"
```

---

### Task 2: `vision.encode_png`

**Files:**
- Modify: `src/keyboard_executor/core/vision.py`（新增函式；檔頭已 `import cv2`、`import numpy as np`）
- Test: `tests/core/test_vision.py`（檔頭已 `import cv2`、`import numpy as np`）

**Interfaces:**
- Produces: `encode_png(image_bgr: np.ndarray) -> bytes`。編碼失敗拋 `ValueError`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_vision.py` 末端新增（並把檔頭 import 補上 `encode_png`）：
```python
def test_encode_png_returns_png_magic_bytes():
    from keyboard_executor.core.vision import encode_png
    data = encode_png(np.zeros((4, 4, 3), dtype=np.uint8))
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:8]) == b"\x89PNG\r\n\x1a\n"   # PNG 檔頭 magic
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_vision.py -k "encode_png" -v`
Expected: FAIL（`ImportError: cannot import name 'encode_png'`）

- [ ] **Step 3: 最小實作**

`vision.py` 末端新增：
```python
def encode_png(image_bgr: np.ndarray) -> bytes:
    """BGR 影像編碼成 PNG bytes（沿用 OpenCV BGR 慣例，顏色正確）。編碼失敗拋 ValueError。"""
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ValueError("PNG 編碼失敗")
    return buf.tobytes()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_vision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/vision.py tests/core/test_vision.py
git commit -m "feat(vision): encode_png 把 BGR 影像編成 PNG bytes"
```

---

### Task 3: 引擎 `_matches` 回傳影像、notify 動作附截圖

**Files:**
- Modify: `src/keyboard_executor/core/rule_engine.py`（`evaluate_once` 51-79、`_matches` 107-132、`_fire` 134-138、`_fire_one` 140-158；檔頭 import）
- Test: `tests/core/test_rule_engine.py`（檔頭已 `import numpy as np`、`from ...models import rule_from_dict`；helper `make_platform`/`tbox`/`Clock`/`DictStorage`/`FakeScreenCapture`/`FakeOcrEngine`）

**Interfaces:**
- Consumes: `Rule.attach_screenshot`（Task 1）、`encode_png`（Task 2）。
- Produces: `_matches(rule) -> (bool, np.ndarray | None)`；`_fire(rule, image)`；`_fire_one(rule, trig, image)`；notify 動作在 `attach_screenshot` 時以 `self._notifier(msg, image_png=<PNG bytes>)` 呼叫，否則 `self._notifier(msg)`。

**注意**：`_matches` 目前只有 `evaluate_once` 一個呼叫者（先 `grep -n "\._matches\|def _matches" src tests` 確認無其他呼叫者/直接斷言）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_rule_engine.py` 末端新增：
```python
def _screenshot_rule(attach):
    return rule_from_dict({
        "name": "截圖規則", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "斷線"}],
        "attach_screenshot": attach})


def test_attach_screenshot_passes_png_to_notifier():
    received = []

    def notifier(message, *, image_png=None):
        received.append((message, image_png))

    engine = RuleEngine(
        make_platform(FakeScreenCapture(image=np.zeros((4, 4, 3), np.uint8)),
                      FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=notifier, clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=True)])
    assert len(received) == 1
    msg, png = received[0]
    assert msg == "斷線"
    assert png is not None and bytes(png[:8]) == b"\x89PNG\r\n\x1a\n"


def test_no_attach_calls_notifier_single_arg():
    calls = []
    # 單參數 notifier：若引擎傳了 image_png 會 TypeError，此測即證明走單參數路徑。
    engine = RuleEngine(
        make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=lambda message: calls.append(message),
        clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=False)])
    assert calls == ["斷線"]


def test_encode_failure_falls_back_to_text_notify(monkeypatch):
    import keyboard_executor.core.rule_engine as re_mod
    received = []

    def boom(_img):
        raise RuntimeError("encode 壞了")

    def notifier(message, *, image_png=None):
        received.append((message, image_png))

    monkeypatch.setattr(re_mod, "encode_png", boom)
    engine = RuleEngine(
        make_platform(FakeScreenCapture(image=np.zeros((4, 4, 3), np.uint8)),
                      FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=notifier, clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=True)])   # 不崩潰
    assert received == [("斷線", None)]                     # 退回純文字（無 image_png）
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py -k "attach or encode_failure" -v`
Expected: FAIL（notify 目前只呼叫 `self._notifier(trig.message)`，`received` 內 `image_png` 為 None；`test_attach_screenshot_passes_png_to_notifier` 斷言 PNG 失敗）

- [ ] **Step 3: 最小實作**

3a. `rule_engine.py` 檔頭 import（18 行 `from ...vision import ...`）加入 `encode_png`：
```python
from keyboard_executor.core.vision import count_color_pixels, encode_png, find_text, match_template
```

3b. `_matches`（107-132 行）改為回傳 `(matched, image)`。把方法簽名與各 return 改成：
```python
    def _matches(self, rule: Rule):
        wm = self._platform.window_manager
        windows = wm.find_windows(title_pattern=rule.target_window.title_pattern,
                                  app_name=rule.target_window.app_name)
        if not windows:
            return False, None
        win = windows[0]
        cap = self._platform.screen_capture
        scale = cap.scale_factor()
        if rule.region is None:
            rx, ry, rw, rh = 0, 0, win.width, win.height
        else:
            rx, ry, rw, rh = rule.region
        rect = Rect(round((win.x + rx) * scale), round((win.y + ry) * scale),
                    round(rw * scale), round(rh * scale))
        image = cap.capture(rect)
        if rule.condition.type == "text":
            boxes = self._platform.ocr_engine.recognize(image)
            return find_text(boxes, rule.condition.pattern,
                             rule.condition.mode) is not None, image
        if rule.condition.type == "color":
            c = rule.condition
            count = count_color_pixels(image, c.hue, c.sat, c.val,
                                       c.hue_tol, c.sat_tol, c.val_tol)
            matched = count < c.min_pixels if c.absent else count >= c.min_pixels
            return matched, image
        template = self._templates(rule.condition.template)
        return match_template(image, template,
                              threshold=rule.condition.threshold).found, image
```

3c. `evaluate_once`（59-74 行）改為解包 tuple 並把 image 傳給 `_fire`：
```python
            try:
                matched, image = self._matches(rule)
                self._fail_streak[rule.name] = 0
            except Exception as e:
                matched, image = False, None
                self._log_failure(rule, e)
                self._record_failure(rule)
            self._next_due[rule.name] = self._clock() + rule.interval_sec
            if not matched:
                continue
            last = self._last_fired.get(rule.name)
            if last is not None and now - last < rule.cooldown_sec:
                continue
            self._last_fired[rule.name] = now
            try:
                self._fire(rule, image)
            except Exception as e:
                self._log_fire_failure(rule, e)
```

3d. `_fire`（134-138 行）與 `_fire_one`（140-158 行）帶入 image；notify 分支附截圖：
```python
    def _fire(self, rule: Rule, image) -> None:
        if self._on_fire is not None:
            self._on_fire(rule.name, "+".join(t.type for t in rule.triggers))
        for trig in rule.triggers:
            # 每個動作各自隔離：前面的動作失敗不可讓後面的動作（尤其 stop_all）漏做。
            try:
                self._fire_one(rule, trig, image)
            except Exception as e:
                self._log_fire_failure(rule, e)

    def _fire_one(self, rule: Rule, trig: RuleTrigger, image) -> None:
        if trig.type == "run_script":
            player = self._player_factory(self._platform, storage=self._storage,
                                          templates=self._templates)
            result = player.play(self._storage.load(trig.script_name))
            if not result.ok:
                logger.error("規則 %r 觸發腳本 %r 中止：%s",
                             rule.name, trig.script_name, result.error)
                self._emit_error(rule, f"觸發腳本 {trig.script_name!r} 中止：{result.error}")
        elif trig.type == "stop_all":
            self.stop_event.set()
            if self._on_stop_all is not None:
                self._on_stop_all()
        elif trig.type == "notify" and self._notifier is not None:
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

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py -v`
Expected: PASS（新增 3 項與既有全數；既有多動作/例外隔離測試因 `attach_screenshot` 預設 False 走單參數 notifier 路徑，不受影響）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/rule_engine.py tests/core/test_rule_engine.py
git commit -m "feat(rule-engine): notify 動作在 attach_screenshot 時附上辨識截圖"
```

---

### Task 4: `discord_notify` multipart 上傳

**Files:**
- Modify: `src/keyboard_executor/core/discord_notify.py`（`_build_request` 19-22、`_urllib_post` 25-26、`post_discord` 29-34、`_safe_send` 41-47、`make_notifier` 50-61）
- Test: `tests/core/test_discord_notify.py`

**Interfaces:**
- Consumes: 引擎以 `notify(message, image_png=<PNG bytes>)` 呼叫（Task 3）。
- Produces: `notify(message, *, image_png=None)`；`post_discord(webhook_url, content, *, image_png=None, poster=None, timeout=5.0)`；poster seam 簽名 `(url, data, timeout, content_type)`。

- [ ] **Step 1: 寫失敗測試 + 更新既有 seam 簽名**

先更新既有測試的注入簽名（poster 多收 `content_type`、sender 多收 `image_png`），避免 Task 4 契約改動使其誤失敗：
- 第 10 行 `def fake_poster(url, data, timeout):` → `def fake_poster(url, data, timeout, content_type):`
- 第 24 行 `poster=lambda u, d, t: ...` → `poster=lambda u, d, t, c: captured.setdefault("data", d)`
- 第 42 行 `sender=lambda url, content: sent.append((url, content))` → `sender=lambda url, content, image_png=None: sent.append((url, content))`
- 第 50 行 `def boom(*a):` → `def boom(*a, **k):`
- 第 68 行 `def raising_sender(webhook_url, content):` → `def raising_sender(webhook_url, content, image_png=None):`

再於檔案末端新增：
```python
def test_post_discord_with_image_sends_multipart():
    captured = {}

    def poster(url, data, timeout, content_type):
        captured["data"] = data
        captured["content_type"] = content_type

    post_discord("https://x/webhooks/1/a", "嗨", image_png=b"\x89PNGdata",
                 poster=poster)
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="payload_json"' in captured["data"]
    assert b'filename="screenshot.png"' in captured["data"]
    assert b"\x89PNGdata" in captured["data"]           # 影像 bytes 有進 body


def test_make_notifier_forwards_image_png_to_sender():
    sent = []
    n = make_notifier(lambda m: None, "https://x/webhooks/1/a",
                      dispatch=lambda fn: fn(),
                      sender=lambda url, content, image_png=None: sent.append(image_png))
    n("嗨", image_png=b"PNGDATA")
    assert sent == [b"PNGDATA"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -k "multipart or forwards_image" -v`
Expected: FAIL（`post_discord`/`notify` 尚不接受 `image_png`：`TypeError: unexpected keyword argument 'image_png'`）

- [ ] **Step 3: 最小實作**

改寫 `discord_notify.py` 的以下部分（其餘不動）：

3a. 模組常數區（`_USER_AGENT` 之後）加 boundary：
```python
_USER_AGENT = "KeyboardExecutor/1.0"
_BOUNDARY = "----KeyboardExecutorBoundary"
```

3b. `_build_request`（19-22 行）content-type 參數化（預設 JSON，保留既有 UA 測試）：
```python
def _build_request(url: str, data: bytes,
                   content_type: str = "application/json") -> urllib.request.Request:
    return urllib.request.Request(
        url, data=data,
        headers={"Content-Type": content_type, "User-Agent": _USER_AGENT})
```

3c. `_urllib_post`（25-26 行）帶 content_type：
```python
def _urllib_post(url: str, data: bytes, timeout: float,
                 content_type: str = "application/json") -> None:
    urllib.request.urlopen(_build_request(url, data, content_type), timeout=timeout).close()
```

3d. 新增 multipart 組裝純函式（放在 `post_discord` 之前）：
```python
def _build_multipart(content: str, image_png: bytes) -> bytes:
    """組 Discord webhook 的 multipart/form-data：payload_json + files[0]=screenshot.png。"""
    b = _BOUNDARY
    payload = json.dumps({"content": content[:_MAX_LEN]}).encode("utf-8")
    return b"".join([
        f"--{b}\r\n".encode(),
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        payload,
        f"\r\n--{b}\r\n".encode(),
        b'Content-Disposition: form-data; name="files[0]"; filename="screenshot.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        image_png,
        f"\r\n--{b}--\r\n".encode(),
    ])
```

3e. `post_discord`（29-34 行）分流 JSON / multipart：
```python
def post_discord(webhook_url: str, content: str, *, image_png: bytes | None = None,
                 poster=None, timeout: float = 5.0) -> None:
    """POST 到 webhook：有 image_png 走 multipart（附截圖），否則 JSON。poster 注入供測試。"""
    poster = poster or _urllib_post
    if image_png is None:
        body = json.dumps({"content": content[:_MAX_LEN]}).encode("utf-8")
        poster(webhook_url, body, timeout, "application/json")
    else:
        body = _build_multipart(content, image_png)
        poster(webhook_url, body, timeout, f"multipart/form-data; boundary={_BOUNDARY}")
```

3f. `_safe_send`（41-47 行）帶 image_png：
```python
def _safe_send(sender, webhook_url: str, content: str, image_png: bytes | None = None) -> None:
    try:
        sender(webhook_url, content, image_png=image_png)
    except Exception:
        logger.warning("Discord 通知傳送失敗", exc_info=True)
```

3g. `make_notifier`（50-61 行）的 `notify` 帶 image_png：
```python
def make_notifier(base_notifier, webhook_url: str, *, dispatch=None,
                  sender=post_discord):
    dispatch = dispatch or _daemon_dispatch

    def notify(message: str, *, image_png: bytes | None = None) -> None:
        base_notifier(message)
        if webhook_url:
            dispatch(lambda: _safe_send(sender, webhook_url, message, image_png))

    return notify
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_discord_notify.py -v`
Expected: PASS（新增 2 項與既有全數；既有 JSON/UA/不洩漏測試因 poster/sender 簽名已更新續過）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/discord_notify.py tests/core/test_discord_notify.py
git commit -m "feat(discord): 有截圖時改用 multipart 上傳（payload_json + screenshot.png）"
```

---

### Task 5: 規則編輯器「附截圖」勾選框

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor_model.py`（`__init__` 26-52、`from_rule` 54-86、`to_dict` 88-123）
- Modify: `src/keyboard_executor/app/rule_editor.py`（`message_edit` 之後 144-145、`_apply_to_model` 226-249）
- Test: `tests/app/test_rule_editor_model.py`、`tests/app/test_rule_editor_widget.py`

**Interfaces:**
- Consumes: `Rule.attach_screenshot`（Task 1）。
- Produces: `RuleEditorModel.attach_screenshot: bool`；`RuleEditorDialog.attach_screenshot_check`（`QCheckBox`）；`to_dict()` 含 `"attach_screenshot"`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_rule_editor_model.py` 末端新增：
```python
def test_attach_screenshot_flag_serializes_to_dict():
    model = RuleEditorModel()
    model.name = "r"
    model.title_pattern = "x"
    model.pattern = "p"
    model.notify_enabled = True
    model.message = "m"
    model.attach_screenshot = True
    assert model.to_dict()["attach_screenshot"] is True


def test_from_rule_restores_attach_screenshot():
    rule = rule_from_dict(_min_attach_rule(True))
    assert RuleEditorModel.from_rule(rule).attach_screenshot is True


def _min_attach_rule(attach):
    return {"name": "r", "target_window": {"title_pattern": "x"},
            "condition": {"type": "text", "pattern": "p"},
            "triggers": [{"type": "notify", "message": "m"}],
            "attach_screenshot": attach}
```

在 `tests/app/test_rule_editor_widget.py` 末端新增：
```python
def test_attach_screenshot_checkbox_saves(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("附圖規則")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("斷線了")
    dialog.attach_screenshot_check.setChecked(True)
    dialog.save_button.click()
    assert storage.load("附圖規則").attach_screenshot is True


def test_attach_screenshot_checkbox_reflects_loaded_rule(qapp, tmp_path):
    model = RuleEditorModel()
    model.attach_screenshot = True
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path))
    assert dialog.attach_screenshot_check.isChecked() is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py -k "attach_screenshot" -v`
Expected: FAIL（`RuleEditorModel` 無 `attach_screenshot`；`dialog` 無 `attach_screenshot_check`）

- [ ] **Step 3: 最小實作**

3a. `rule_editor_model.py` 的 `__init__`，在 `self.enabled = True`（52 行）之前加：
```python
        self.attach_screenshot = False
        self.enabled = True
```

3b. `from_rule`，在 `model.enabled = rule.enabled`（85 行）之前加：
```python
        model.attach_screenshot = rule.attach_screenshot
        model.enabled = rule.enabled
```

3c. `to_dict`，在 `data["triggers"] = triggers`（122 行）之後、`return data` 之前加：
```python
        data["attach_screenshot"] = self.attach_screenshot
        return data
```

3d. `rule_editor.py`，在 `layout.addRow("通知訊息", self.message_edit)`（145 行）之後加：
```python
        self.attach_screenshot_check = QCheckBox("附上辨識截圖到 Discord 通知")
        self.attach_screenshot_check.setChecked(model.attach_screenshot)
        layout.addRow("", self.attach_screenshot_check)
```

3e. `rule_editor.py` 的 `_apply_to_model`，在 `m.enabled = self.enabled_check.isChecked()`（249 行）之前加：
```python
        m.attach_screenshot = self.attach_screenshot_check.isChecked()
        m.enabled = self.enabled_check.isChecked()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py -v`
Expected: PASS（新增 4 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor_model.py src/keyboard_executor/app/rule_editor.py tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py
git commit -m "feat(rule-editor): 每條規則加「附上辨識截圖到 Discord 通知」勾選框"
```

---

### Task 6: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 632 + 新增約 12 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~5); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後，連同先前的「立即停止」「規則多動作觸發」「OCR CPU 節流」一起重新打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序，避免 cv2.pyd 鎖檔）。實機驗收：設一條文字規則、勾「附上辨識截圖到 Discord 通知」、填 webhook，觸發後應在 Discord 看到通知訊息＋一張框選區域截圖。此步驟在計畫外，由使用者驅動。
