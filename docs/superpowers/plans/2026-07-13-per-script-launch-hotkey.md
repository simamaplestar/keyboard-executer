# 每腳本啟動快捷鍵（＋多鍵組合錄製＋緊急停止不停監看）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每個腳本可設定一個啟動快捷鍵（單鍵或組合鍵），按下即以背景輪詢（遊戲/背景亦有效）執行該腳本並先停現有回放；組合鍵錄製支援 3 鍵以上；緊急停止只中止回放、不再停監看。

**Architecture:** 熱鍵存進 `ScriptSettings.hotkey`；`vk_for_key` 補修飾鍵並新增 `hotkey_to_vks`；新 `ScriptHotkeyPoller`（多綁定 GetAsyncKeyState 輪詢）上升緣經 Qt Signal 排到 GUI 執行緒；主視窗把回放抽成共用 `_run_script(name)`（熱鍵先停再跑）、開機/清單/設定變動時重建綁定。另兩項相關調整：`_KeyCaptureEdit` combo 改「累積＋放開才定案」；拆除監看的緊急停止 guard 並讓 `_on_emergency_hotkey` 只停回放。

**Tech Stack:** Python 3.13、PySide6/Qt6、ctypes（GetAsyncKeyState）、pytest（`QT_QPA_PLATFORM=offscreen`）。

## Global Constraints

- 所有使用者可見字串一律繁體中文。
- 修飾鍵 VK：`ctrl`/`control`=0x11、`shift`=0x10、`alt`=0x12、`win`/`super`/`cmd`=0x5B。
- 熱鍵 canonical 名稱以 `+` 相接，修飾鍵固定序 **ctrl、alt、shift、win** 在前，主鍵在後（小寫）。
- 輪詢間隔固定 `0.03`（30ms），與 `AsyncKeyStopPoller` 一致。
- Windows-only 的 poller/hotkey：非 `win32` 或 `QApplication.platformName()=="offscreen"` 一律守門 no-op，`self._script_hotkey_poller` 為 `None`。
- 去重「先出現者贏」依 `ScriptStorage.list_names()`（`sorted()`）的順序。
- 熱鍵 vk 清單**含**緊急停止鍵（含在組合裡也算）→ 略過該綁定並記一行警告。
- 每步 TDD；小步提交。測試以 `QT_QPA_PLATFORM=offscreen <venv-py> -m pytest` 執行（見 windows-build-env 記憶）。

---

## 檔案結構

- `src/keyboard_executor/core/models.py` — `ScriptSettings.hotkey` 欄位/驗證/序列化（Task 1）
- `src/keyboard_executor/app/global_hotkey.py` — `vk_for_key` 修飾鍵 ＋ `hotkey_to_vks`（Task 2）
- `src/keyboard_executor/app/key_stop_poller.py` — 公開 `win_key_down`（Task 3）
- `src/keyboard_executor/app/script_hotkey_poller.py`（新）— `ScriptHotkeyPoller`（Task 3）
- `src/keyboard_executor/app/script_editor_model.py` — `hotkey` 存取器（Task 4）
- `src/keyboard_executor/app/script_editor.py` — 「啟動快捷鍵」欄位（Task 5）
- `src/keyboard_executor/app/main_window.py` — 熱鍵接線（Task 6）＋緊急停止只停回放（Task 8）
- `src/keyboard_executor/app/key_capture.py` — 多鍵累積錄製（Task 7）
- `src/keyboard_executor/app/watch_controller.py` — 移除緊急停止 guard（Task 8）

---

## Task 1: `ScriptSettings.hotkey` 欄位、驗證、序列化

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`ScriptSettings` 40 行處的 dataclass；`_validate_settings` 約 428–457；`script_to_dict` 約 478–490）
- Test: `tests/core/test_models_script.py`

**Interfaces:**
- Produces: `ScriptSettings.hotkey: str`（預設 `""`）；驗證：以 `+` 拆開每個非空部分須 `is_valid_key`，正規化為小寫 `+` 相接；`script_to_dict` 的 `settings` 含 `"hotkey"`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/core/test_models_script.py` 末尾）

```python
def test_settings_hotkey_default_empty():
    assert script_from_dict(minimal()).settings.hotkey == ""


def test_settings_hotkey_accepts_single_and_combo():
    assert script_from_dict(minimal(settings={"hotkey": "f5"})).settings.hotkey == "f5"
    assert script_from_dict(
        minimal(settings={"hotkey": "ctrl+shift+1"})).settings.hotkey == "ctrl+shift+1"
    assert script_from_dict(minimal(settings={"hotkey": "  "})).settings.hotkey == ""  # 空＝不設


def test_settings_hotkey_rejects_bad_key_and_type():
    with pytest.raises(ScriptValidationError, match="hotkey"):
        script_from_dict(minimal(settings={"hotkey": "ctrl+nope"}))
    with pytest.raises(ScriptValidationError, match="hotkey"):
        script_from_dict(minimal(settings={"hotkey": 5}))
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/core/test_models_script.py -q`
Expected: 三個新測試 FAIL（`ScriptSettings` 無 `hotkey`／`_check_no_extra` 擋掉 `hotkey`）。

- [ ] **Step 3: 實作 `models.py`**

在 `ScriptSettings` dataclass 加欄位（於 `window_retry_interval_ms` 之後）：

```python
@dataclass(frozen=True)
class ScriptSettings:
    speed: float = 1.0
    repeat: int = 1
    humanize_jitter_pct: int = 0
    game_input_mode: bool = True
    window_retry: int = 0
    window_retry_interval_ms: int = 1000
    hotkey: str = ""
