# M2a 腳本模型與回放引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 JSON 腳本資料模型、檔案儲存與回放引擎，能用 `python -m keyboard_executor.cli play <name>` 對指定視窗回放手寫腳本（含 delay/loop/run_script 流程控制、速度倍率、隨機抖動、重複次數）。

**Architecture:** 三層架構的 core 層擴充。`core/models.py` 定義 Action/Script 資料模型與嚴格驗證（未知欄位即報錯）；`storage/scripts.py` 負責 JSON 檔案存取；`core/player.py` 是同步狀態機，逐動作執行、每個座標動作前重新查詢視窗位置、stop_event 隨時可中斷；`cli.py` 提供 play 子命令。全部依賴 M1 的平台抽象（fakes 注入即可單元測試）。錄製（InputHook、recorder、F9/F10 熱鍵）在 M2b 另立計畫。

**Tech Stack:** Python 3.11+（StrEnum）、既有 M1 平台層（pynput/pywinctl）、pytest。無新增第三方依賴。

**對應 spec:** `docs/superpowers/specs/2026-07-06-keyboard-executor-design.md` §5（資料模型，M2a 子集）、§7（回放）、§10（錯誤處理）、§13-M2。M1 最終審查行動項見 `docs/superpowers/notes/2026-07-06-m1-final-review.md`（本計畫吸收：geometry docstring 修正、三組補測；game-mode 覆蓋與 settle 政策留給 M2b Windows 段）。

## Global Constraints

- Python `>=3.11`；src layout：程式碼一律在 `src/keyboard_executor/` 下（spec §4）
- 判斷作業系統（`sys.platform`）只允許出現在 `platforms/` 層；CLI 的 darwin 權限檢查分支沿用 demo.py 的計畫核准例外（spec §4）
- 腳本座標一律為「目標視窗左上角為原點」的相對座標；回放時每個座標動作前重新查詢視窗位置再換算絕對座標（spec §5.2、§7）
- 腳本 JSON 損壞或不合規：載入時驗證、拋 `ScriptValidationError`（繁體中文訊息）、不崩潰（spec §10）
- 驗證採嚴格模式：未知動作類型、未知欄位一律報錯（及早抓 typo）
- `settings`：`speed`（>0 倍率，除延遲）、`repeat`（-1=無限或 >=1）、`humanize_jitter_pct`（0–100，只作用於 delay）、`game_input_mode`（bool）、`window_retry`（>=0）、`window_retry_interval_ms`（>=0）（spec §5.1 + §10 重試）
- 外部依賴（sleep、rng、stop_event、storage）一律建構子注入，預設真實實作（spec §12）
- 所有面向使用者的訊息（錯誤、CLI 輸出）用繁體中文
- Commit 訊息用 conventional commits；直接在 main 工作，不開分支（用戶既定選擇）
- TDD：RED 一律用計畫指定的 pytest 指令執行並在報告貼上真實 transcript；全套件回歸跑 repo 根目錄 `python -m pytest -q`

---

### Task 1: M1 遺留補強

**Files:**
- Modify: `src/keyboard_executor/core/geometry.py`（僅 docstring）
- Modify: `tests/platforms/test_keymap.py`（追加 2 個測試）
- Modify: `tests/platforms/test_window_pywinctl.py`（追加 1 個測試）
- Modify: `tests/platforms/test_win32_input.py`（強化 2 個既有測試的斷言）

**Interfaces:**
- Consumes: M1 全部既有程式碼（不改任何行為，只補測試與文字）
- Produces: 無新介面；全套件基準從 52 passed, 1 skipped 變為 55 passed, 1 skipped

- [ ] **Step 1: 修正 geometry.py 座標單位措辭**

M1 最終審查指出：macOS 上 pywinctl/pynput 用的是「點（points）」而非實體像素（Retina 上 1 pt = 2 px）。M2a 只修文件措辭，換算設計留給 M3 規劃。

將 `src/keyboard_executor/core/geometry.py` 第 1 行 docstring：

```python
"""座標系統：所有腳本座標一律為「目標視窗左上角為原點」的相對座標（實體像素）。"""
```

改為：

```python
"""座標系統：所有腳本座標一律為「目標視窗左上角為原點」的相對座標。

單位為「平台輸入座標」：Windows 上是實體像素（已宣告 DPI aware）；macOS 上是
Cocoa 點（Retina 螢幕 1 點 = 2 實體像素）。M1/M2 內部（pywinctl 幾何、pynput
滑鼠）單位一致；M3 引入螢幕截圖（實體像素）時需在 ScreenCapture 層處理換算，
見 docs/superpowers/notes/2026-07-06-m1-final-review.md。
"""
```

- [ ] **Step 2: 寫追加的失敗/通過測試**

在 `tests/platforms/test_keymap.py` 檔尾追加：

```python
def test_parse_combo_empty_string_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_combo("")


def test_parse_combo_trailing_plus_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_combo("ctrl+")
```

在 `tests/platforms/test_window_pywinctl.py` 檔尾追加：

```python
def test_find_windows_intersects_title_and_app():
    manager, _ = make_manager([
        StubWindow("記事本 A", app="Notepad"),
        StubWindow("記事本 B", app="Editor"),
        StubWindow("瀏覽器", app="Notepad"),
    ])
    result = manager.find_windows(title_pattern="記事本", app_name="notepad")
    assert [w.title for w in result] == ["記事本 A"]
```

在 `tests/platforms/test_win32_input.py` 把兩個既有測試整段替換，補「不走 pynput」斷言：

```python
def test_game_mode_key_press_with_hold():
    backend, pdi, kb, _, sleeps = make_game_backend()
    backend.key_press("w", hold_ms=1000)
    assert pdi.ops == [("keyDown", "w"), ("keyUp", "w")]
    assert sleeps == [1.0]
    assert kb.ops == []  # 不走 pynput
```

`test_game_mode_key_combo_releases_in_reverse` 整段改成：

```python
def test_game_mode_key_combo_releases_in_reverse():
    backend, pdi, kb, mouse, _ = make_game_backend()
    backend.key_combo(["ctrl", "c"])
    assert pdi.ops == [
        ("keyDown", "ctrl"), ("keyDown", "c"),
        ("keyUp", "c"), ("keyUp", "ctrl"),
    ]
    assert kb.ops == []
    assert mouse.ops == []
```

- [ ] **Step 3: 跑測試確認通過（本任務無 RED——新測試針對既有正確行為）**

Run: `python -m pytest tests/platforms/test_keymap.py tests/platforms/test_window_pywinctl.py tests/platforms/test_win32_input.py -v`
Expected: 全部通過（keymap 9、window 8、win32 5）。若 `parse_combo("")` 測試失敗，代表對既有行為的認知有誤——停下回報，不要改動 keymap 實作。

- [ ] **Step 4: 全套件回歸**

