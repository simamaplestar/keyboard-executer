# 組合鍵可設定按住時間（hold_ms）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `key_combo`（組合鍵）動作可設定按住毫秒數（`hold_ms`）；預設 0 維持現有固定 40ms（遊戲偵測），>0 由 Player 託管、可被緊急停止中斷。

**Architecture:** 完全比照既有 `key_press` 的 `hold_ms`。把「依序按下/反序放開」做成 `InputBackend` 的具體方法 `key_combo_down`/`key_combo_up`（以既有抽象 `key_down`/`key_up` 實作，兩後端靠多型自動正確）；`key_combo`(40ms) 改用它們；Player `KEY_COMBO` 分支比照 `KEY_PRESS`。

**Tech Stack:** Python 3.13、pytest（`QT_QPA_PLATFORM=offscreen` for GUI tests）、pynput / pydirectinput 後端。

## Global Constraints

- 單位一律**毫秒 ms**（與 `key_press` 一致）；`hold_ms` 預設 **0**，最小 0。
- `hold_ms == 0` → 走現有 `backend.key_combo`（固定 40ms `_COMBO_HOLD`，遊戲偵測不變）；`> 0` → Player 託管 `key_combo_down` → 可中斷 `self._sleep(hold_ms/1000)` → `finally key_combo_up`。
- `key_combo_down` 依序按下全部鍵、`key_combo_up` 反序放開；以 `self.key_down`/`self.key_up` 實作於 base（非 abstract），子類不需各自實作。
- 所有使用者可見字串繁體中文。舊腳本無 `hold_ms` → 預設 0 → 行為完全不變。
- 每步 TDD、小步提交。測試指令：`QT_QPA_PLATFORM=offscreen python.exe -m pytest <files> -q`（native-Windows venv）。

---

## 檔案結構

- `src/keyboard_executor/core/models.py` — `key_combo` 驗證加 `hold_ms`、`action_label` 顯示按住（Task 1）
- `src/keyboard_executor/platforms/base.py` — `InputBackend.key_combo_down`/`key_combo_up`（具體）（Task 2）
- `src/keyboard_executor/platforms/common/input_pynput.py` — `key_combo` 改用 down/up（Task 2）
- `src/keyboard_executor/platforms/win32/input.py` — 刪 `key_combo` 覆寫、移除 `_COMBO_HOLD` import（Task 2）
- `src/keyboard_executor/core/player.py` — `KEY_COMBO` 分支 hold 處理（Task 3）
- `src/keyboard_executor/app/action_fields.py` — `FIELD_SPECS["key_combo"]` 加 `hold_ms`（Task 4）
- `src/keyboard_executor/app/script_editor.py` — `_chip_spec` key_combo 顯示按住（Task 4）

---

## Task 1: 動作模型 — `key_combo` 的 `hold_ms`

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`_validate_key_combo` 約 110–120；`action_label` KEY_COMBO 分支約 679–680）
- Test: `tests/core/test_models_script.py`

**Interfaces:**
- Produces: `key_combo` action params 含 `hold_ms: int`（預設 0，minimum 0）；`action_label` 有 hold 時顯示「（按住 Xms）」。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/core/test_models_script.py`）

```python
def test_key_combo_hold_ms_default_and_validation():
    from keyboard_executor.core.models import action_from_dict, action_label
    a = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"]})
    assert a.params["hold_ms"] == 0
    a2 = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000})
    assert a2.params["hold_ms"] == 2000
    assert action_label(a2) == "組合鍵 ctrl+s（按住 2000ms）"
    assert action_label(a) == "組合鍵 ctrl+s"
    with pytest.raises(ScriptValidationError, match="hold_ms"):
        action_from_dict({"type": "key_combo", "keys": ["a"], "hold_ms": -1})
    with pytest.raises(ScriptValidationError, match="hold_ms"):
        action_from_dict({"type": "key_combo", "keys": ["a"], "hold_ms": 1.5})