```

`_validate_settings`：把 `"hotkey"` 加進 `allowed`，並在回傳前加入驗證與正規化：

```python
    allowed = {"speed", "repeat", "humanize_jitter_pct", "game_input_mode",
               "window_retry", "window_retry_interval_ms", "hotkey"}
```

```python
    hotkey = data.get("hotkey", defaults.hotkey)
    if not isinstance(hotkey, str):
        _err("settings.hotkey 必須是字串")
    hotkey_parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    for part in hotkey_parts:
        if not is_valid_key(part):
            _err(f"settings.hotkey 不是可用的按鍵名稱: {part!r}")
    hotkey = "+".join(hotkey_parts)
    return ScriptSettings(speed=float(speed), repeat=repeat, humanize_jitter_pct=jitter,
                          game_input_mode=game, window_retry=retry,
                          window_retry_interval_ms=interval, hotkey=hotkey)
```

`script_to_dict` 的 `settings` dict 加一鍵：

```python
        "settings": {"speed": s.speed, "repeat": s.repeat,
                     "humanize_jitter_pct": s.humanize_jitter_pct,
                     "game_input_mode": s.game_input_mode,
                     "window_retry": s.window_retry,
                     "window_retry_interval_ms": s.window_retry_interval_ms,
                     "hotkey": s.hotkey},
```

- [ ] **Step 4: 更新既有 round-trip 測試**（`script_to_dict` 現在會多輸出 `hotkey`）

把 `tests/core/test_models_script.py` 的 `test_round_trip` 期望 settings dict 補上 `"hotkey": ""`：

```python
        "settings": {"speed": 2.0, "repeat": 3, "humanize_jitter_pct": 10,
                     "game_input_mode": True,
                     "window_retry": 0, "window_retry_interval_ms": 1000,
                     "hotkey": ""},
```

- [ ] **Step 5: 執行全部 models 測試**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/core/test_models_script.py -q`
Expected: PASS（含新測試與更新後的 round-trip）。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_script.py
git commit -m "feat(models): ScriptSettings 新增 hotkey 欄位（啟動快捷鍵）"
```

---

## Task 2: `vk_for_key` 修飾鍵 ＋ `hotkey_to_vks`

**Files:**
- Modify: `src/keyboard_executor/app/global_hotkey.py`（`vk_for_key` 約 29–42）
- Test: `tests/app/test_global_hotkey.py`

**Interfaces:**
- Consumes: 無。
- Produces: `vk_for_key` 對 `ctrl/control/shift/alt/win/super/cmd` 回修飾鍵 VK；`hotkey_to_vks(hotkey: str) -> list[int] | None`（任一部分無法對應或字串為空 → None）。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_global_hotkey.py`）

```python
def test_vk_for_key_modifiers():
    assert vk_for_key("ctrl") == 0x11
    assert vk_for_key("control") == 0x11
    assert vk_for_key("shift") == 0x10
    assert vk_for_key("alt") == 0x12
    assert vk_for_key("win") == 0x5B
    assert vk_for_key("super") == 0x5B
    assert vk_for_key("cmd") == 0x5B


def test_hotkey_to_vks():
    from keyboard_executor.app.global_hotkey import hotkey_to_vks
    assert hotkey_to_vks("ctrl+shift+1") == [0x11, 0x10, 0x31]
    assert hotkey_to_vks("f5") == [0x74]
    assert hotkey_to_vks("shift+a+right") == [0x10, ord("A"), 0x27]
    assert hotkey_to_vks("ctrl+nope") is None
    assert hotkey_to_vks("") is None
    assert hotkey_to_vks("  ") is None
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_global_hotkey.py -q`
Expected: 兩個新測試 FAIL。

- [ ] **Step 3: 實作 `global_hotkey.py`**

在 `_VK_SPECIAL` 之後新增修飾鍵表：

```python
_VK_MODIFIERS = {
    "ctrl": 0x11, "control": 0x11,   # VK_CONTROL
    "shift": 0x10,                    # VK_SHIFT
    "alt": 0x12,                      # VK_MENU
    "win": 0x5B, "super": 0x5B, "cmd": 0x5B,   # VK_LWIN
}
```

`vk_for_key` 於 `n = name.strip().lower()` 之後、`_VK_SPECIAL` 判斷之前加入修飾鍵查詢：

```python
def vk_for_key(name: str) -> int | None:
    """canonical 按鍵名（keynames）→ Windows 虛擬鍵碼（VK）；無法對應回 None。"""
    n = name.strip().lower()
    if n in _VK_MODIFIERS:
        return _VK_MODIFIERS[n]
    if n in _VK_SPECIAL:
        return _VK_SPECIAL[n]
    if n.startswith("f") and n[1:].isdigit():
        num = int(n[1:])
        if 1 <= num <= 24:
            return 0x70 + (num - 1)          # VK_F1=0x70 … VK_F24=0x87
    if len(n) == 1:
        ch = n.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)                   # 字母/數字的 VK == ASCII 大寫
    return None
```

在 `vk_for_key` 之後新增：