Run: `python -m pytest -q`
Expected: 55 passed, 1 skipped

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/geometry.py tests/platforms/
git commit -m "test: M1 補強——座標單位措辭修正與邊界補測"
```

---

### Task 2: Action 資料模型與驗證

**Files:**
- Create: `src/keyboard_executor/core/models.py`
- Test: `tests/core/test_models_action.py`

**Interfaces:**
- Consumes: 無（純資料層）
- Produces（Task 3–7 依賴）:
  - `ScriptValidationError(Exception)` — 所有腳本驗證錯誤，訊息繁中
  - `ActionType`（StrEnum）: `KEY_PRESS="key_press"`, `KEY_COMBO="key_combo"`, `TEXT_INPUT="text_input"`, `MOUSE_MOVE="mouse_move"`, `MOUSE_CLICK="mouse_click"`, `MOUSE_DRAG="mouse_drag"`, `SCROLL="scroll"`, `DELAY="delay"`, `LOOP="loop"`, `RUN_SCRIPT="run_script"`
  - `Action`（frozen dataclass）: `type: ActionType`, `params: dict`
  - `action_from_dict(data: dict) -> Action` — 驗證 + 正規化（loop 的 actions 遞迴轉為 Action）；未知類型/欄位/型別錯誤拋 `ScriptValidationError`
  - `action_to_dict(action: Action) -> dict` — 反向序列化（loop 遞迴）
  - 各類型欄位規格（params）:
    - `key_press`: `key: str` 必填非空；`hold_ms: int>=0` 選填預設 0
    - `key_combo`: `keys: list[str]` 必填、至少 1 個、皆非空
    - `text_input`: `text: str` 必填
    - `mouse_move`: `x: int`, `y: int` 必填
    - `mouse_click`: `x, y: int` 必填；`button` 選填 in {"left","right","middle"} 預設 "left"；`count: int>=1` 選填預設 1
    - `mouse_drag`: `from: [int, int]`, `to: [int, int]` 必填；`button` 選填同上
    - `scroll`: `x, y: int` 必填；`dx, dy: int` 選填預設 0
    - `delay`: `ms` 必填——`int>=0` 或 `[min, max]`（int、`0<=min<=max`）
    - `loop`: `count: int`（-1 或 >=1）必填；`actions: list` 必填非空，遞迴驗證
    - `run_script`: `script_name: str` 必填非空

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_models_action.py`：

```python
import pytest

from keyboard_executor.core.models import (
    Action,
    ActionType,
    ScriptValidationError,
    action_from_dict,
    action_to_dict,
)


def test_key_press_minimal():
    a = action_from_dict({"type": "key_press", "key": "enter"})
    assert a.type is ActionType.KEY_PRESS
    assert a.params == {"key": "enter", "hold_ms": 0}


def test_key_press_with_hold():
    a = action_from_dict({"type": "key_press", "key": "w", "hold_ms": 500})
    assert a.params["hold_ms"] == 500


def test_unknown_type_raises():
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        action_from_dict({"type": "fly"})


def test_unknown_field_raises():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        action_from_dict({"type": "key_press", "key": "a", "cout": 2})


def test_missing_required_field_raises():
    with pytest.raises(ScriptValidationError, match="缺少欄位"):
        action_from_dict({"type": "key_press"})


def test_wrong_type_raises():
    with pytest.raises(ScriptValidationError, match="型別"):
        action_from_dict({"type": "key_press", "key": 123})


def test_bool_is_not_int():
    with pytest.raises(ScriptValidationError, match="型別"):
        action_from_dict({"type": "mouse_move", "x": True, "y": 0})


def test_key_combo():
    a = action_from_dict({"type": "key_combo", "keys": ["ctrl", "s"]})
    assert a.params == {"keys": ["ctrl", "s"]}


def test_key_combo_empty_list_raises():
    with pytest.raises(ScriptValidationError, match="至少"):
        action_from_dict({"type": "key_combo", "keys": []})


def test_mouse_click_defaults():
    a = action_from_dict({"type": "mouse_click", "x": 10, "y": 20})
    assert a.params == {"x": 10, "y": 20, "button": "left", "count": 1}


def test_mouse_click_invalid_button_raises():
    with pytest.raises(ScriptValidationError, match="button"):
        action_from_dict({"type": "mouse_click", "x": 1, "y": 2, "button": "side"})


def test_mouse_drag_normalizes_points():
    a = action_from_dict({"type": "mouse_drag", "from": [1, 2], "to": [3, 4]})
    assert a.params == {"from": [1, 2], "to": [3, 4], "button": "left"}


def test_mouse_drag_bad_point_raises():
    with pytest.raises(ScriptValidationError, match="兩個整數"):
        action_from_dict({"type": "mouse_drag", "from": [1], "to": [3, 4]})


def test_delay_fixed_and_range():
    assert action_from_dict({"type": "delay", "ms": 100}).params == {"ms": 100}
    assert action_from_dict({"type": "delay", "ms": [50, 150]}).params == {"ms": [50, 150]}


def test_delay_bad_range_raises():
    with pytest.raises(ScriptValidationError, match="delay"):
        action_from_dict({"type": "delay", "ms": [150, 50]})


def test_loop_recursively_validates():
    a = action_from_dict({
        "type": "loop", "count": 3,
        "actions": [{"type": "key_press", "key": "a"}],
    })
    assert a.type is ActionType.LOOP
    inner = a.params["actions"][0]
    assert isinstance(inner, Action)
    assert inner.type is ActionType.KEY_PRESS


def test_loop_invalid_count_raises():
    with pytest.raises(ScriptValidationError, match="count"):
        action_from_dict({"type": "loop", "count": 0,
                          "actions": [{"type": "key_press", "key": "a"}]})


def test_loop_bad_inner_action_raises():
    with pytest.raises(ScriptValidationError, match="未知動作類型"):
        action_from_dict({"type": "loop", "count": 1, "actions": [{"type": "nope"}]})


def test_run_script():
    a = action_from_dict({"type": "run_script", "script_name": "子腳本"})
    assert a.params == {"script_name": "子腳本"}


def test_round_trip():
    src = {
        "type": "loop", "count": 2,
        "actions": [
            {"type": "mouse_click", "x": 5, "y": 6, "button": "right", "count": 2},
            {"type": "delay", "ms": [10, 20]},
        ],
    }
    assert action_to_dict(action_from_dict(src)) == {
        "type": "loop", "count": 2,
        "actions": [
            {"type": "mouse_click", "x": 5, "y": 6, "button": "right", "count": 2},
            {"type": "delay", "ms": [10, 20]},
        ],
    }
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_models_action.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.models'`

- [ ] **Step 3: 實作 models.py（Action 部分）**

`src/keyboard_executor/core/models.py`：