```

（`test_models_script.py` 已 import `pytest`、`ScriptValidationError`；若無 `action_from_dict`/`action_label` 於既有 import，於本測試內就地 import，如上。）

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/core/test_models_script.py -q`
Expected: FAIL（`key_combo` 無 `hold_ms`／`_check_no_extra` 擋掉 `hold_ms`）。

- [ ] **Step 3: 實作 `models.py`**

`_validate_key_combo`：
```python
def _validate_key_combo(p: dict) -> dict:
    _check_no_extra(p, "動作 key_combo", {"keys", "hold_ms"})
    keys = p.get("keys")
    if not isinstance(keys, list) or not keys:
        _err("動作 key_combo 欄位 keys 必須是至少一個按鍵的清單")
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            _err("動作 key_combo 欄位 keys 型別錯誤：每個按鍵必須是非空字串")
        if not is_valid_key(k):
            _err(f"動作 key_combo 欄位 keys 不是可用的按鍵名稱: {k!r}")
    return {"keys": list(keys),
            "hold_ms": _get_int(p, "動作 key_combo", "hold_ms", minimum=0, default=0,
                                required=False)}
```

`action_label` 的 KEY_COMBO 分支：
```python
    if t is ActionType.KEY_COMBO:
        combo = "組合鍵 " + "+".join(p["keys"])
        return f"{combo}（按住 {p['hold_ms']}ms）" if p["hold_ms"] else combo
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/core/test_models_script.py -q`
Expected: PASS（既有 key_combo 測試續過；無 hold_ms 者帶預設 0）。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_script.py
git commit -m "feat(models): key_combo 動作支援 hold_ms（按住時間）"
```

---

## Task 2: 後端 — `key_combo_down`/`key_combo_up`（base 具體）＋ pynput/win32 套用

**Files:**
- Modify: `src/keyboard_executor/platforms/base.py`（`InputBackend`，`key_combo` 抽象宣告後）
- Modify: `src/keyboard_executor/platforms/common/input_pynput.py`（`key_combo` 約 45–51）
- Modify: `src/keyboard_executor/platforms/win32/input.py`（刪 `key_combo` 約 53–60；import 約 13）
- Test: `tests/platforms/test_input_pynput.py`（既有 `tests/platforms/test_win32_input.py` 應續過）

**Interfaces:**
- Consumes: 既有抽象 `InputBackend.key_down`/`key_up`。
- Produces: `InputBackend.key_combo_down(keys)`（依序 `self.key_down`）、`key_combo_up(keys)`（反序 `self.key_up`）；`key_combo` = down + `_sleep(_COMBO_HOLD)` + up。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/platforms/test_input_pynput.py`）

```python
def test_key_combo_down_presses_in_order():
    backend, kb, _, _ = make_backend()
    backend.key_combo_down(["ctrl", "s"])
    assert kb.ops == [("press", Key.ctrl), ("press", KeyCode.from_char("s"))]


def test_key_combo_up_releases_in_reverse():
    backend, kb, _, _ = make_backend()
    backend.key_combo_up(["ctrl", "s"])
    assert kb.ops == [("release", KeyCode.from_char("s")), ("release", Key.ctrl)]


def test_key_combo_is_down_hold_up():
    backend, kb, _, sleeps = make_backend()
    backend.key_combo(["ctrl", "s"])
    s = KeyCode.from_char("s")
    assert kb.ops == [("press", Key.ctrl), ("press", s),
                      ("release", s), ("release", Key.ctrl)]
    assert sleeps == [0.04]     # _COMBO_HOLD
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/platforms/test_input_pynput.py -q`
Expected: 前兩個新測試 FAIL（無 `key_combo_down`/`key_combo_up`）。

- [ ] **Step 3: base.py 加具體方法**

在 `InputBackend` 的 `key_combo` 抽象宣告之後加：
```python
    def key_combo_down(self, keys: list[str]) -> None:
        """依序按下全部鍵（不放開）。按住多久由呼叫端掌控。"""
        for k in keys:
            self.key_down(k)

    def key_combo_up(self, keys: list[str]) -> None:
        """反序放開全部鍵。"""
        for k in reversed(keys):
            self.key_up(k)
```