```python
def hotkey_to_vks(hotkey: str) -> list[int] | None:
    """熱鍵字串（如 'ctrl+shift+1' 或 'f5'）→ 每個按鍵的 VK 清單；
    任一部分無法對應、或字串為空 → None。"""
    parts = [p for p in (hotkey or "").split("+") if p.strip()]
    if not parts:
        return None
    vks: list[int] = []
    for p in parts:
        vk = vk_for_key(p)
        if vk is None:
            return None
        vks.append(vk)
    return vks
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_global_hotkey.py -q`
Expected: PASS（既有 `test_vk_for_key_mapping` 續過）。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/global_hotkey.py tests/app/test_global_hotkey.py
git commit -m "feat(hotkey): vk_for_key 支援修飾鍵，新增 hotkey_to_vks"
```

---

## Task 3: `ScriptHotkeyPoller`（多綁定 GetAsyncKeyState 輪詢）

**Files:**
- Modify: `src/keyboard_executor/app/key_stop_poller.py`（公開 `win_key_down`）
- Create: `src/keyboard_executor/app/script_hotkey_poller.py`
- Test: `tests/app/test_script_hotkey_poller.py`

**Interfaces:**
- Consumes: `win_key_down`（key_stop_poller）。
- Produces: `ScriptHotkeyPoller(on_trigger, *, key_down_fn=None, sleep=None, poll_interval=0.03)`；`.start(bindings)->bool`（`bindings`: `Iterable[(name, [vk,...])]`，至少一個有效綁定才啟動）；`.stop()`；每綁定「整組鍵皆按下」上升緣呼叫 `on_trigger(name)`。

- [ ] **Step 1: 公開 `win_key_down`（key_stop_poller.py）**

把 `_win_key_down` 改名為 `win_key_down` 並保留舊名別名（既有預設引用不變）：

```python
def win_key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


_win_key_down = win_key_down   # 既有引用（AsyncKeyStopPoller 預設）相容
```

- [ ] **Step 2: 寫失敗測試**（新檔 `tests/app/test_script_hotkey_poller.py`）

```python
from keyboard_executor.app.script_hotkey_poller import ScriptHotkeyPoller


def test_start_false_when_no_bindings():
    p = ScriptHotkeyPoller(lambda name: None,
                           key_down_fn=lambda vk: False, sleep=lambda s: None)
    assert p.start([]) is False
    assert p._thread is None


def test_fires_name_once_per_rising_edge_not_while_held():
    fired = []
    states = iter([False, False, True, True, False, True])  # 上升緣在 index 2、5
    poller = None
    n = {"i": 0}

    def key_down_fn(vk):
        return next(states)

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 6:
            poller.stop()   # 從輪詢執行緒自身呼叫 → 不得自我 join

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    assert poller.start([("甲", [0x41])]) is True
    poller._thread.join(timeout=2)
    assert fired == ["甲", "甲"]     # 兩次上升緣各一次；按著不放不重複


def test_combo_fires_only_when_all_keys_down():
    fired = []
    rounds = [
        {0x11: True, 0x41: False},   # ctrl 下、a 未下 → 不觸發
        {0x11: True, 0x41: True},    # 兩鍵皆下 → 上升緣觸發一次
        {0x11: True, 0x41: True},    # 仍皆下 → 不重複
    ]
    idx = {"r": 0}
    poller = None

    def key_down_fn(vk):
        return rounds[idx["r"]].get(vk, False)

    def fake_sleep(_):
        idx["r"] += 1
        if idx["r"] >= len(rounds):
            poller.stop()
            idx["r"] = len(rounds) - 1     # 防越界

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    poller.start([("組", [0x11, 0x41])])
    poller._thread.join(timeout=2)
    assert fired == ["組"]


def test_multiple_bindings_independent():
    fired = []
    rounds = [
        {0x41: True, 0x42: False},   # 只有甲(a)上升 → fire 甲
        {0x41: True, 0x42: True},    # 乙(b)上升 → fire 乙（甲維持按著不重複）
    ]
    idx = {"r": 0}
    poller = None

    def key_down_fn(vk):
        return rounds[idx["r"]].get(vk, False)

    def fake_sleep(_):
        idx["r"] += 1
        if idx["r"] >= len(rounds):
            poller.stop()
            idx["r"] = len(rounds) - 1

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    poller.start([("甲", [0x41]), ("乙", [0x42])])
    poller._thread.join(timeout=2)
    assert fired == ["甲", "乙"]
```

- [ ] **Step 3: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_hotkey_poller.py -q`
Expected: FAIL（模組不存在）。

- [ ] **Step 4: 實作 `script_hotkey_poller.py`**