```python
"""腳本資料模型與驗證。

所有座標為「目標視窗左上角為原點」的相對座標（平台輸入座標單位，見 geometry.py）。
驗證採嚴格模式：未知動作類型、未知欄位、型別錯誤一律拋 ScriptValidationError，
訊息為繁體中文，供 CLI/GUI 直接顯示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ScriptValidationError(Exception):
    """腳本 JSON 結構不合法。"""


class ActionType(StrEnum):
    KEY_PRESS = "key_press"
    KEY_COMBO = "key_combo"
    TEXT_INPUT = "text_input"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_DRAG = "mouse_drag"
    SCROLL = "scroll"
    DELAY = "delay"
    LOOP = "loop"
    RUN_SCRIPT = "run_script"


@dataclass(frozen=True)
class Action:
    type: ActionType
    params: dict[str, Any] = field(default_factory=dict)


_MOUSE_BUTTONS = {"left", "right", "middle"}


def _err(message: str) -> None:
    raise ScriptValidationError(message)


def _check_no_extra(params: dict, atype: str, allowed: set[str]) -> None:
    extra = set(params) - allowed
    if extra:
        _err(f"動作 {atype} 不支援的欄位: {', '.join(sorted(extra))}")


def _get_int(params: dict, atype: str, name: str, *, minimum: int | None = None,
             default: int | None = None, required: bool = True) -> int:
    if name not in params:
        if required:
            _err(f"動作 {atype} 缺少欄位 {name}")
        return default
    value = params[name]
    if not isinstance(value, int) or isinstance(value, bool):
        _err(f"動作 {atype} 欄位 {name} 型別錯誤：必須是整數")
    if minimum is not None and value < minimum:
        _err(f"動作 {atype} 欄位 {name} 必須 >= {minimum}")
    return value


def _get_str(params: dict, atype: str, name: str) -> str:
    if name not in params:
        _err(f"動作 {atype} 缺少欄位 {name}")
    value = params[name]
    if not isinstance(value, str) or not value.strip():
        _err(f"動作 {atype} 欄位 {name} 型別錯誤：必須是非空字串")
    return value


def _get_button(params: dict, atype: str) -> str:
    button = params.get("button", "left")
    if button not in _MOUSE_BUTTONS:
        _err(f"動作 {atype} 欄位 button 必須是 left/right/middle")
    return button


def _get_point(params: dict, atype: str, name: str) -> list[int]:
    if name not in params:
        _err(f"動作 {atype} 缺少欄位 {name}")
    value = params[name]
    ok = (isinstance(value, (list, tuple)) and len(value) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in value))
    if not ok:
        _err(f"動作 {atype} 欄位 {name} 必須是兩個整數的座標 [x, y]")
    return [value[0], value[1]]


def _validate_key_press(p: dict) -> dict:
    _check_no_extra(p, "key_press", {"key", "hold_ms"})
    return {"key": _get_str(p, "key_press", "key"),
            "hold_ms": _get_int(p, "key_press", "hold_ms", minimum=0, default=0, required=False)}


def _validate_key_combo(p: dict) -> dict:
    _check_no_extra(p, "key_combo", {"keys"})
    keys = p.get("keys")
    if not isinstance(keys, list) or not keys:
        _err("動作 key_combo 欄位 keys 必須是至少一個按鍵的清單")
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            _err("動作 key_combo 欄位 keys 型別錯誤：每個按鍵必須是非空字串")
    return {"keys": list(keys)}


def _validate_text_input(p: dict) -> dict:
    _check_no_extra(p, "text_input", {"text"})
    if "text" not in p:
        _err("動作 text_input 缺少欄位 text")
    if not isinstance(p["text"], str):
        _err("動作 text_input 欄位 text 型別錯誤：必須是字串")
    return {"text": p["text"]}


def _validate_mouse_move(p: dict) -> dict:
    _check_no_extra(p, "mouse_move", {"x", "y"})
    return {"x": _get_int(p, "mouse_move", "x"), "y": _get_int(p, "mouse_move", "y")}


def _validate_mouse_click(p: dict) -> dict:
    _check_no_extra(p, "mouse_click", {"x", "y", "button", "count"})
    return {"x": _get_int(p, "mouse_click", "x"),
            "y": _get_int(p, "mouse_click", "y"),
            "button": _get_button(p, "mouse_click"),
            "count": _get_int(p, "mouse_click", "count", minimum=1, default=1, required=False)}


def _validate_mouse_drag(p: dict) -> dict:
    _check_no_extra(p, "mouse_drag", {"from", "to", "button"})
    return {"from": _get_point(p, "mouse_drag", "from"),
            "to": _get_point(p, "mouse_drag", "to"),
            "button": _get_button(p, "mouse_drag")}


def _validate_scroll(p: dict) -> dict:
    _check_no_extra(p, "scroll", {"x", "y", "dx", "dy"})
    return {"x": _get_int(p, "scroll", "x"), "y": _get_int(p, "scroll", "y"),
            "dx": _get_int(p, "scroll", "dx", default=0, required=False),
            "dy": _get_int(p, "scroll", "dy", default=0, required=False)}


def _validate_delay(p: dict) -> dict:
    _check_no_extra(p, "delay", {"ms"})
    if "ms" not in p:
        _err("動作 delay 缺少欄位 ms")
    ms = p["ms"]
    if isinstance(ms, int) and not isinstance(ms, bool):
        if ms < 0:
            _err("動作 delay 欄位 ms 必須 >= 0")
        return {"ms": ms}
    ok = (isinstance(ms, list) and len(ms) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in ms)
          and 0 <= ms[0] <= ms[1])
    if not ok:
        _err("動作 delay 欄位 ms 必須是 >=0 的整數，或 [min, max]（0 <= min <= max）")
    return {"ms": [ms[0], ms[1]]}


def _validate_loop(p: dict) -> dict:
    _check_no_extra(p, "loop", {"count", "actions"})
    count = _get_int(p, "loop", "count")
    if count != -1 and count < 1:
        _err("動作 loop 欄位 count 必須是 -1（無限）或 >= 1")
    actions = p.get("actions")
    if not isinstance(actions, list) or not actions:
        _err("動作 loop 欄位 actions 必須是至少一個動作的清單")
    return {"count": count, "actions": [action_from_dict(a) for a in actions]}


def _validate_run_script(p: dict) -> dict:
    _check_no_extra(p, "run_script", {"script_name"})
    return {"script_name": _get_str(p, "run_script", "script_name")}


_VALIDATORS = {
    ActionType.KEY_PRESS: _validate_key_press,
    ActionType.KEY_COMBO: _validate_key_combo,
    ActionType.TEXT_INPUT: _validate_text_input,
    ActionType.MOUSE_MOVE: _validate_mouse_move,
    ActionType.MOUSE_CLICK: _validate_mouse_click,
    ActionType.MOUSE_DRAG: _validate_mouse_drag,
    ActionType.SCROLL: _validate_scroll,
    ActionType.DELAY: _validate_delay,
    ActionType.LOOP: _validate_loop,
    ActionType.RUN_SCRIPT: _validate_run_script,
}


def action_from_dict(data: Any) -> Action:
    if not isinstance(data, dict):
        _err("動作必須是 JSON 物件")
    raw_type = data.get("type")
    try:
        atype = ActionType(raw_type)
    except ValueError:
        _err(f"未知動作類型: {raw_type!r}")
    params = {k: v for k, v in data.items() if k != "type"}
    return Action(type=atype, params=_VALIDATORS[atype](params))


def action_to_dict(action: Action) -> dict:
    result: dict[str, Any] = {"type": str(action.type)}
    for key, value in action.params.items():
        if key == "actions":
            result[key] = [action_to_dict(a) for a in value]
        else:
            result[key] = value
    return result
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_models_action.py -v`
Expected: 20 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: 75 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_action.py
git commit -m "feat: Action 資料模型與嚴格驗證"
```

---

### Task 3: Script 資料模型與（反）序列化

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（檔尾追加）
- Test: `tests/core/test_models_script.py`

**Interfaces:**
- Consumes: Task 2 的 `Action`/`action_from_dict`/`action_to_dict`/`ScriptValidationError`
- Produces（Task 4–7 依賴）:
  - `TargetWindow`（frozen dataclass）: `title_pattern: str | None = None`, `app_name: str | None = None`
  - `ScriptSettings`（frozen dataclass）: `speed: float = 1.0`, `repeat: int = 1`, `humanize_jitter_pct: int = 0`, `game_input_mode: bool = False`, `window_retry: int = 0`, `window_retry_interval_ms: int = 1000`
  - `Script`（frozen dataclass）: `name: str`, `target_window: TargetWindow`, `actions: tuple[Action, ...]`, `settings: ScriptSettings`
  - `script_from_dict(data: dict) -> Script`（驗證規則見測試）
  - `script_to_dict(script: Script) -> dict`（round-trip）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_models_script.py`：