- [ ] **Step 4: pynput 的 key_combo 改用 down/up**

`input_pynput.py` 的 `key_combo` 改為：
```python
    def key_combo(self, keys: list[str]) -> None:
        self.key_combo_down(keys)
        self._sleep(_COMBO_HOLD)          # 預設 40ms：讓輪詢式遊戲抓得到同時按下
        self.key_combo_up(keys)
```

- [ ] **Step 5: win32 刪除 key_combo 覆寫**

`win32/input.py`：
- 刪除整個 `key_combo` 方法（約 53–60 行）——改繼承 pynput 版；`self.key_combo_down`→`self.key_down`（game mode 走 pdi.keyDown）、`self.key_combo_up`→`self.key_up`（pdi.keyUp），行為與原 pdi 順序一致。
- import 由 `from keyboard_executor.platforms.common.input_pynput import _COMBO_HOLD, _SETTLE, PynputInputBackend` 改為 `from keyboard_executor.platforms.common.input_pynput import _SETTLE, PynputInputBackend`（`_COMBO_HOLD` 不再直接使用）。

- [ ] **Step 6: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py -q`
Expected: PASS（含既有 `test_key_combo_releases_in_reverse_order`、`test_key_combo_holds_before_release`、win32 `test_game_mode_key_combo_releases_in_reverse`——行為不變）。

- [ ] **Step 7: 提交**

```bash
git add src/keyboard_executor/platforms/base.py src/keyboard_executor/platforms/common/input_pynput.py src/keyboard_executor/platforms/win32/input.py tests/platforms/test_input_pynput.py
git commit -m "feat(input): 後端加 key_combo_down/up（base 具體），win32 免覆寫"
```

---

## Task 3: 執行 — Player `KEY_COMBO` 分支的 hold 處理

**Files:**
- Modify: `src/keyboard_executor/core/player.py`（`_run_one` 的 KEY_COMBO 分支約 303–305）
- Test: `tests/core/test_player_basic.py`

**Interfaces:**
- Consumes: `backend.key_combo_down`/`key_combo_up`（Task 2）、`p["hold_ms"]`（Task 1）、可中斷 `self._sleep`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/core/test_player_basic.py`；比照既有 `test_key_press_hold_uses_key_down_wait_key_up`）

```python
def test_key_combo_hold_uses_combo_down_wait_up():
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 300}]))
    assert backend.calls == [("key_down", "ctrl"), ("key_down", "s"),
                             ("key_up", "s"), ("key_up", "ctrl")]
    assert sleeps == [0.3]


def test_key_combo_no_hold_uses_key_combo():
    platform, backend, _ = make_platform()
    Player(platform).play(make_script([{"type": "key_combo", "keys": ["ctrl", "s"]}]))
    assert backend.calls == [("key_combo", ["ctrl", "s"])]


def test_key_combo_hold_releases_and_aborts_on_stop():
    platform, backend, _ = make_platform()
    stop = threading.Event()

    def sleep_then_stop(seconds):
        stop.set()             # 模擬 hold 途中按下停止

    result = Player(platform, stop_event=stop, sleep=sleep_then_stop).play(
        make_script([{"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 500},
                     {"type": "key_press", "key": "b"}]))
    assert backend.calls == [("key_down", "ctrl"), ("key_down", "s"),
                             ("key_up", "s"), ("key_up", "ctrl")]   # 放開、b 未送
    assert result.ok is False                                       # 停止後中止
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/core/test_player_basic.py -q`
Expected: `test_key_combo_hold_*` FAIL（舊 player 對所有 key_combo 都呼叫 `backend.key_combo`，記錄為 `("key_combo", ...)` 而非 key_down/up）。`test_key_combo_no_hold_uses_key_combo` 可能已過（無妨，作為回歸保護）。