```python
"""Windows 系統級腳本啟動熱鍵：背景輪詢 GetAsyncKeyState，多綁定版。

沿用 AsyncKeyStopPoller 的作法（讀 OS async 按鍵狀態表，不經焦點/hook，遊戲中亦常
有效），但同時監看多個「腳本 → 按鍵組合」綁定：某綁定的所有鍵同時按下的上升緣 →
on_trigger(腳本名)。若遊戲在核心層過濾鍵盤則此法亦無效（接受）。僅 Windows 使用。
"""
from __future__ import annotations

import logging
import threading
import time

from keyboard_executor.app.key_stop_poller import win_key_down

logger = logging.getLogger(__name__)


class ScriptHotkeyPoller:
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None,
                 poll_interval: float = 0.03):
        self._on_trigger = on_trigger          # callable(script_name: str)
        self._key_down_fn = key_down_fn or win_key_down
        self._sleep = sleep or time.sleep
        self._poll_interval = poll_interval
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._bindings: list[tuple[str, tuple[int, ...]]] = []

    def start(self, bindings) -> bool:
        """bindings: Iterable[(script_name, [vk, ...])]；至少一個有效綁定才啟動並回 True。"""
        self._bindings = [(name, tuple(vks)) for name, vks in bindings if vks]
        if not self._bindings:
            return False
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_flag.set()
        t = self._thread
        # 從輪詢執行緒自己呼叫 stop() 時不能 join 自己（RuntimeError）；設旗標即可。
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        prev = {name: False for name, _ in self._bindings}
        while not self._stop_flag.is_set():
            for name, vks in self._bindings:
                try:
                    down = all(self._key_down_fn(vk) for vk in vks)
                except Exception:
                    logger.warning("腳本熱鍵輪詢讀取失敗", exc_info=True)
                    down = False
                if down and not prev.get(name, False):
                    try:
                        self._on_trigger(name)
                    except Exception:
                        logger.exception("腳本熱鍵觸發處理失敗")
                prev[name] = down
            self._sleep(self._poll_interval)
```

- [ ] **Step 5: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_hotkey_poller.py tests/app/test_key_stop_poller.py -q`
Expected: PASS（含 key_stop_poller 既有測試，確認改名不破壞）。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/app/key_stop_poller.py src/keyboard_executor/app/script_hotkey_poller.py tests/app/test_script_hotkey_poller.py
git commit -m "feat(hotkey): 新增 ScriptHotkeyPoller 多綁定背景輪詢"
```

---

## Task 4: `ScriptEditorModel` hotkey 存取器

**Files:**
- Modify: `src/keyboard_executor/app/script_editor_model.py`（`new()` 的 `_settings` 約 56–58；鏡射 `game_input_mode` 的 property 約 83–88）
- Test: `tests/app/test_script_editor_model.py`

**Interfaces:**
- Consumes: `ScriptSettings.hotkey`（Task 1）。
- Produces: `ScriptEditorModel.hotkey`（property）與 `set_hotkey(value)`；`new()` 預設 `hotkey=""`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_model.py`）

```python
def test_new_script_hotkey_defaults_empty():
    assert ScriptEditorModel.new("g").hotkey == ""


def test_set_hotkey_writes_settings():
    model = ScriptEditorModel.new("g")
    model.set_target("Test", "")
    model.insert(0, {"type": "delay", "ms": 100})
    model.set_hotkey("ctrl+shift+a")
    assert model.hotkey == "ctrl+shift+a"
    assert model.to_script().settings.hotkey == "ctrl+shift+a"
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_model.py -q`
Expected: 兩個新測試 FAIL。

- [ ] **Step 3: 實作 `script_editor_model.py`**

`new()` 的 `_settings` 字面值加 `"hotkey": ""`：

```python
        obj._settings = {"speed": 1.0, "repeat": 1, "humanize_jitter_pct": 0,
                         "game_input_mode": True, "window_retry": 0,
                         "window_retry_interval_ms": 1000, "hotkey": ""}
```

在 `set_game_input_mode` 之後加入 property 與 setter：

```python
    @property
    def hotkey(self) -> str:
        return str(self._settings.get("hotkey", ""))

    def set_hotkey(self, value: str) -> None:
        self._settings["hotkey"] = value or ""
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_model.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/script_editor_model.py tests/app/test_script_editor_model.py
git commit -m "feat(editor): ScriptEditorModel 新增 hotkey 存取器"
```

---

## Task 5: 腳本編輯器「啟動快捷鍵」欄位

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（`game_mode_check` 之後約 535；`_on_save` 約 1072–1076）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `ScriptEditorModel.hotkey`/`set_hotkey`（Task 4）；`_KeyCaptureEdit`（已 import）。
- Produces: `ScriptEditorDialog.hotkey_edit`（`_KeyCaptureEdit(combo=True)`）；`_on_save` 寫入 `settings.hotkey`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`）

```python
def test_editor_has_hotkey_field_reflecting_model(qapp, tmp_path):
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "settings": {"hotkey": "ctrl+f5"},
        "actions": [{"type": "key_press", "key": "a"}]})
    dialog = ScriptEditorDialog(ScriptEditorModel(script), ScriptStorage(tmp_path))
    assert dialog.hotkey_edit.text() == "ctrl+f5"


def test_editor_saves_hotkey(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]})
    dialog = ScriptEditorDialog(ScriptEditorModel(script), storage)
    dialog.hotkey_edit.setText("shift+a+right")
    dialog._on_save()
    assert storage.load("甲").settings.hotkey == "shift+a+right"
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_widget.py -q`
Expected: 兩個新測試 FAIL（無 `hotkey_edit`）。

- [ ] **Step 3: 加入欄位**（`script_editor.py`，在 `game_mode_check` 的 `layout.addWidget(self.game_mode_check)` 之後）

```python
        hk_row = QHBoxLayout()
        hk_row.addWidget(QLabel("啟動快捷鍵"))
        self.hotkey_edit = _KeyCaptureEdit(combo=True)
        self.hotkey_edit.setText(model.hotkey)
        hk_row.addWidget(self.hotkey_edit, 1)
        layout.addLayout(hk_row)
```

- [ ] **Step 4: `_on_save` 寫入**（在 `self._model.set_game_input_mode(...)` 之後）