```python
import pytest

from keyboard_executor.core.models import (
    Script,
    ScriptValidationError,
    script_from_dict,
    script_to_dict,
)


def minimal(**overrides):
    data = {
        "name": "測試腳本",
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}],
    }
    data.update(overrides)
    return data


def test_minimal_script_with_defaults():
    s = script_from_dict(minimal())
    assert isinstance(s, Script)
    assert s.name == "測試腳本"
    assert s.target_window.title_pattern == "記事本"
    assert s.target_window.app_name is None
    assert (s.settings.speed, s.settings.repeat) == (1.0, 1)
    assert s.settings.humanize_jitter_pct == 0
    assert s.settings.game_input_mode is False
    assert (s.settings.window_retry, s.settings.window_retry_interval_ms) == (0, 1000)
    assert len(s.actions) == 1


def test_name_required_and_no_path_separators():
    with pytest.raises(ScriptValidationError, match="name"):
        script_from_dict(minimal(name=""))
    with pytest.raises(ScriptValidationError, match="name"):
        script_from_dict(minimal(name="a/b"))


def test_target_window_needs_at_least_one_condition():
    with pytest.raises(ScriptValidationError, match="target_window"):
        script_from_dict(minimal(target_window={}))


def test_target_window_invalid_regex_raises():
    with pytest.raises(ScriptValidationError, match="regex"):
        script_from_dict(minimal(target_window={"title_pattern": "["}))


def test_target_window_app_name_only_is_ok():
    s = script_from_dict(minimal(target_window={"app_name": "Notepad"}))
    assert s.target_window.app_name == "Notepad"
    assert s.target_window.title_pattern is None


def test_actions_must_be_nonempty():
    with pytest.raises(ScriptValidationError, match="actions"):
        script_from_dict(minimal(actions=[]))


def test_settings_validation():
    with pytest.raises(ScriptValidationError, match="speed"):
        script_from_dict(minimal(settings={"speed": 0}))
    with pytest.raises(ScriptValidationError, match="repeat"):
        script_from_dict(minimal(settings={"repeat": 0}))
    with pytest.raises(ScriptValidationError, match="humanize_jitter_pct"):
        script_from_dict(minimal(settings={"humanize_jitter_pct": 101}))
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        script_from_dict(minimal(settings={"speeed": 2}))


def test_settings_repeat_minus_one_is_infinite():
    s = script_from_dict(minimal(settings={"repeat": -1}))
    assert s.settings.repeat == -1


def test_unknown_top_level_field_raises():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        script_from_dict(minimal(extra=1))


def test_round_trip():
    data = minimal(settings={"speed": 2.0, "repeat": 3, "humanize_jitter_pct": 10})
    assert script_to_dict(script_from_dict(data)) == {
        "name": "測試腳本",
        "target_window": {"title_pattern": "記事本", "app_name": None},
        "settings": {"speed": 2.0, "repeat": 3, "humanize_jitter_pct": 10,
                     "game_input_mode": False,
                     "window_retry": 0, "window_retry_interval_ms": 1000},
        "actions": [{"type": "key_press", "key": "a", "hold_ms": 0}],
    }
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_models_script.py -v`
Expected: FAIL — `ImportError: cannot import name 'script_from_dict'`

- [ ] **Step 3: 在 models.py 追加實作**

(a) 在檔案頂部 import 區塊（`from dataclasses import ...` 之前）加入：

```python
import re
```

(b) 檔尾追加：

```python
@dataclass(frozen=True)
class TargetWindow:
    title_pattern: str | None = None
    app_name: str | None = None


@dataclass(frozen=True)
class ScriptSettings:
    speed: float = 1.0
    repeat: int = 1
    humanize_jitter_pct: int = 0
    game_input_mode: bool = False
    window_retry: int = 0
    window_retry_interval_ms: int = 1000


@dataclass(frozen=True)
class Script:
    name: str
    target_window: TargetWindow
    actions: tuple[Action, ...]
    settings: ScriptSettings = field(default_factory=ScriptSettings)


def _validate_target_window(data: Any) -> TargetWindow:
    if not isinstance(data, dict):
        _err("target_window 必須是 JSON 物件")
    _check_no_extra(data, "target_window", {"title_pattern", "app_name"})
    title = data.get("title_pattern")
    app = data.get("app_name")
    for name, value in (("title_pattern", title), ("app_name", app)):
        if value is not None and not isinstance(value, str):
            _err(f"target_window 欄位 {name} 型別錯誤：必須是字串")
    if not (title and title.strip()) and not (app and app.strip()):
        _err("target_window 至少要提供 title_pattern 或 app_name 其中一個")
    if title:
        try:
            re.compile(title)
        except re.error as e:
            _err(f"target_window.title_pattern 不是合法 regex: {e}")
    return TargetWindow(title_pattern=title, app_name=app)


def _validate_settings(data: Any) -> ScriptSettings:
    if data is None:
        return ScriptSettings()
    if not isinstance(data, dict):
        _err("settings 必須是 JSON 物件")
    allowed = {"speed", "repeat", "humanize_jitter_pct", "game_input_mode",
               "window_retry", "window_retry_interval_ms"}
    _check_no_extra(data, "settings", allowed)
    defaults = ScriptSettings()
    speed = data.get("speed", defaults.speed)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
        _err("settings.speed 必須是 > 0 的數字")
    repeat = data.get("repeat", defaults.repeat)
    if not isinstance(repeat, int) or isinstance(repeat, bool) or (repeat != -1 and repeat < 1):
        _err("settings.repeat 必須是 -1（無限）或 >= 1 的整數")
    jitter = data.get("humanize_jitter_pct", defaults.humanize_jitter_pct)
    if not isinstance(jitter, int) or isinstance(jitter, bool) or not 0 <= jitter <= 100:
        _err("settings.humanize_jitter_pct 必須是 0–100 的整數")
    game = data.get("game_input_mode", defaults.game_input_mode)
    if not isinstance(game, bool):
        _err("settings.game_input_mode 必須是布林值")
    retry = data.get("window_retry", defaults.window_retry)
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        _err("settings.window_retry 必須是 >= 0 的整數")
    interval = data.get("window_retry_interval_ms", defaults.window_retry_interval_ms)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 0:
        _err("settings.window_retry_interval_ms 必須是 >= 0 的整數")
    return ScriptSettings(speed=float(speed), repeat=repeat, humanize_jitter_pct=jitter,
                          game_input_mode=game, window_retry=retry,
                          window_retry_interval_ms=interval)


def script_from_dict(data: Any) -> Script:
    if not isinstance(data, dict):
        _err("腳本必須是 JSON 物件")
    _check_no_extra(data, "腳本", {"name", "target_window", "settings", "actions"})
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        _err("腳本欄位 name 必須是非空字串且不含路徑分隔字元")
    if "target_window" not in data:
        _err("腳本缺少欄位 target_window")
    target = _validate_target_window(data["target_window"])
    settings = _validate_settings(data.get("settings"))
    actions_raw = data.get("actions")
    if not isinstance(actions_raw, list) or not actions_raw:
        _err("腳本欄位 actions 必須是至少一個動作的清單")
    actions = tuple(action_from_dict(a) for a in actions_raw)
    return Script(name=name, target_window=target, actions=actions, settings=settings)


def script_to_dict(script: Script) -> dict:
    s = script.settings
    return {
        "name": script.name,
        "target_window": {"title_pattern": script.target_window.title_pattern,
                          "app_name": script.target_window.app_name},
        "settings": {"speed": s.speed, "repeat": s.repeat,
                     "humanize_jitter_pct": s.humanize_jitter_pct,
                     "game_input_mode": s.game_input_mode,
                     "window_retry": s.window_retry,
                     "window_retry_interval_ms": s.window_retry_interval_ms},
        "actions": [action_to_dict(a) for a in script.actions],
    }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_models_script.py -v`