- [ ] **Step 3: 實作 `player.py` KEY_COMBO 分支**

```python
        elif atype is ActionType.KEY_COMBO:
            self._ensure_alive(win)
            keys = list(p["keys"])
            if p["hold_ms"] > 0:
                # 長按由 Player 掌管：可中斷 _sleep 撐住，finally 保證放鍵，
                # 停止途中不卡鍵、放鍵後由下一個 _check_stop 中止。
                backend.key_combo_down(keys)
                try:
                    self._sleep(p["hold_ms"] / 1000)
                finally:
                    backend.key_combo_up(keys)
            else:
                backend.key_combo(keys)          # 維持固定 40ms（遊戲偵測）
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/core/test_player_basic.py tests/core/test_player_flow.py tests/core/test_player_alive.py -q`
Expected: PASS（含既有 `test_runs_keyboard_actions_in_order` 等走 `hold_ms==0` 分支者）。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_basic.py
git commit -m "feat(player): key_combo hold_ms>0 走可中斷的 down/hold/up"
```

---

## Task 4: UI — 編輯器 key_combo 加「按住(ms)」欄與 chip 顯示

**Files:**
- Modify: `src/keyboard_executor/app/action_fields.py`（`FIELD_SPECS["key_combo"]` 約 20）
- Modify: `src/keyboard_executor/app/script_editor.py`（`_chip_spec` key_combo 分支約 60–61）
- Test: `tests/app/test_action_fields.py`、`tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `key_combo` 的 `hold_ms`（Task 1）；既有 `("hold_ms", "int")` 的 `FIELD_LABELS`／coerce。

- [ ] **Step 1: 寫失敗測試**

加到 `tests/app/test_action_fields.py`：
```python
def test_key_combo_hold_ms_field_coerced():
    from keyboard_executor.app.action_fields import to_action_dict
    assert to_action_dict("key_combo", {"keys": "ctrl+s", "hold_ms": "2000"}) == {
        "type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000}
    # 空 hold_ms → 省略（讓 models 帶預設 0）
    assert to_action_dict("key_combo", {"keys": "ctrl+s", "hold_ms": ""}) == {
        "type": "key_combo", "keys": ["ctrl", "s"]}
```

在 `tests/app/test_script_editor_widget.py` 的 `test_chip_spec_shows_hold_and_kind` 末尾加兩行斷言：
```python
    assert _chip_spec({"type": "key_combo", "keys": ["ctrl", "s"]}) == (
        "CTRL+S", "組合鍵", "key")
    assert _chip_spec({"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000}) == (
        "CTRL+S", "組合鍵，按住 2000ms", "key")
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_action_fields.py tests/app/test_script_editor_widget.py -q -k "hold or chip"`
Expected: FAIL（`FIELD_SPECS["key_combo"]` 無 hold_ms；`_chip_spec` key_combo 不含按住）。

- [ ] **Step 3: `action_fields.py` 加欄位**

`FIELD_SPECS` 的 `"key_combo"` 由 `[("keys", "keys")]` 改為：
```python
    "key_combo": [("keys", "keys"), ("hold_ms", "int")],
```

- [ ] **Step 4: `script_editor.py` chip 顯示按住**

`_chip_spec` 的 key_combo 分支改為：
```python
    if t == "key_combo":
        hold = d.get("hold_ms", 0)
        keys = "+".join(str(k).upper() for k in d.get("keys", []))
        return keys, (f"組合鍵，按住 {hold}ms" if hold else "組合鍵"), "key"
```

- [ ] **Step 5: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest tests/app/test_action_fields.py tests/app/test_script_editor_widget.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/app/action_fields.py src/keyboard_executor/app/script_editor.py tests/app/test_action_fields.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor): key_combo 加按住(ms)欄與 chip 顯示"
```

---

## 收尾：全套件驗證

- [ ] **執行完整測試套件**

Run: `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest -q`
Expected: 全綠（716 passed / 4 skipped 之上加本計畫新增測試）。