```python
        self._model.set_hotkey(self.hotkey_edit.text())
```

- [ ] **Step 5: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_widget.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(editor): 腳本編輯器加入啟動快捷鍵欄位"
```

---

## Task 6: 主視窗接線（共用 `_run_script`、綁定建置、poller 生命週期）

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`（Signal 約 47；`__init__` 約 87–102；`_on_run_clicked`/`_cleanup_worker` 約 427–466；`_apply_settings` 約 687–688；`closeEvent` 約 726–736）
- Test: `tests/app/test_main_window.py`

**Interfaces:**
- Consumes: `hotkey_to_vks`、`vk_for_key`（Task 2）；`ScriptHotkeyPoller`（Task 3）；`ScriptSettings.hotkey`（Task 1）；`Worker.wait()`。
- Produces: `script_hotkey_requested = Signal(str)`；`_run_script(name)`；`_build_script_bindings()`；`_refresh_script_hotkeys()`；`_setup_script_hotkeys()`。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_main_window.py`）

```python
class RunningWorker:
    """模擬仍在跑的 worker：只需 wait()（_cleanup_worker 用 getattr 守門其餘訊號）。"""

    def __init__(self):
        self.waited = 0

    def wait(self, timeout_ms=5000):
        self.waited += 1
        return True


def test_hotkey_signal_runs_named_script(qapp, tmp_path):
    window = make_window(tmp_path)                 # storage 內有「甲」
    window.script_hotkey_requested.emit("甲")
    assert "開始回放：甲" in window.log_view.toPlainText()


def test_run_script_stops_running_worker_before_new_run(qapp, tmp_path):
    controller = FakeRunController()
    window = make_window(tmp_path, controller=controller)
    running = RunningWorker()
    window._worker = running                        # 模擬有腳本正在跑
    window._run_script("甲")
    assert controller.stopped == 1                  # 先送停止
    assert running.waited == 1                      # 等舊 worker 結束
    assert "開始回放：甲" in window.log_view.toPlainText()   # 再跑新的


def test_build_script_bindings_dedup_and_skips(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)

    def save(name, hotkey):
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "x"},
            "settings": {"hotkey": hotkey},
            "actions": [{"type": "key_press", "key": "a"}]}))

    save("s1_ctrl_a", "ctrl+a")     # 排序在前 → 拿走 ctrl+a
    save("s2_ctrl_a", "ctrl+a")     # 與 s1 同鍵 → 去重略過
    save("s3_stopkey", "f10")       # == 緊急停止鍵（預設 f10）→ 略過
    save("s4_ok", "f6")             # OK
    save("s5_none", "")             # 無熱鍵 → 略過
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=FakeRunController(),
                        worker_factory=ImmediateWorker)
    bindings = dict(window._build_script_bindings())
    assert "s1_ctrl_a" in bindings and "s2_ctrl_a" not in bindings
    assert "s3_stopkey" not in bindings
    assert "s4_ok" in bindings
    assert "s5_none" not in bindings
    assert bindings["s1_ctrl_a"] == [0x11, ord("A")]
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_main_window.py -q`
Expected: 三個新測試 FAIL。

- [ ] **Step 3: 加 Signal 與初始化**

類別屬性（`emergency_stop_requested = Signal()` 之後）：

```python
    script_hotkey_requested = Signal(str)   # 背景輪詢器請求執行某腳本（排到 GUI 執行緒）
```

`__init__`：在 `self._key_poller = None` 之後加：

```python
        self._script_hotkey_poller = None   # Windows 腳本啟動熱鍵背景輪詢
```

在 `self.emergency_stop_requested.connect(self._on_emergency_hotkey)` 之後加：

```python
        self.script_hotkey_requested.connect(self._run_script)
```

在 `self._setup_key_poller()`（約 102）之後加：

```python
        self._setup_script_hotkeys()
```

`refresh_scripts()` 尾端加重建（`__init__` 早於 setup 時 poller 為 None → 守門 no-op）：

```python
    def refresh_scripts(self) -> None:
        self.script_list.clear()
        self.script_list.addItems(self._scripts.refresh())
        self._refresh_script_hotkeys()
```

- [ ] **Step 4: 抽出 `_run_script` 與改寫 `_cleanup_worker`**

把 `_on_run_clicked` 改為委派、抽出 `_run_script`：

```python
    def _on_run_clicked(self) -> None:
        self._run_script(self._scripts.selected)

    def _run_script(self, name) -> None:
        if name is None:
            self.append_log("請先選取要執行的腳本")
            return
        try:
            job = self._run_controller.build_job(name)
        except ScriptValidationError as e:
            self.append_log(f"腳本載入失敗：{e}")
            return
        # 先停現在跑的、再跑新的；_cleanup_worker 收尾會把 self._worker 設 None，
        # 故非 None 即代表仍在跑（熱鍵可在腳本執行中切換）。
        if self._worker is not None:
            self._run_controller.stop()
            self._cleanup_worker()
        stop_key = self._settings.stop_key.upper()
        self.append_log(f"開始回放：{name}（{stop_key} 或滑鼠甩到螢幕左上角可緊急停止）")
        worker = self._worker_factory(job)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_run_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker = worker                    # 保留引用，避免執行中被 GC
        self.run_button.setEnabled(False)
        worker.start()