Expected: 10 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: 85 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_script.py
git commit -m "feat: Script 資料模型、settings 驗證與 JSON 序列化"
```

---

### Task 4: 腳本檔案儲存

**Files:**
- Create: `src/keyboard_executor/storage/scripts.py`
- Test: `tests/storage/__init__.py`（空檔案）
- Test: `tests/storage/test_scripts.py`

**Interfaces:**
- Consumes: `Script`/`script_from_dict`/`script_to_dict`/`ScriptValidationError`（Task 2–3）
- Produces（Task 5–7 依賴）:
  - `ScriptStorage(root: str | Path)` —
    - `path_for(name: str) -> Path` — `root/<name>.json`
    - `save(script: Script) -> Path` — 自動建目錄，UTF-8、`ensure_ascii=False`、`indent=2`
    - `load(name: str) -> Script` — 不存在/壞 JSON/驗證失敗 → `ScriptValidationError`
    - `list_names() -> list[str]` — 排序後的 `*.json` 檔名（不含副檔名）

- [ ] **Step 1: 寫失敗測試**

`tests/storage/test_scripts.py`：

```python
import pytest

from keyboard_executor.core.models import ScriptValidationError, script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage


def make_script(name="測試"):
    return script_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "text_input", "text": "哈囉"}],
    })