```

改寫 `_cleanup_worker`（斷開舊 worker 訊號、歸零 `self._worker`；`getattr` 守門假 worker）：

```python
    def _cleanup_worker(self) -> None:
        """收尾：斷開舊 worker 訊號、等背景執行緒結束、把 self._worker 歸零，
        避免舊 worker 的 finished/failed 在新 worker 就位後回頭誤觸，也讓
        「self._worker 非 None 即在跑」的判斷成立。"""
        w = self._worker
        if w is None:
            return
        for attr, slot in (("progress", self._on_progress),
                           ("finished", self._on_run_finished),
                           ("failed", self._on_worker_failed)):
            sig = getattr(w, attr, None)      # 假 worker（如 SpyWorker）可能沒有訊號
            if sig is not None:
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        w.wait()
        self._worker = None
```

- [ ] **Step 5: 加 poller 設定、綁定建置、重建**

在 `_setup_key_poller` 之後新增三個方法：

```python
    def _setup_script_hotkeys(self) -> None:
        """Windows：背景輪詢每個腳本的啟動熱鍵（GetAsyncKeyState），
        上升緣經 script_hotkey_requested 排到 GUI 執行緒執行該腳本。"""
        if sys.platform != "win32":
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None or app.platformName() == "offscreen":
                return
            from keyboard_executor.app.script_hotkey_poller import ScriptHotkeyPoller
            self._script_hotkey_poller = ScriptHotkeyPoller(
                self.script_hotkey_requested.emit)
            self._refresh_script_hotkeys()
        except Exception:
            logger.warning("腳本啟動熱鍵無法啟用", exc_info=True)

    def _build_script_bindings(self) -> list[tuple[str, list[int]]]:
        """從所有腳本的 settings.hotkey 建綁定；去重（先出現者贏）、略過含緊急停止鍵者
        與無法對應者。回傳 [(腳本名, [vk,...])]。"""
        from keyboard_executor.app.global_hotkey import hotkey_to_vks, vk_for_key
        stop_vk = vk_for_key(self._settings.stop_key)
        claimed: set[frozenset[int]] = set()
        bindings: list[tuple[str, list[int]]] = []
        for name in self._scripts.names:          # list_names() 已排序 → 先出現者贏
            try:
                hk = self._script_storage.load(name).settings.hotkey.strip()
            except ScriptValidationError:
                continue
            if not hk:
                continue
            vks = hotkey_to_vks(hk)
            if vks is None:
                logger.warning("腳本「%s」啟動熱鍵 %s 有無法對應的按鍵，略過", name, hk)
                continue
            if stop_vk is not None and stop_vk in vks:
                logger.warning("腳本「%s」啟動熱鍵 %s 含緊急停止鍵，略過", name, hk)
                continue
            key = frozenset(vks)
            if key in claimed:
                logger.warning("腳本「%s」啟動熱鍵 %s 與其他腳本重複，略過", name, hk)
                continue
            claimed.add(key)
            bindings.append((name, vks))
        return bindings

    def _refresh_script_hotkeys(self) -> None:
        poller = self._script_hotkey_poller
        if poller is None:
            return
        poller.stop()
        bindings = self._build_script_bindings()
        if bindings:
            poller.start(bindings)
```

- [ ] **Step 6: `_apply_settings` 與 `closeEvent` 掛入**

`_apply_settings` 尾端（`self._refresh_hotkey_labels()` 之後）加：

```python
        self._refresh_script_hotkeys()   # stop_key 若改變，撞停止鍵而略過的熱鍵可能重新可用
```

`closeEvent`（在停 `_key_poller` 附近）加：

```python
        if self._script_hotkey_poller is not None:
            self._script_hotkey_poller.stop()
```

- [ ] **Step 7: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_main_window.py -q`
Expected: PASS（含既有 run/close 測試——`_cleanup_worker` 改動對 `SpyWorker`/`ImmediateWorker` 行為等價）。

- [ ] **Step 8: 提交**

```bash
git add src/keyboard_executor/app/main_window.py tests/app/test_main_window.py
git commit -m "feat(hotkey): 主視窗接線腳本啟動快捷鍵（先停再跑、綁定去重）"
```

---

## Task 7: 多鍵組合錄製（`_KeyCaptureEdit` 累積＋放開才定案）

**Files:**
- Modify: `src/keyboard_executor/app/key_capture.py`（`_KeyCaptureEdit` `__init__`/`_start`/`keyPressEvent`；新增 `keyReleaseEvent`/`_commit`；模組常數）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `_qt_key_to_name`、`_modifier_names`（同檔既有）。
- Produces: combo 模式輸出多鍵組合（如 `shift+a+right`）；單鍵模式不變。

- [ ] **Step 1: 寫失敗測試**（加到 `tests/app/test_script_editor_widget.py`；於檔頭 `_kp` 之後加 `_kr`）

```python
def _kr(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    return QKeyEvent(QEvent.Type.KeyRelease, key, mods, text)


def test_key_capture_edit_records_multi_key_combo(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    shift = Qt.KeyboardModifier.ShiftModifier
    w.keyPressEvent(_kp(Qt.Key.Key_Shift, shift))
    w.keyPressEvent(_kp(Qt.Key.Key_A, shift, "a"))
    w.keyPressEvent(_kp(Qt.Key.Key_Right, shift))
    assert w.text() == ""                       # 尚未放開 → 未定案
    w.keyReleaseEvent(_kr(Qt.Key.Key_Right, shift))
    assert w.text() == "shift+a+right"


def test_key_capture_combo_ignores_autorepeat(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    rep = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                    Qt.KeyboardModifier.NoModifier, "a", True)   # autoRepeat=True
    w.keyPressEvent(rep)
    w.keyReleaseEvent(_kr(Qt.Key.Key_A, text="a"))
    assert w.text() == ""                       # autorepeat 的 press 被忽略 → 不定案
```

並把既有 `test_key_capture_edit_records_combo` 改為放開才定案：

```python
def test_key_capture_edit_records_combo(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    w.keyPressEvent(_kp(Qt.Key.Key_S, mods, "s"))
    w.keyReleaseEvent(_kr(Qt.Key.Key_S, mods, "s"))
    assert w.text() == "ctrl+shift+s"
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_widget.py -q -k key_capture`
Expected: 新測試 FAIL、改寫後的 combo 測試 FAIL（尚未放開才定案）。

- [ ] **Step 3: 實作 `key_capture.py`**

模組層（`_F1` 附近）加常數：

```python
_ALL_MODS = ("ctrl", "alt", "shift", "win")
```

`_KeyCaptureEdit.__init__` 於 `self._listening = False` 之後加：

```python
        self._pressed: list[str] = []      # combo 錄製期間按下過的鍵（依序、去重）
```

`_start` 於設 `self._listening = True` 之後加 `self._pressed = []`：

```python
    def _start(self) -> None:
        self._listening = True
        self._pressed = []
        self._display.setText("請按一個鍵…（Esc 取消）")
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if self.isVisible():
            self.grabKeyboard()
```

改寫 `keyPressEvent`、新增 `keyReleaseEvent` 與 `_commit`：

```python
    def keyPressEvent(self, event):   # noqa: N802
        if not self._listening:
            super().keyPressEvent(event)
            return
        if event.key() == int(Qt.Key.Key_Escape):
            self._stop()          # Esc＝取消錄製（保留原值）
            return
        if event.isAutoRepeat():
            return                # 按住的自動重複不算新按鍵
        name = _qt_key_to_name(event)
        if name is None:
            return
        if not self._combo:
            self._value = name
            self._stop()
            return
        # combo：累積按下的鍵（含事件上的 modifiers 位元），放開任一鍵才定案
        for m in _modifier_names(event.modifiers()):
            if m not in self._pressed:
                self._pressed.append(m)
        if name not in self._pressed:
            self._pressed.append(name)

    def keyReleaseEvent(self, event):   # noqa: N802
        if not self._listening or not self._combo:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            return
        if any(k not in _ALL_MODS for k in self._pressed):
            self._commit()
            self._stop()
        else:
            name = _qt_key_to_name(event)   # 只按了修飾鍵就放開：移除、繼續等
            if name in self._pressed:
                self._pressed.remove(name)

    def _commit(self) -> None:
        mods = [m for m in _ALL_MODS if m in self._pressed]
        mains = [k for k in self._pressed if k not in _ALL_MODS]
        self._value = "+".join(mods + mains)
```

- [ ] **Step 4: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_script_editor_widget.py -q`
Expected: PASS（含既有單鍵測試 `test_key_capture_edit_records_single_key` 續過）。

- [ ] **Step 5: 提交**

```bash
git add src/keyboard_executor/app/key_capture.py tests/app/test_script_editor_widget.py
git commit -m "feat(key-capture): 組合鍵錄製支援 3 鍵以上（累積＋放開才定案）"
```

---

## Task 8: 緊急停止不再停監看（拆除監看 guard、只停回放）

**Files:**
- Modify: `src/keyboard_executor/app/watch_controller.py`（`__init__`、`build_job`、`apply_settings`、移除 `_start_guard` 與相關 import）
- Modify: `src/keyboard_executor/app/main_window.py`（`_on_emergency_hotkey` 約 149–153；WatchController 建構 約 77–85；`_apply_settings` 約 683–686）
- Test: `tests/app/test_watch_controller.py`、`tests/app/test_main_window.py`

**Interfaces:**
- Produces: `WatchController` 不再接受 `hook_factory`/`guard_factory`/`stop_key`/`corner_failsafe`；`apply_settings(*, get_platform, discord_webhook_url)`；`_on_emergency_hotkey` 只呼叫 `run_controller.stop()`。

- [ ] **Step 1: 改寫/刪除監看測試**（`tests/app/test_watch_controller.py`）

- 刪除 `SpyGuard` 類別、`test_guard_best_effort_with_configured_stop_key`、`test_watch_controller_passes_corner_failsafe_to_guard`。
- 移除 `from tests.fakes import FakeInputHook`（若不再使用）與 `import threading`（若不再使用）。
- `make_controller` 改為：

```python
def make_controller(tmp_path, *, player_factory=None, on_stop_all=None):
    return WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=player_factory or (lambda *a, **k: object()),
        on_stop_all=on_stop_all)