def test_save_then_load_round_trip(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    script = make_script()
    path = storage.save(script)
    assert path.exists()
    loaded = storage.load("測試")
    assert loaded == script


def test_saved_json_is_human_readable_utf8(tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(make_script())
    text = (tmp_path / "測試.json").read_text(encoding="utf-8")
    assert "哈囉" in text          # ensure_ascii=False
    assert "\n  " in text          # indent=2


def test_load_missing_raises(tmp_path):
    storage = ScriptStorage(tmp_path)
    with pytest.raises(ScriptValidationError, match="找不到腳本"):
        storage.load("不存在")


def test_load_broken_json_raises(tmp_path):
    (tmp_path / "壞.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ScriptValidationError, match="JSON"):
        ScriptStorage(tmp_path).load("壞")


def test_load_invalid_script_raises(tmp_path):
    (tmp_path / "缺.json").write_text('{"name": "缺"}', encoding="utf-8")
    with pytest.raises(ScriptValidationError):
        ScriptStorage(tmp_path).load("缺")


def test_list_names_sorted(tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(make_script("b"))
    storage.save(make_script("a"))
    (tmp_path / "not-a-script.txt").write_text("x", encoding="utf-8")
    assert storage.list_names() == ["a", "b"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/storage/test_scripts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.storage.scripts'`

- [ ] **Step 3: 實作 scripts.py**

`src/keyboard_executor/storage/scripts.py`：

```python
"""腳本 JSON 檔案存取。一個腳本一個檔：<root>/<name>.json。"""
from __future__ import annotations

import json
from pathlib import Path

from keyboard_executor.core.models import (
    Script,
    ScriptValidationError,
    script_from_dict,
    script_to_dict,
)


class ScriptStorage:
    def __init__(self, root: str | Path):
        self._root = Path(root)

    def path_for(self, name: str) -> Path:
        return self._root / f"{name}.json"

    def save(self, script: Script) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(script.name)
        path.write_text(
            json.dumps(script_to_dict(script), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, name: str) -> Script:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到腳本 {name!r}（{path}）")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ScriptValidationError(f"腳本 {name!r} 不是合法 JSON: {e}") from e
        return script_from_dict(data)

    def list_names(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json"))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/storage/test_scripts.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/storage/scripts.py tests/storage/
git commit -m "feat: 腳本 JSON 檔案儲存"
```

---

### Task 5: 回放引擎——視窗取得與輸入動作

**Files:**
- Create: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_basic.py`

**Interfaces:**
- Consumes: `Script`/`Action`/`ActionType`（Task 2–3）、`Platform`（M1 factory 的 dataclass，欄位 `input_backend`/`window_manager`）、`to_absolute`/`Point`（M1 geometry）、`MouseButton`/`WindowInfo`（M1 base）、`FakeInputBackend`/`FakeWindowManager`（tests/fakes.py）
- Produces（Task 6–7 依賴）:
  - `PlayResult`（frozen dataclass）: `ok: bool`, `actions_run: int`, `error: str | None = None`
  - `Player(platform, storage=None, stop_event=None, sleep=time.sleep, rng=None)` —
    - `play(script: Script) -> PlayResult`
    - `stop_event` property（`threading.Event`；CLI/M2b 熱鍵用來中斷）
  - 行為契約：找不到視窗/無法切前景/視窗中途關閉/手動停止 → `ok=False` + 繁中 `error`；每個座標動作前 `refresh()` 重新查詢視窗並以最新位置換算絕對座標
  - 本任務實作：視窗取得（含 retry）、輸入類動作（key/text/mouse/scroll）、stop_event、actions_run 計數；delay/repeat/loop/run_script 由 Task 6 補上（本任務中 `_run_one` 對這些類型先 `raise _PlayerAbort("動作類型尚未支援: ...")`）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_basic.py`：

```python
import threading

import pytest

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player, PlayResult
from keyboard_executor.platforms.base import MouseButton, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(x=100, y=200, title="記事本"):
    return WindowInfo(handle=object(), title=title, app_name="Notepad",
                      x=x, y=y, width=800, height=600, is_active=False)


def make_platform(windows=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    return Platform(input_backend=backend, window_manager=manager), backend, manager


def make_script(actions, settings=None):
    data = {
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    }
    if settings:
        data["settings"] = settings
    return script_from_dict(data)


def test_runs_keyboard_actions_in_order():
    platform, backend, manager = make_platform()
    script = make_script([
        {"type": "key_press", "key": "enter"},
        {"type": "key_combo", "keys": ["ctrl", "s"]},
        {"type": "text_input", "text": "哈囉"},
    ])
    result = Player(platform).play(script)
    assert result == PlayResult(ok=True, actions_run=3)
    assert backend.calls == [
        ("key_press", "enter", 0),
        ("key_combo", ["ctrl", "s"]),
        ("type_text", "哈囉"),
    ]
    assert manager.activated  # 有先切前景


def test_mouse_coordinates_converted_to_absolute():
    platform, backend, _ = make_platform([make_window(x=100, y=200)])
    script = make_script([
        {"type": "mouse_click", "x": 10, "y": 20},
        {"type": "mouse_move", "x": 1, "y": 2},
        {"type": "mouse_drag", "from": [0, 0], "to": [5, 5]},
        {"type": "scroll", "x": 3, "y": 4, "dy": -2},
    ])
    result = Player(platform).play(script)
    assert result.ok
    assert backend.calls == [
        ("mouse_click", 110, 220, MouseButton.LEFT, 1),
        ("mouse_move", 101, 202),
        ("mouse_drag", 100, 200, 105, 205, MouseButton.LEFT),
        ("scroll", 103, 204, 0, -2),
    ]


def test_window_not_found_returns_error():
    platform, backend, _ = make_platform([])
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "找不到目標視窗" in result.error
    assert backend.calls == []


def test_window_retry_then_success():
    win = make_window()

    class LateWindowManager(FakeWindowManager):
        def __init__(self):
            super().__init__([])
            self.find_calls = 0

        def find_windows(self, title_pattern=None, app_name=None):
            self.find_calls += 1
            if self.find_calls >= 3:
                self.windows = [win]
            return super().find_windows(title_pattern, app_name)

    manager = LateWindowManager()
    backend = FakeInputBackend()
    platform = Platform(input_backend=backend, window_manager=manager)
    sleeps = []
    script = make_script([{"type": "key_press", "key": "a"}],
                         settings={"window_retry": 3, "window_retry_interval_ms": 500})
    result = Player(platform, sleep=sleeps.append).play(script)
    assert result.ok
    assert manager.find_calls == 3
    assert sleeps == [0.5, 0.5]  # 前兩次失敗各等一次


def test_activate_failure_returns_error():
    platform, _, manager = make_platform()
    manager.activate_result = False
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "前景" in result.error


def test_window_closed_mid_run_aborts_safely():
    platform, backend, manager = make_platform()

    class ClosingBackend(FakeInputBackend):
        def mouse_click(self, x, y, button=MouseButton.LEFT, count=1):
            super().mouse_click(x, y, button, count)
            manager.windows = []  # 第一個點擊後視窗被關閉

    backend = ClosingBackend()
    platform = Platform(input_backend=backend, window_manager=manager)
    script = make_script([
        {"type": "mouse_click", "x": 1, "y": 1},
        {"type": "mouse_click", "x": 2, "y": 2},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert result.actions_run == 1  # 只完成第一個動作
    assert len([c for c in backend.calls if c[0] == "mouse_click"]) == 1


def test_pre_set_stop_event_aborts_immediately():
    platform, backend, _ = make_platform()
    stop = threading.Event()
    stop.set()
    result = Player(platform, stop_event=stop).play(
        make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "手動停止" in result.error
    assert backend.calls == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_basic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.player'`

- [ ] **Step 3: 實作 player.py（基本執行）**

`src/keyboard_executor/core/player.py`：

```python
"""回放引擎：把 Script 的動作序列執行到目標視窗。

執行模型：同步逐動作執行。stop_event 在每個動作前檢查，供 Ctrl+C 與
未來的緊急停止熱鍵（M2b）隨時中斷。每個座標動作前都重新查詢視窗位置
（視窗移動也能點對位置），視窗消失則安全中止、絕不對其他視窗送輸入。
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

from keyboard_executor.core.geometry import Point, to_absolute
from keyboard_executor.core.models import Action, ActionType, Script
from keyboard_executor.platforms.base import MouseButton, WindowInfo
from keyboard_executor.platforms.factory import Platform


@dataclass(frozen=True)
class PlayResult:
    ok: bool
    actions_run: int
    error: str | None = None


class _PlayerAbort(Exception):
    """內部中止訊號；訊息即 PlayResult.error。"""


class Player:
    """storage 供 run_script 載入子腳本（Task 6）；sleep/rng/stop_event 注入供測試。"""

    def __init__(self, platform: Platform, storage=None, stop_event=None,
                 sleep=time.sleep, rng=None):
        self._platform = platform
        self._storage = storage
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._actions_run = 0

    @property
    def stop_event(self) -> threading.Event:
        return self._stop

    def play(self, script: Script) -> PlayResult:
        self._actions_run = 0
        try:
            self._execute_script(script)
        except _PlayerAbort as e:
            return PlayResult(ok=False, actions_run=self._actions_run, error=str(e))
        return PlayResult(ok=True, actions_run=self._actions_run)

    # -- 腳本層（Task 6 會在此加入 repeat 與 run_script 巢狀） --

    def _execute_script(self, script: Script) -> None:
        win = self._acquire_window(script)
        self._run_actions(script.actions, script, win)

    def _acquire_window(self, script: Script) -> WindowInfo:
        wm = self._platform.window_manager
        tw = script.target_window
        settings = script.settings
        for attempt in range(settings.window_retry + 1):
            windows = wm.find_windows(title_pattern=tw.title_pattern, app_name=tw.app_name)
            if windows:
                win = windows[0]
                if not wm.activate(win):
                    raise _PlayerAbort(f"無法將視窗切到前景: {win.title}")
                return win
            if attempt < settings.window_retry:
                self._sleep(settings.window_retry_interval_ms / 1000)
        raise _PlayerAbort("找不到目標視窗")

    # -- 動作層 --

    def _run_actions(self, actions, script: Script, win: WindowInfo) -> None:
        for action in actions:
            self._check_stop()
            self._run_one(action, script, win)
            self._actions_run += 1

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise _PlayerAbort("已手動停止")

    def _to_screen(self, win: WindowInfo, rel_x: int, rel_y: int) -> tuple[int, int]:
        fresh = self._platform.window_manager.refresh(win)
        if fresh is None:
            raise _PlayerAbort("目標視窗已關閉")
        point = to_absolute(Point(fresh.x, fresh.y), Point(rel_x, rel_y))
        return point.x, point.y

    def _run_one(self, action: Action, script: Script, win: WindowInfo) -> None:
        backend = self._platform.input_backend
        p = action.params
        atype = action.type
        if atype is ActionType.KEY_PRESS:
            backend.key_press(p["key"], p["hold_ms"])
        elif atype is ActionType.KEY_COMBO:
            backend.key_combo(list(p["keys"]))
        elif atype is ActionType.TEXT_INPUT:
            backend.type_text(p["text"])
        elif atype is ActionType.MOUSE_MOVE:
            x, y = self._to_screen(win, p["x"], p["y"])
            backend.mouse_move(x, y)
        elif atype is ActionType.MOUSE_CLICK:
            x, y = self._to_screen(win, p["x"], p["y"])
            backend.mouse_click(x, y, MouseButton(p["button"]), p["count"])
        elif atype is ActionType.MOUSE_DRAG:
            from_x, from_y = self._to_screen(win, p["from"][0], p["from"][1])
            to_x, to_y = self._to_screen(win, p["to"][0], p["to"][1])
            backend.mouse_drag(from_x, from_y, to_x, to_y, MouseButton(p["button"]))
        elif atype is ActionType.SCROLL:
            x, y = self._to_screen(win, p["x"], p["y"])
            backend.scroll(x, y, p["dx"], p["dy"])
        else:
            raise _PlayerAbort(f"動作類型尚未支援: {atype}")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_basic.py -v`
Expected: 7 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: 98 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_basic.py
git commit -m "feat: 回放引擎——視窗取得、輸入動作與安全防護"
```

---

### Task 6: 回放引擎——時間與流程控制

**Files:**
- Modify: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_flow.py`

**Interfaces:**
- Consumes: Task 5 的 `Player` 內部結構
- Produces（Task 7 依賴的完整行為）:
  - `delay`：`ms` 固定值或 `[min,max]`（`rng.randint`）；jitter `±pct%`（`rng.uniform(-pct, pct)`）；再除以 `speed`；最後 `sleep(秒)`
  - `repeat`：整份 actions 重複 `settings.repeat` 次（-1 無限，靠 stop_event 停）
  - `loop`：`count` 次（-1 無限）巢狀執行
  - `run_script`：由 `storage.load(script_name)` 載入子腳本完整執行（自己的視窗與 settings）；無 storage → 中止；循環呼叫或巢狀 > 8 層 → 中止
  - `Player._execute_script(script, depth=0)` 簽名更新（含 `self._script_stack: list[str]`）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_flow.py`：

```python
import random
import threading

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(title="記事本"):
    return WindowInfo(handle=object(), title=title, app_name="App",
                      x=0, y=0, width=100, height=100, is_active=False)


def make_platform():
    backend = FakeInputBackend()
    manager = FakeWindowManager([make_window()])
    return Platform(input_backend=backend, window_manager=manager), backend


def make_script(actions, settings=None, name="測試"):
    data = {"name": name, "target_window": {"title_pattern": "記事本"}, "actions": actions}
    if settings:
        data["settings"] = settings
    return script_from_dict(data)


def test_delay_scaled_by_speed():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": 1000}], settings={"speed": 2.0})
    assert Player(platform, sleep=sleeps.append).play(script).ok
    assert sleeps == [0.5]  # 1000ms / 2.0 倍速


def test_delay_range_uses_rng():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": [100, 200]}])
    Player(platform, sleep=sleeps.append, rng=random.Random(42)).play(script)
    expected = random.Random(42).randint(100, 200) / 1000
    assert sleeps == [expected]


def test_delay_jitter_deterministic_with_seeded_rng():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": 1000}],
                         settings={"humanize_jitter_pct": 10})
    Player(platform, sleep=sleeps.append, rng=random.Random(7)).play(script)
    expected = 1000 * (1 + random.Random(7).uniform(-10, 10) / 100) / 1000
    assert sleeps == [expected]
    assert 0.9 <= sleeps[0] <= 1.1


def test_repeat_runs_actions_twice():
    platform, backend = make_platform()
    script = make_script([{"type": "key_press", "key": "a"}], settings={"repeat": 2})
    result = Player(platform).play(script)
    assert result.ok
    assert result.actions_run == 2
    assert len(backend.calls) == 2


def test_loop_count_runs_nested_actions():
    platform, backend = make_platform()
    script = make_script([
        {"type": "loop", "count": 3, "actions": [{"type": "key_press", "key": "a"}]},
    ])
    result = Player(platform).play(script)
    assert result.ok
    assert len([c for c in backend.calls if c[0] == "key_press"]) == 3
    # loop 本身 1 + 內部 3
    assert result.actions_run == 4


def test_infinite_loop_stopped_by_stop_event():
    platform, backend = make_platform()
    stop = threading.Event()

    class StopAfterFive(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            super().key_press(key, hold_ms)
            if len(self.calls) >= 5:
                stop.set()

    backend = StopAfterFive()
    platform = Platform(input_backend=backend, window_manager=platform.window_manager)
    script = make_script([
        {"type": "loop", "count": -1, "actions": [{"type": "key_press", "key": "a"}]},
    ])
    result = Player(platform, stop_event=stop).play(script)
    assert result.ok is False
    assert "手動停止" in result.error
    assert len(backend.calls) == 5


def test_infinite_repeat_stopped_by_stop_event():
    platform, backend = make_platform()
    stop = threading.Event()

    class StopAfterThree(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            super().key_press(key, hold_ms)
            if len(self.calls) >= 3:
                stop.set()

    backend = StopAfterThree()
    platform = Platform(input_backend=backend, window_manager=platform.window_manager)
    script = make_script([{"type": "key_press", "key": "a"}], settings={"repeat": -1})
    result = Player(platform, stop_event=stop).play(script)
    assert result.ok is False
    assert len(backend.calls) == 3


class DictStorage:
    """測試用：以 dict 模擬 ScriptStorage.load。"""

    def __init__(self, scripts):
        self._scripts = {s.name: s for s in scripts}

    def load(self, name):
        from keyboard_executor.core.models import ScriptValidationError
        if name not in self._scripts:
            raise ScriptValidationError(f"找不到腳本 {name!r}")
        return self._scripts[name]


def test_run_script_executes_sub_script():
    platform, backend = make_platform()
    sub = make_script([{"type": "text_input", "text": "子"}], name="子腳本")
    main = make_script([{"type": "run_script", "script_name": "子腳本"}], name="主")
    result = Player(platform, storage=DictStorage([sub])).play(main)
    assert result.ok
    assert ("type_text", "子") in backend.calls


def test_run_script_without_storage_aborts():
    platform, _ = make_platform()
    main = make_script([{"type": "run_script", "script_name": "x"}])
    result = Player(platform).play(main)
    assert result.ok is False
    assert "儲存來源" in result.error


def test_run_script_cycle_detected():
    platform, _ = make_platform()
    a = make_script([{"type": "run_script", "script_name": "b"}], name="a")
    b = make_script([{"type": "run_script", "script_name": "a"}], name="b")
    result = Player(platform, storage=DictStorage([a, b])).play(a)
    assert result.ok is False
    assert "循環" in result.error


def test_run_script_missing_sub_script_aborts_cleanly():
    platform, _ = make_platform()
    main = make_script([{"type": "run_script", "script_name": "不存在"}])
    result = Player(platform, storage=DictStorage([])).play(main)
    assert result.ok is False
    assert "找不到腳本" in result.error
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_flow.py -v`
Expected: FAIL — delay/loop/run_script 走到 `_run_one` 的 `動作類型尚未支援` 分支（或 repeat 行為缺失）而失敗

- [ ] **Step 3: 修改 player.py 加入時間與流程控制**

修改 `src/keyboard_executor/core/player.py`：

(a) 檔案頂部常數（import 區塊後）加入：

```python
_MAX_RUN_SCRIPT_DEPTH = 8
```

(b) `__init__` 末尾加入：

```python
        self._script_stack: list[str] = []
```

(c) `play()` 中 `self._actions_run = 0` 之後加入 `self._script_stack = []`，並把 `self._execute_script(script)` 改為 `self._execute_script(script, depth=0)`。

(d) `_execute_script` 整個方法替換為（深度用「儲存/還原」模式，兄弟 run_script 不會累積深度）：

```python
    def _execute_script(self, script: Script, depth: int) -> None:
        self._check_stop()  # 視窗取得前就要能停（Task 5 review 修正，保留）
        if depth > _MAX_RUN_SCRIPT_DEPTH:
            raise _PlayerAbort(f"run_script 巢狀超過 {_MAX_RUN_SCRIPT_DEPTH} 層")
        if script.name in self._script_stack:
            raise _PlayerAbort(f"run_script 循環呼叫: {script.name}")
        previous_depth = self._current_depth
        self._current_depth = depth
        self._script_stack.append(script.name)
        try:
            win = self._acquire_window(script)
            repeat = script.settings.repeat
            done = 0
            while repeat == -1 or done < repeat:
                self._check_stop()
                self._run_actions(script.actions, script, win)
                done += 1
        finally:
            self._script_stack.pop()
            self._current_depth = previous_depth
```

(e) `__init__` 末尾（`self._script_stack` 之後）加入：

```python
        self._current_depth = 0
```

(f) `_run_one` 的 `else` 分支之前加入三個新分支（run_script 需把 `ScriptValidationError` 轉為安全中止）：

```python
        elif atype is ActionType.DELAY:
            self._sleep(self._delay_seconds(p["ms"], script.settings))
        elif atype is ActionType.LOOP:
            count = p["count"]
            done = 0
            while count == -1 or done < count:
                self._check_stop()
                self._run_actions(p["actions"], script, win)
                done += 1
        elif atype is ActionType.RUN_SCRIPT:
            if self._storage is None:
                raise _PlayerAbort("run_script 需要腳本儲存來源，但未提供")
            try:
                sub = self._storage.load(p["script_name"])
            except ScriptValidationError as e:
                raise _PlayerAbort(str(e)) from e
            self._execute_script(sub, self._current_depth + 1)
```

同時把檔案頂部的 models import 改為：

```python
from keyboard_executor.core.models import (
    Action,
    ActionType,
    Script,
    ScriptValidationError,
)
```

(g) 新增 `_delay_seconds` 方法：

```python
    def _delay_seconds(self, ms, settings) -> float:
        if isinstance(ms, list):
            base = float(self._rng.randint(ms[0], ms[1]))
        else:
            base = float(ms)
        if settings.humanize_jitter_pct:
            jitter = settings.humanize_jitter_pct
            base *= 1 + self._rng.uniform(-jitter, jitter) / 100
        return base / 1000 / settings.speed
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_flow.py tests/core/test_player_basic.py -v`
Expected: 18 passed（flow 11 + basic 7；basic 不得回歸）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: 109 passed, 1 skipped

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_flow.py
git commit -m "feat: 回放引擎——delay/speed/jitter/repeat/loop/run_script"
```

---

### Task 7: CLI play 子命令與 M2a 驗收

**Files:**
- Create: `src/keyboard_executor/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ScriptStorage`（Task 4）、`Player`/`PlayResult`（Task 5–6）、`ScriptValidationError`（Task 2）、`get_platform`（M1）、darwin 權限檢查（M1，沿用 demo.py 模式）
- Produces:
  - `build_parser() -> argparse.ArgumentParser` — 子命令 `play <name> [--dir DIR]`；`list [--dir DIR]`
  - `default_scripts_dir() -> Path` — `~/.keyboard-executor/scripts`
  - `main(argv=None) -> int` — 0 成功；1 失敗/中斷
  - CLI 進入點：`python -m keyboard_executor.cli play <name>`；Ctrl+C 中斷回報「已中斷」

- [ ] **Step 1: 寫失敗測試**

`tests/test_cli.py`：

```python
from pathlib import Path

import pytest

from keyboard_executor.cli import build_parser, default_scripts_dir


def test_play_parses_name_and_dir():
    args = build_parser().parse_args(["play", "簽到", "--dir", "/tmp/s"])
    assert args.command == "play"
    assert args.name == "簽到"
    assert args.dir == "/tmp/s"


def test_dir_defaults_to_none():
    args = build_parser().parse_args(["play", "x"])
    assert args.dir is None


def test_list_subcommand():
    args = build_parser().parse_args(["list"])
    assert args.command == "list"


def test_command_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_default_scripts_dir_under_home():
    d = default_scripts_dir()
    assert d == Path.home() / ".keyboard-executor" / "scripts"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.cli'`

- [ ] **Step 3: 實作 cli.py**

`src/keyboard_executor/cli.py`：

```python
"""CLI 進入點。

    python -m keyboard_executor.cli list                 # 列出腳本
    python -m keyboard_executor.cli play <腳本名稱>      # 回放（Ctrl+C 可中斷）

腳本目錄預設 ~/.keyboard-executor/scripts，可用 --dir 覆寫。
M2b 將加入 record 子命令（F9 錄製、F10 緊急停止）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.factory import get_platform
from keyboard_executor.storage.scripts import ScriptStorage


def default_scripts_dir() -> Path:
    return Path.home() / ".keyboard-executor" / "scripts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="keyboard-executor CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="回放腳本")
    play.add_argument("name", help="腳本名稱（不含 .json）")
    play.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")

    list_cmd = sub.add_parser("list", help="列出腳本")
    list_cmd.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")
    return parser


def _check_darwin_permissions() -> bool:
    if sys.platform != "darwin":
        return True
    from keyboard_executor.platforms.darwin.permissions import (
        ACCESSIBILITY_GUIDE,
        check_accessibility,
    )

    if not check_accessibility():
        print(ACCESSIBILITY_GUIDE, file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = ScriptStorage(args.dir or default_scripts_dir())

    if args.command == "list":
        names = storage.list_names()
        if not names:
            print("（沒有腳本）")
        for name in names:
            print(name)
        return 0

    # play
    if not _check_darwin_permissions():
        return 1
    try:
        script = storage.load(args.name)
    except ScriptValidationError as e:
        print(f"腳本載入失敗：{e}", file=sys.stderr)
        return 1

    platform = get_platform(game_input_mode=script.settings.game_input_mode)
    player = Player(platform, storage=storage)
    print(f"開始回放：{script.name}（Ctrl+C 可中斷）")
    try:
        result = player.play(script)
    except KeyboardInterrupt:
        print("\n已中斷（Ctrl+C）", file=sys.stderr)
        return 1
    if result.ok:
        print(f"回放完成，共執行 {result.actions_run} 個動作")
        return 0
    print(f"回放中止：{result.error}（已執行 {result.actions_run} 個動作）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 5 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: 114 passed, 1 skipped

- [ ] **Step 6: 建立範例腳本（供手動驗收，不進版控）**

```bash
mkdir -p ~/.keyboard-executor/scripts
cat > ~/.keyboard-executor/scripts/textedit-demo.json << 'EOF'
{
  "name": "textedit-demo",
  "target_window": {"title_pattern": "未命名|Untitled"},
  "settings": {"speed": 1.0, "repeat": 1, "humanize_jitter_pct": 10},
  "actions": [
    {"type": "mouse_click", "x": 200, "y": 200},
    {"type": "text_input", "text": "M2a 回放測試："},
    {"type": "key_press", "key": "enter"},
    {"type": "loop", "count": 3, "actions": [
      {"type": "text_input", "text": "loop! "},
      {"type": "delay", "ms": [200, 500]}
    ]},
    {"type": "key_press", "key": "enter"},
    {"type": "text_input", "text": "完成"}
  ]
}
EOF
python -m keyboard_executor.cli list
```

Expected: 印出 `textedit-demo`

- [ ] **Step 7: 手動驗收（macOS；由人執行——會實際操作滑鼠鍵盤）**

1. 開啟「文字編輯」新文件
2. `python -m keyboard_executor.cli play textedit-demo`
3. Expected：TextEdit 切到前景，輸入標題行後 loop 三次輸入 `loop! `（間隔 0.2–0.5 秒隨機），最後輸出「完成」；CLI 印出 `回放完成，共執行 N 個動作`，exit code 0
4. 再測中斷：把 repeat 改為 -1 後重新 play，執行中按 Ctrl+C → CLI 印「已中斷」，輸入停止

- [ ] **Step 8: Commit**

```bash
git add src/keyboard_executor/cli.py tests/test_cli.py
git commit -m "feat: CLI play/list 子命令（M2a 驗收入口）"
```

---

## 完成定義（M2a）

- [ ] `python -m pytest -q` 全綠（實際 122 passed, 1 skipped——含各審查修正循環新增的測試）
- [ ] 手動驗收（Task 7 Step 7）通過：手寫 JSON 腳本可回放、loop/delay/隨機抖動生效、Ctrl+C 可中斷
- [ ] 腳本驗證錯誤訊息為繁中且不崩潰（壞 JSON、未知欄位、壞 regex 皆有對應測試）

## 後續計畫（不在本計畫範圍）

- M2b：錄製引擎（PynputInputHook + EventKind 型別化、recorder 事件→動作演算法、F9/F10 熱鍵、滑鼠角落 failsafe、CLI record）+ Windows game-mode 覆蓋擴充（text_input/mouse_drag）與 settle 統一
- M3：截圖 + OCR + 模板比對 + 規則引擎（含 Retina 座標換算設計，見 m1-final-review 筆記）