```

- `test_build_job_wires_webhook_into_notifier_factory` 建構子移除 `hook_factory=FakeInputHook, guard_factory=SpyGuard`。
- `test_apply_settings_takes_effect_on_next_build_job` 改為（移除 guard 與 stop_key）：

```python
def test_apply_settings_takes_effect_on_next_build_job(tmp_path):
    captured = {}

    def fake_notifier_factory(base, webhook):
        captured["webhook"] = webhook
        return base

    plat_calls = []
    controller = WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=lambda *a, **k: object(),
        discord_webhook_url="https://discord.com/api/webhooks/1/old",
        notifier_factory=fake_notifier_factory)
    controller.apply_settings(
        get_platform=lambda **k: (plat_calls.append(True), object())[1],
        discord_webhook_url="https://discord.com/api/webhooks/1/new")
    controller.build_job()(lambda r: None)
    assert captured["webhook"] == "https://discord.com/api/webhooks/1/new"  # 新 webhook
    assert plat_calls                                                    # 新 get_platform 被呼叫
```

- [ ] **Step 2: 執行確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_watch_controller.py -q`
Expected: FAIL（`WatchController` 仍要求/使用 guard 參數，或 `apply_settings` 仍需 `stop_key`）。

- [ ] **Step 3: 改寫 `watch_controller.py`**

移除 import：`from keyboard_executor.core.guard import SessionGuard` 與 `from keyboard_executor.platforms.common.hook_pynput import PynputInputHook`。

`__init__` 改為（移除 `hook_factory`/`guard_factory`/`stop_key`/`corner_failsafe`）：

```python
    def __init__(self, rule_storage, script_storage, templates, *,
                 get_platform=get_platform, engine_factory=RuleEngine,
                 player_factory=Player, discord_webhook_url: str = "",
                 notifier_factory=make_notifier, on_stop_all=None):
        self._rule_storage = rule_storage
        self._script_storage = script_storage
        self._templates = templates
        self._get_platform = get_platform
        self._engine_factory = engine_factory
        self._player_factory = player_factory
        self._discord_webhook_url = discord_webhook_url
        self._notifier_factory = notifier_factory
        self._on_stop_all = on_stop_all   # stop_all 觸發時另停執行中的腳本（run_controller）
        self._stop_event: threading.Event | None = None
```

`build_job` 的 `job` 內移除 guard（直接 `engine.run(rules)`）：

```python
        def job(progress):
            platform = self._get_platform()

            def player_factory_with_stop(*args, **kwargs):
                return self._player_factory(*args, stop_event=stop_event, **kwargs)

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
                stop_event=stop_event, on_stop_all=self._on_stop_all)
            engine.run(rules)
            return f"已停止監看（{len(rules)} 條規則）"
        return job
```

`apply_settings` 移除 `stop_key`/`corner_failsafe`：

```python
    def apply_settings(self, *, get_platform, discord_webhook_url: str) -> None:
        """就地更新下一次 build_job 會用到的設定；不影響進行中的監看。"""
        self._get_platform = get_platform
        self._discord_webhook_url = discord_webhook_url
```

刪除整個 `_start_guard` 方法。`import threading` 保留（`build_job` 仍用 `threading.Event`）。

- [ ] **Step 4: 改 `main_window.py` — 建構與 `_on_emergency_hotkey`**

`_on_emergency_hotkey` 改為只停回放：

```python
    def _on_emergency_hotkey(self) -> None:
        """緊急停止（系統級/背景輪詢）：只中止進行中的回放；監看完全獨立，
        由「停止監看」按鈕停止。"""
        self.append_log("偵測到緊急停止 → 中止回放")
        self._run_controller.stop()
```

WatchController 建構（約 77–85）移除 `stop_key`、`corner_failsafe`：

```python
        self._watch_controller = (watch_controller if watch_controller is not None
                                  else WatchController(
                                      self._rule_storage, self._script_storage,
                                      self._template_store.load_template,
                                      get_platform=self._get_platform,
                                      discord_webhook_url=self._settings.discord_webhook_url,
                                      on_stop_all=self._run_controller.stop))
```

`_apply_settings` 的 `self._watch_controller.apply_settings(...)`（約 683–686）改為：

```python
        self._watch_controller.apply_settings(
            get_platform=self._get_platform,
            discord_webhook_url=new.discord_webhook_url)
```

- [ ] **Step 5: 改 `tests/app/test_main_window.py`**

- `test_apply_settings_updates_snapshot_controllers_hotkey_and_labels`：刪除 `assert watch_c.applied["stop_key"] == "f8"`（保留 `discord_webhook_url` 那條；`RecCtrl.apply_settings(**kw)` 仍記錄）。
- 改寫 `test_emergency_signal_stops_both_controllers`：

```python
def test_emergency_signal_stops_only_run_not_watch(qapp, tmp_path):
    run = FakeRunController()
    watch = FakeWatchController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=run, watch_controller=watch)
    window.emergency_stop_requested.emit()      # 同執行緒 → 同步呼叫 _on_emergency_hotkey
    assert run.stopped == 1 and watch.stopped == 0   # 只停回放，監看不動
```

- [ ] **Step 6: 執行確認通過**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/app/test_watch_controller.py tests/app/test_main_window.py -q`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/keyboard_executor/app/watch_controller.py src/keyboard_executor/app/main_window.py tests/app/test_watch_controller.py tests/app/test_main_window.py
git commit -m "feat(estop): 緊急停止只停回放，監看完全獨立（拆除監看 guard）"
```

---

## 收尾：全套件驗證

- [ ] **執行完整測試套件**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: 全綠（既有 696 passed 之上，加本計畫新增/更新的測試；監看 guard 相關測試已依 Task 8 刪除）。

- [ ] **更新 windows-build-env 記憶的測試基線數字**（若被審閱要求；於最終審閱後）。
