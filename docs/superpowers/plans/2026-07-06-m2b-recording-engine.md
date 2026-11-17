# M2b 錄製引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 M2 的錄製半邊：`python -m keyboard_executor.cli record` 以 F9 開始/停止全域錄製、F10 放棄，事件轉為 Action 序列（含 key_combo 合成、click/drag 判定、delay 插入、座標相對化）後存成 JSON 腳本；`play` 掛上 F10 熱鍵與滑鼠左上角 failsafe 緊急停止。同時吸收 M2a 最終審查的全部約束（可中斷 sleep、鍵盤動作存活檢查、key 名稱驗證前移）與 M1 遺留的 Windows game-mode 覆蓋擴充。

**Architecture:** platforms 層新增 `PynputInputHook`（pynput listener → 型別化 `InputEvent`）與 `WindowManager.is_alive` 輕量契約；core 層新增 `Recorder`（事件流 → Action 的純演算法）與 `SessionGuard`（F9/F10 熱鍵 + 角落 failsafe 的控制語義），並讓 `Player` 的等待可被 stop_event 中斷。CLI 組裝以上元件成 `record` 子命令，`play` 以 best-effort 方式啟動緊急停止守護。

**Tech Stack:** Python 3.11+（StrEnum）、pynput（keyboard/mouse Listener）、pywinctl、pytest。無新增第三方依賴。

**對應 spec:** `docs/superpowers/specs/2026-07-06-keyboard-executor-design.md` §6（錄製：熱鍵控制、事件收集、簡化/完整軌跡、自我過濾）、§7（回放：緊急停止雙保險、執行期防護）、§10（錯誤處理）、§13-M2。吸收 `docs/superpowers/notes/2026-07-06-m2a-final-review.md`「M2b 計畫必須吸收的約束」全部五項，與 `docs/superpowers/notes/2026-07-06-m1-final-review.md`「M2 規劃時的決策點」1/2/3/4 項。

## Global Constraints

- Python `>=3.11`；src layout：程式碼一律在 `src/keyboard_executor/` 下（spec §4）
- 判斷作業系統（`sys.platform`）只允許出現在 `platforms/` 層；CLI/demo 的 darwin 權限檢查分支沿用已核准的例外模式（`_check_darwin_permissions`，M2a 計畫核准）
- 所有面向使用者的訊息（錯誤、CLI 輸出、docstring 內的操作說明）一律繁體中文
- 外部依賴（listener 類、clock、sleep、rng、stop_event、hook、storage、ask/echo）一律建構子/參數注入，預設真實實作（spec §12）
- 腳本座標一律為「目標視窗左上角為原點」的相對座標；錄製時以錄製當下的視窗左上角為 origin 換算（spec §5.2、§6）
- Commit 訊息用 conventional commits；直接在 main 工作，不開分支（用戶既定選擇）
- TDD：RED 一律用計畫指定的 pytest 指令執行，報告需貼 `rtk proxy python -m pytest ...` 的原始 transcript（避免 rtk 過濾細節）；全套件回歸在 repo 根目錄跑 `python -m pytest -q`
- YAGNI：只實作本計畫列出的行為，不加「順手」的參數或抽象
- 全套件基準（計畫撰寫時已實測）：**122 passed, 1 skipped**；各任務結束時的精確累計總數列在每個任務的回歸步驟

---

### Task 1: 模型收尾批次——keynames 權威名單與驗證前移

M2a 審查行動項 4/5：`key_press.key` 目前載入時只驗「非空字串」，typo（`"entr"`）要到回放才在 keymap 拋錯。把按鍵名稱權威名單抽到 core 純資料模組，載入時就驗證；順帶統一 delay 的 list/tuple 容忍度、`target_window` 空白字串正規化、window_retry 獨立測試。

**Files:**
- Create: `src/keyboard_executor/core/keynames.py`
- Modify: `src/keyboard_executor/core/models.py`
- Modify: `src/keyboard_executor/platforms/common/keymap.py`（僅 docstring）
- Test: `tests/core/test_keynames.py`（新檔）
- Test: `tests/core/test_models_action.py`（追加 4 個測試）
- Test: `tests/core/test_models_script.py`（追加 4 個測試）
- Test: `tests/platforms/test_keymap.py`（追加 1 個測試）
- Modify: `tests/core/test_player_basic.py`（更新 1 個既有測試——驗證前移的配套，見 Step 3b）

**Interfaces:**
- Consumes: 既有 `models.py` 驗證器、`keymap._SPECIAL`
- Produces（Task 5/7 依賴）:
  - `SPECIAL_KEY_NAMES: frozenset[str]` — 修飾鍵（ctrl/control/shift/alt/option/cmd/win/super）+ 導航編輯鍵（enter/return/esc/escape/tab/space/backspace/delete/home/end/pageup/pagedown/up/down/left/right）+ f1–f20
  - `is_valid_key(name: str) -> bool` — strip+lower 後在名單內，或長度為 1 的單一字元
  - `models.py` 行為變更：key_press/key_combo 載入時驗按鍵名稱；delay 的 `ms` 接受 list|tuple（回傳一律 list）；target_window 空白字串正規化為 None（「至少一個」規則不變）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_keynames.py`（新檔）：

```python
from keyboard_executor.core.keynames import SPECIAL_KEY_NAMES, is_valid_key


def test_contains_modifiers_and_aliases():
    for name in ("ctrl", "control", "shift", "alt", "option", "cmd", "win", "super"):
        assert name in SPECIAL_KEY_NAMES


def test_contains_navigation_and_editing_keys():
    for name in ("enter", "return", "esc", "escape", "tab", "space", "backspace",
                 "delete", "home", "end", "pageup", "pagedown", "up", "down", "left", "right"):
        assert name in SPECIAL_KEY_NAMES


def test_contains_f1_to_f20_only():
    for i in range(1, 21):
        assert f"f{i}" in SPECIAL_KEY_NAMES
    assert "f21" not in SPECIAL_KEY_NAMES
    assert "f0" not in SPECIAL_KEY_NAMES


def test_is_valid_key_strips_and_lowercases():
    assert is_valid_key(" F10 ") is True
    assert is_valid_key("CTRL") is True


def test_single_char_is_valid():
    assert is_valid_key("a") is True
    assert is_valid_key("1") is True
    assert is_valid_key("哈") is True  # 單一字元一律合法（KeyCode.from_char 可送出）


def test_unknown_names_are_invalid():
    assert is_valid_key("entr") is False
    assert is_valid_key("") is False
    assert is_valid_key("notakey") is False
```

在 `tests/core/test_models_action.py` 檔尾追加：

```python
def test_key_press_typo_rejected_at_load():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "key_press", "key": "entr"})


def test_key_press_accepts_alias_and_single_char():
    assert action_from_dict({"type": "key_press", "key": "return"}).params["key"] == "return"
    assert action_from_dict({"type": "key_press", "key": "A"}).params["key"] == "A"


def test_key_combo_invalid_key_name_rejected():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "key_combo", "keys": ["ctrl", "sift"]})


def test_delay_accepts_tuple_range():
    a = action_from_dict({"type": "delay", "ms": (50, 150)})
    assert a.params == {"ms": [50, 150]}
```

在 `tests/core/test_models_script.py` 檔尾追加：

```python
def test_target_window_blank_strings_normalized_to_none():
    s = script_from_dict(minimal(target_window={"title_pattern": "   ", "app_name": "Notepad"}))
    assert s.target_window.title_pattern is None
    assert s.target_window.app_name == "Notepad"
    s2 = script_from_dict(minimal(target_window={"title_pattern": "記事本", "app_name": ""}))
    assert s2.target_window.app_name is None


def test_target_window_blank_both_still_raises():
    with pytest.raises(ScriptValidationError, match="至少要提供"):
        script_from_dict(minimal(target_window={"title_pattern": " ", "app_name": ""}))


def test_settings_window_retry_validation():
    with pytest.raises(ScriptValidationError, match="window_retry"):
        script_from_dict(minimal(settings={"window_retry": -1}))
    with pytest.raises(ScriptValidationError, match="window_retry"):
        script_from_dict(minimal(settings={"window_retry": True}))


def test_settings_window_retry_interval_validation():
    with pytest.raises(ScriptValidationError, match="window_retry_interval_ms"):
        script_from_dict(minimal(settings={"window_retry_interval_ms": -1}))
    with pytest.raises(ScriptValidationError, match="window_retry_interval_ms"):
        script_from_dict(minimal(settings={"window_retry_interval_ms": 1.5}))
```

在 `tests/platforms/test_keymap.py` 檔尾追加（鎖定 keymap 名單與 keynames 權威名單一致）：

```python
def test_special_names_match_keynames_authority():
    from keyboard_executor.core.keynames import SPECIAL_KEY_NAMES
    from keyboard_executor.platforms.common.keymap import _SPECIAL
    assert set(_SPECIAL) == SPECIAL_KEY_NAMES
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_keynames.py tests/core/test_models_action.py tests/core/test_models_script.py tests/platforms/test_keymap.py -v`
Expected: FAIL — `test_keynames.py` 整檔 collection error（`ModuleNotFoundError: No module named 'keyboard_executor.core.keynames'`）；`test_key_press_typo_rejected_at_load`、`test_key_combo_invalid_key_name_rejected`、`test_delay_accepts_tuple_range`、`test_target_window_blank_strings_normalized_to_none`、`test_special_names_match_keynames_authority` 失敗。注意：`test_key_press_accepts_alias_and_single_char`、`test_target_window_blank_both_still_raises`、兩個 window_retry 測試針對既有正確行為（迴歸保護），RED 階段就會通過——這是預期的，不要因此改動它們。

- [ ] **Step 3: 實作**

(a) 建立 `src/keyboard_executor/core/keynames.py`：

```python
"""按鍵名稱權威名單（純資料，不依賴 pynput）。

core 層（models 載入驗證、recorder）與 platforms 層（keymap 映射）共用此名單，
確保「載入時驗證通過的名稱」與「keymap 能映射的名稱」一致
（tests/platforms/test_keymap.py 以集合相等測試鎖定）。新增按鍵時兩邊都要改。
"""
from __future__ import annotations

_MODIFIERS = frozenset({"ctrl", "control", "shift", "alt", "option", "cmd", "win", "super"})

_NAVIGATION = frozenset({
    "enter", "return", "esc", "escape", "tab", "space", "backspace", "delete",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
})

_FUNCTION = frozenset(f"f{i}" for i in range(1, 21))

SPECIAL_KEY_NAMES: frozenset[str] = _MODIFIERS | _NAVIGATION | _FUNCTION


def is_valid_key(name: str) -> bool:
    """strip+lower 後在名單內，或為單一字元，即為合法按鍵名稱。"""
    n = name.strip().lower()
    return n in SPECIAL_KEY_NAMES or len(n) == 1
```

(b) 修改 `src/keyboard_executor/core/models.py`——import 區塊 `from typing import Any` 之後加入：

```python
from keyboard_executor.core.keynames import is_valid_key
```

(c) `_validate_key_press` 整個函式替換為（名稱原樣保存，只用 strip+lower 檢查；大小寫由 keymap 回放時處理）：

```python
def _validate_key_press(p: dict) -> dict:
    _check_no_extra(p, "動作 key_press", {"key", "hold_ms"})
    key = _get_str(p, "key_press", "key")
    if not is_valid_key(key):
        _err(f"動作 key_press 欄位 key 不是可用的按鍵名稱: {key!r}")
    return {"key": key,
            "hold_ms": _get_int(p, "key_press", "hold_ms", minimum=0, default=0, required=False)}
```

(d) `_validate_key_combo` 整個函式替換為：

```python
def _validate_key_combo(p: dict) -> dict:
    _check_no_extra(p, "動作 key_combo", {"keys"})
    keys = p.get("keys")
    if not isinstance(keys, list) or not keys:
        _err("動作 key_combo 欄位 keys 必須是至少一個按鍵的清單")
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            _err("動作 key_combo 欄位 keys 型別錯誤：每個按鍵必須是非空字串")
        if not is_valid_key(k):
            _err(f"動作 key_combo 欄位 keys 不是可用的按鍵名稱: {k!r}")
    return {"keys": list(keys)}
```

(e) `_validate_delay` 中的範圍檢查行（`ok = (isinstance(ms, list) and len(ms) == 2` 那一段）替換為（與 `_get_point` 一致的 list|tuple 容忍度）：

```python
    ok = (isinstance(ms, (list, tuple)) and len(ms) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in ms)
          and 0 <= ms[0] <= ms[1])
```

(f) `_validate_target_window` 整個函式替換為（空白字串正規化為 None）：

```python
def _validate_target_window(data: Any) -> TargetWindow:
    if not isinstance(data, dict):
        _err("target_window 必須是 JSON 物件")
    _check_no_extra(data, "target_window", {"title_pattern", "app_name"})
    title = data.get("title_pattern")
    app = data.get("app_name")
    for name, value in (("title_pattern", title), ("app_name", app)):
        if value is not None and not isinstance(value, str):
            _err(f"target_window 欄位 {name} 型別錯誤：必須是字串")
    title = title if title and title.strip() else None
    app = app if app and app.strip() else None
    if title is None and app is None:
        _err("target_window 至少要提供 title_pattern 或 app_name 其中一個")
    if title:
        try:
            re.compile(title)
        except re.error as e:
            _err(f"target_window.title_pattern 不是合法 regex: {e}")
    return TargetWindow(title_pattern=title, app_name=app)
```

(g) `src/keyboard_executor/platforms/common/keymap.py` 第 1 行 docstring 替換為：

```python
"""腳本按鍵名稱（字串）→ pynput 按鍵物件的映射。

名稱集合必須與 core/keynames.py 的 SPECIAL_KEY_NAMES 一致
（tests/platforms/test_keymap.py 以集合相等測試鎖定）；新增按鍵時兩邊都要改。
"""
```

- [ ] **Step 3b: 更新既有測試（驗證前移的配套）**

`tests/core/test_player_basic.py` 的 `test_unexpected_backend_error_returns_result_not_raises` 目前用無效按鍵名 `"entr"` 讓 keymap 在回放期拋錯。驗證前移後 `"entr"` 會在 `make_script(...)` 載入期就被 `ScriptValidationError` 擋下（發生在 `play()` 之前），測試會變成 collection-time error 而非驗證原意。把該測試整段替換為（改用合法鍵名，讓 backend 無條件拋錯——原意「Player 接殺未預期 backend 例外」不變）：

```python
def test_unexpected_backend_error_returns_result_not_raises():
    platform, _, manager = make_platform()

    class ExplodingBackend(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            raise ValueError("backend 內部錯誤")

    platform = Platform(input_backend=ExplodingBackend(), window_manager=manager)
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "未預期錯誤" in result.error
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_keynames.py tests/core/test_models_action.py tests/core/test_models_script.py tests/platforms/test_keymap.py tests/core/test_player_basic.py -v`
Expected: 65 passed（keynames 6 + models_action 25 + models_script 15 + keymap 10 + player_basic 9）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **137 passed, 1 skipped**（122 + 15）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/keynames.py src/keyboard_executor/core/models.py src/keyboard_executor/platforms/common/keymap.py tests/core/test_keynames.py tests/core/test_models_action.py tests/core/test_models_script.py tests/platforms/test_keymap.py tests/core/test_player_basic.py
git commit -m "feat: keynames 權威按鍵名單與載入時驗證前移"
```

---

### Task 2: Player 可中斷 sleep 與 stop 語義文件化

M2a 審查約束 1/3：Player 進執行緒後 SIGINT 救不了長 delay——F10 設 stop_event 時，`time.sleep(300)` 會把緊急停止卡住 5 分鐘。預設 sleep 改用 `stop_event.wait(timeout)`：停止時 wait 提早返回，下一個 `_check_stop()` 中止。同時把「stop_event 不自動清除」的重用語義寫進 docstring。

**Files:**
- Modify: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_stop.py`（新檔）

**Interfaces:**
- Consumes: 既有 `Player` 內部結構
- Produces:
  - `Player.__init__(self, platform, storage=None, stop_event=None, sleep=None, rng=None)` — `sleep=None` 時預設 `lambda seconds: self._stop.wait(seconds) and None`（回傳值丟棄；stop 設定時提早醒來）。**注入 sleep 的既有測試行為完全不變**
  - 文件化契約：Player 不自動清除 stop_event；重用前呼叫端需自行 `stop_event.clear()`

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_stop.py`：

```python
import threading
import time

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_platform():
    backend = FakeInputBackend()
    manager = FakeWindowManager([WindowInfo(handle=object(), title="記事本", app_name="App",
                                            x=0, y=0, width=100, height=100, is_active=False)])
    return Platform(input_backend=backend, window_manager=manager), backend


def make_script(actions):
    return script_from_dict({
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    })


def test_stop_event_interrupts_default_sleep_during_delay():
    platform, backend = make_platform()
    player = Player(platform)  # 不注入 sleep——用預設的可中斷等待
    script = make_script([
        {"type": "delay", "ms": 5000},
        {"type": "key_press", "key": "a"},
    ])
    timer = threading.Timer(0.05, player.stop_event.set)
    timer.start()
    t0 = time.monotonic()
    result = player.play(script)
    elapsed = time.monotonic() - t0
    timer.cancel()
    assert elapsed < 2.0  # 不等滿 5 秒（wait 提早返回）
    assert result.ok is False
    assert "已手動停止" in result.error
    assert backend.calls == []  # delay 後的 key_press 沒有執行


def test_default_sleep_waits_out_delay_when_not_stopped():
    platform, _ = make_platform()
    player = Player(platform)
    script = make_script([{"type": "delay", "ms": 50}])
    t0 = time.monotonic()
    result = player.play(script)
    elapsed = time.monotonic() - t0
    assert result.ok is True
    assert elapsed >= 0.04  # 沒被停止時要等好等滿
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_stop.py -v`
Expected: `test_stop_event_interrupts_default_sleep_during_delay` FAIL（現行 `sleep=time.sleep` 會等滿 5 秒，`elapsed < 2.0` 斷言失敗且 `result.ok` 為 True）；`test_default_sleep_waits_out_delay_when_not_stopped` 已通過（迴歸保護）。RED 這一輪會跑約 5 秒，屬預期。

- [ ] **Step 3: 修改 player.py**

(a) 模組 docstring（第 1–6 行）替換為：

```python
"""回放引擎：把 Script 的動作序列執行到目標視窗。

執行模型：同步逐動作執行。stop_event 在每個動作前檢查，供 Ctrl+C 與
緊急停止熱鍵/failsafe（F10、滑鼠甩左上角，見 core/guard.py）隨時中斷；
未注入 sleep 時，delay/window_retry 的等待本身以 stop_event.wait 實作，
停止時提早醒來。每個座標動作前都重新查詢視窗位置（視窗移動也能點對位
置），視窗消失則安全中止、絕不對其他視窗送輸入。
"""
```

(b) 刪除 `import time`（改用可中斷等待後不再使用）。

(c) `Player` 類別開頭到 `self._sleep = sleep` 為止整段替換為：

```python
class Player:
    """storage 供 run_script 載入子腳本；sleep/rng/stop_event 注入供測試。

    stop 語義：Player 不會自動清除 stop_event。重用同一實例（或共用同一
    stop_event 的新實例）再次 play 前，呼叫端需自行 stop_event.clear()，
    否則第二次 play 會立即以「已手動停止」中止。未注入 sleep 時，預設等待
    以 stop_event.wait 實作：delay / window_retry 等待途中設 stop_event
    會提早醒來，並在下一個停止檢查點（_check_stop）中止。
    """

    def __init__(self, platform: Platform, storage=None, stop_event=None,
                 sleep=None, rng=None):
        self._platform = platform
        self._storage = storage
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep if sleep is not None else (
            lambda seconds: self._stop.wait(seconds) and None)
```

（`__init__` 其餘各行——`self._rng`、`self._actions_run`、`self._script_stack`、`self._current_depth`——保持不變。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_stop.py tests/core/test_player_basic.py tests/core/test_player_flow.py -v`
Expected: 24 passed（stop 2 + basic 9 + flow 13；注入 sleep 的既有測試不得回歸）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **139 passed, 1 skipped**（137 + 2）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_stop.py
git commit -m "feat: Player 預設等待改為可中斷的 stop_event.wait 並文件化 stop 語義"
```

---

### Task 3: EventKind 型別化與 WindowManager.is_alive 契約

M1 審查決策點 3 + M2a 審查約束 2 的契約半邊：`InputEvent.kind` 由裸字串改為 StrEnum（避免字串 typo 流進錄製存檔格式）；`WindowManager` 新增 `is_alive` 輕量存活檢查（不查幾何、不查 appname——macOS 的 getAppName 是百 ms 級 AppleScript，不能在每個按鍵前呼叫 refresh）。

已確認：目前 `tests/` 沒有任何直接建構 `InputEvent` 的用法（grep 驗證），型別化不影響既有測試。但 `WindowManager` 新增抽象方法後，`FakeWindowManager` 若不同步補上會讓所有 player 測試以 `TypeError`（無法實例化抽象類）失敗——實作步驟必須一次完成 base、pywinctl、fakes 三處再跑回歸。

**Files:**
- Modify: `src/keyboard_executor/platforms/base.py`
- Modify: `src/keyboard_executor/platforms/common/window_pywinctl.py`
- Modify: `tests/fakes.py`
- Test: `tests/platforms/test_base.py`（追加 3 個測試）
- Test: `tests/platforms/test_window_pywinctl.py`（追加 3 個測試）

**Interfaces:**
- Consumes: 既有 `InputEvent`/`WindowManager`
- Produces（Task 4/6/7/8/9 依賴）:
  - `EventKind(StrEnum)`: `KEY_DOWN="key_down"`, `KEY_UP="key_up"`, `MOUSE_MOVE="mouse_move"`, `MOUSE_DOWN="mouse_down"`, `MOUSE_UP="mouse_up"`, `SCROLL="scroll"`
  - `InputEvent.kind: EventKind`（其餘欄位不變：`timestamp_ms: int`, `key: str | None`, `x: int | None`, `y: int | None`, `button: MouseButton | None`, `dx: int = 0`, `dy: int = 0`）
  - `WindowManager.is_alive(self, window: WindowInfo) -> bool`（抽象）— 輕量存活檢查
  - `PywinctlWindowManager.is_alive` — `window.handle.isAlive`，任何例外視為已關閉
  - `FakeWindowManager.is_alive` — `window in self.windows`

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_base.py` 頂部 import 行替換為：

```python
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton, WindowInfo
from tests.fakes import FakeInputBackend, FakeWindowManager
```

檔尾追加：

```python
def test_event_kind_values():
    assert EventKind.KEY_DOWN == "key_down"
    assert EventKind("mouse_up") is EventKind.MOUSE_UP


def test_input_event_carries_typed_kind():
    e = InputEvent(kind=EventKind.SCROLL, timestamp_ms=1500, x=10, y=20, dx=0, dy=-3)
    assert e.kind is EventKind.SCROLL
    assert (e.x, e.y, e.dx, e.dy) == (10, 20, 0, -3)


def test_fake_window_manager_is_alive_tracks_windows():
    w = make_window()
    manager = FakeWindowManager([w])
    assert manager.is_alive(w) is True
    manager.windows = []
    assert manager.is_alive(w) is False
```

在 `tests/platforms/test_window_pywinctl.py` 檔尾追加：

```python
class ExplodingWindow:
    """isAlive 一讀就拋例外的視窗物件（模擬 pywinctl 平台相依失效）。"""

    title = "爆炸"

    def __init__(self):
        self.box = SimpleNamespace(left=0, top=0, width=10, height=10)
        self.isActive = False

    def getAppName(self):
        return "App"

    def activate(self):
        pass

    @property
    def isAlive(self):
        raise RuntimeError("視窗物件已失效")


def test_is_alive_true_for_living_window():
    manager, _ = make_manager([StubWindow("目標")])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is True


def test_is_alive_false_when_window_closed():
    manager, _ = make_manager([StubWindow("目標", alive=False)])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is False


def test_is_alive_false_when_handle_raises():
    manager, _ = make_manager([ExplodingWindow()])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_base.py tests/platforms/test_window_pywinctl.py -v`
Expected: FAIL — `ImportError: cannot import name 'EventKind'`（test_base 整檔 collection error）；pywinctl 三個新測試以 `AttributeError: 'PywinctlWindowManager' object has no attribute 'is_alive'` 失敗

- [ ] **Step 3: 實作（三處一次完成）**

(a) `src/keyboard_executor/platforms/base.py`——`MouseButton` 類別之後、`InputEvent` 之前插入：

```python
class EventKind(StrEnum):
    """全域監聽事件類型。"""
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    MOUSE_MOVE = "mouse_move"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    SCROLL = "scroll"
```

(b) `InputEvent` 整個 dataclass 替換為：

```python
@dataclass(frozen=True)
class InputEvent:
    """全域監聽事件。key 為 canonical 按鍵名稱（keymap.key_to_name 產出）；
    x/y 為螢幕絕對座標（平台輸入座標單位，見 core/geometry.py）。"""
    kind: EventKind
    timestamp_ms: int
    key: str | None = None
    x: int | None = None
    y: int | None = None
    button: MouseButton | None = None
    dx: int = 0
    dy: int = 0
```

(c) `WindowManager` 的 `refresh` 之後追加抽象方法：

```python
    @abstractmethod
    def is_alive(self, window: WindowInfo) -> bool:
        """輕量存活檢查：只確認視窗還在，不重新查詢幾何或應用程式名稱
        （macOS 的 getAppName 是百 ms 級 AppleScript，鍵盤動作前勿用 refresh）。"""
        ...
```

(d) `src/keyboard_executor/platforms/common/window_pywinctl.py`——`refresh` 方法之後追加：

```python
    def is_alive(self, window: WindowInfo) -> bool:
        try:
            return bool(window.handle.isAlive)
        except Exception:
            # 視窗物件失效（已關閉）時 pywinctl 可能丟平台相依例外
            return False
```

(e) `tests/fakes.py` 的 `FakeWindowManager`——`refresh` 之後追加：

```python
    def is_alive(self, window: WindowInfo) -> bool:
        return window in self.windows
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_base.py tests/platforms/test_window_pywinctl.py -v`
Expected: 20 passed（base 9 + pywinctl 11）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **145 passed, 1 skipped**（139 + 6）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/base.py src/keyboard_executor/platforms/common/window_pywinctl.py tests/fakes.py tests/platforms/test_base.py tests/platforms/test_window_pywinctl.py
git commit -m "feat: EventKind 型別化與 WindowManager.is_alive 輕量存活契約"
```

---

### Task 4: Player 鍵盤動作前的視窗存活檢查

M2a 審查約束 2 的行為半邊：目前純鍵盤動作（key_press/key_combo/text_input）不查視窗，掛機時目標視窗被關閉後，輸入會流向當下焦點視窗（spec §7「偵測到目標視窗關閉時安全中止，絕不對其他視窗送輸入」的缺口）。在三個鍵盤分支前加 `is_alive` 檢查。

**Files:**
- Modify: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_alive.py`（新檔）

**Interfaces:**
- Consumes: Task 3 的 `WindowManager.is_alive`
- Produces:
  - `Player._ensure_alive(win: WindowInfo) -> None`（私有 helper）— 視窗不存活時 `raise _PlayerAbort("目標視窗已關閉")`
  - 行為契約：KEY_PRESS/KEY_COMBO/TEXT_INPUT 執行前檢查存活；座標動作維持既有 `_to_screen` 的 refresh 檢查（不重複查）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_alive.py`：

```python
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window():
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=0, y=0, width=100, height=100, is_active=False)


class CloseAfterFirstKey(FakeInputBackend):
    """第一個 key_press 執行後把視窗關閉。"""

    def __init__(self, manager):
        super().__init__()
        self._manager = manager

    def key_press(self, key, hold_ms=0):
        super().key_press(key, hold_ms)
        self._manager.windows = []


def make_setup():
    manager = FakeWindowManager([make_window()])
    backend = CloseAfterFirstKey(manager)
    platform = Platform(input_backend=backend, window_manager=manager)
    return platform, backend


def make_script(actions):
    return script_from_dict({
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    })


def test_key_press_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "key_press", "key": "b"},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert result.actions_run == 1
    assert backend.calls == [("key_press", "a", 0)]  # b 沒有送出


def test_key_combo_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "key_combo", "keys": ["ctrl", "s"]},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert backend.calls == [("key_press", "a", 0)]


def test_text_input_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "text_input", "text": "不該出現"},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert backend.calls == [("key_press", "a", 0)]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_alive.py -v`
Expected: 3 failed — 現行鍵盤動作不查視窗，`result.ok` 為 True、第二個動作照樣送進 backend

- [ ] **Step 3: 修改 player.py**

(a) `_to_screen` 方法之後新增：

```python
    def _ensure_alive(self, win: WindowInfo) -> None:
        """鍵盤動作前的輕量存活檢查：視窗關閉即安全中止，不對焦點視窗誤送輸入。"""
        if not self._platform.window_manager.is_alive(win):
            raise _PlayerAbort("目標視窗已關閉")
```

(b) `_run_one` 的三個鍵盤分支替換為：

```python
        if atype is ActionType.KEY_PRESS:
            self._ensure_alive(win)
            backend.key_press(p["key"], p["hold_ms"])
        elif atype is ActionType.KEY_COMBO:
            self._ensure_alive(win)
            backend.key_combo(list(p["keys"]))
        elif atype is ActionType.TEXT_INPUT:
            self._ensure_alive(win)
            backend.type_text(p["text"])
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_alive.py tests/core/test_player_basic.py tests/core/test_player_flow.py tests/core/test_player_stop.py -v`
Expected: 27 passed（alive 3 + basic 9 + flow 13 + stop 2）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **148 passed, 1 skipped**（145 + 3）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_alive.py
git commit -m "feat: Player 鍵盤動作前的視窗存活檢查"
```

---

### Task 5: keymap 反查 key_to_name

錄製方向的映射：pynput listener 給的是 `Key`/`KeyCode` 物件，要反查成我們的 canonical 名稱才能存進腳本。左右修飾鍵變體（ctrl_l/ctrl_r…）一律折疊成 canonical 家族名；`KeyCode` 取 `char.lower()`（M1 審查決策點 4：單字元統一小寫，shift 組合由 key_combo 表達）；無法辨識回傳 None（呼叫端略過該事件）。

**Files:**
- Modify: `src/keyboard_executor/platforms/common/keymap.py`
- Test: `tests/platforms/test_keymap.py`（追加 5 個測試）

**Interfaces:**
- Consumes: `_SPECIAL`（既有）、pynput `Key`/`KeyCode`
- Produces（Task 6 依賴）:
  - `key_to_name(key: Key | KeyCode | None) -> str | None` — 反查 canonical 名稱；反查表以 `_SPECIAL` 的插入順序取「第一個映射到該 Key 的名稱」（canonical 名在別名之前，如 ctrl 在 control 之前，與 keynames 的 canonical 順序一致）；修飾鍵左右變體查 `_MODIFIER_VARIANTS`；`KeyCode` 有 char → `char.lower()`；其餘 → None
  - 往返一致性：對支援的鍵 `parse_key(key_to_name(k))` 成立

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_keymap.py` 的 import 行替換為：

```python
from keyboard_executor.platforms.common.keymap import key_to_name, parse_combo, parse_key
```

檔尾追加：

```python
def test_key_to_name_modifier_variants_collapse_to_canonical():
    assert key_to_name(Key.ctrl_l) == "ctrl"
    assert key_to_name(Key.ctrl_r) == "ctrl"
    assert key_to_name(Key.shift_r) == "shift"
    assert key_to_name(Key.alt_gr) == "alt"
    assert key_to_name(Key.cmd_r) == "cmd"


def test_key_to_name_special_keys_use_canonical_names():
    assert key_to_name(Key.f9) == "f9"
    assert key_to_name(Key.enter) == "enter"
    assert key_to_name(Key.esc) == "esc"
    assert key_to_name(Key.page_up) == "pageup"


def test_key_to_name_char_lowercases():
    assert key_to_name(KeyCode.from_char("A")) == "a"
    assert key_to_name(KeyCode.from_char("1")) == "1"


def test_key_to_name_unknown_returns_none():
    assert key_to_name(Key.media_play_pause) is None
    assert key_to_name(KeyCode(vk=255)) is None
    assert key_to_name(None) is None


def test_key_to_name_round_trips_with_parse_key():
    for key in (Key.ctrl, Key.shift, Key.alt, Key.cmd, Key.enter, Key.esc,
                Key.tab, Key.space, Key.page_up, Key.f1, Key.f20):
        assert parse_key(key_to_name(key)) is key
    assert parse_key(key_to_name(KeyCode.from_char("a"))) == KeyCode.from_char("a")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_keymap.py -v`
Expected: FAIL — `ImportError: cannot import name 'key_to_name'`（整檔 collection error）

- [ ] **Step 3: 在 keymap.py 檔尾追加實作**

```python
# 修飾鍵左右變體 → canonical 名稱（錄製反查用）
_MODIFIER_VARIANTS: dict[Key, str] = {
    Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.shift_l: "shift", Key.shift_r: "shift",
    Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
    Key.cmd_l: "cmd", Key.cmd_r: "cmd",
}

# Key → canonical 名稱：取 _SPECIAL 中第一個映射到該 Key 的名稱
#（_SPECIAL 的插入順序保證 canonical 名在別名之前，如 ctrl 在 control 之前）
_CANONICAL_NAME: dict[Key, str] = {}
for _name, _key in _SPECIAL.items():
    _CANONICAL_NAME.setdefault(_key, _name)


def key_to_name(key: Key | KeyCode | None) -> str | None:
    """pynput 按鍵物件 → canonical 按鍵名稱；不支援的鍵回傳 None（呼叫端略過）。"""
    if isinstance(key, KeyCode):
        if key.char:
            return key.char.lower()
        return None
    if isinstance(key, Key):
        if key in _MODIFIER_VARIANTS:
            return _MODIFIER_VARIANTS[key]
        return _CANONICAL_NAME.get(key)
    return None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_keymap.py -v`
Expected: 15 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **153 passed, 1 skipped**（148 + 5）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/common/keymap.py tests/platforms/test_keymap.py
git commit -m "feat: keymap 反查 key_to_name（pynput 按鍵 → canonical 名稱）"
```

---

### Task 6: PynputInputHook 全域輸入監聽

`InputHook` 的第一個真實實作：把 pynput 的 keyboard/mouse Listener callbacks 轉為型別化 `InputEvent` 送給單一 `on_event`。Listener 類與 clock 注入（測試用 Spy，真實用 lazy import——與 M1 的 pdi 注入模式相同）。

**Files:**
- Create: `src/keyboard_executor/platforms/common/hook_pynput.py`
- Test: `tests/platforms/test_hook_pynput.py`（新檔）

**Interfaces:**
- Consumes: `InputHook`/`InputEvent`/`EventKind`/`MouseButton`（Task 3）、`key_to_name`（Task 5）
- Produces（Task 11 依賴）:
  - `PynputInputHook(keyboard_listener_cls=None, mouse_listener_cls=None, clock=time.monotonic)` —
    - `start(on_event: Callable[[InputEvent], None]) -> None` — 建立並啟動兩個 listener；重複 start → `RuntimeError`（繁中）
    - `stop() -> None` — 停止兩個 listener；stop 後可再 start
  - 事件轉換規則：`timestamp_ms = int(clock() * 1000)`；按鍵用 `key_to_name`，回傳 None 則略過該事件；`on_click` 依 `pressed` 分 MOUSE_DOWN/MOUSE_UP，按鍵以 `button.name` 轉 `MouseButton`，非左/中/右鍵略過；`on_move` 座標取 int；`on_scroll` → SCROLL（x/y/dx/dy）

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_hook_pynput.py`：

```python
from types import SimpleNamespace

import pytest
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook


class SpyListener:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class ListenerFactory:
    """記錄每次建構出的 SpyListener，供測試取用 callbacks。"""

    def __init__(self):
        self.instances = []

    def __call__(self, **callbacks):
        listener = SpyListener(**callbacks)
        self.instances.append(listener)
        return listener


def make_hook(clock_value=1.5):
    kb_factory, mouse_factory = ListenerFactory(), ListenerFactory()
    hook = PynputInputHook(keyboard_listener_cls=kb_factory,
                           mouse_listener_cls=mouse_factory,
                           clock=lambda: clock_value)
    events: list[InputEvent] = []
    hook.start(events.append)
    return hook, kb_factory.instances[0], mouse_factory.instances[0], events


def test_start_starts_keyboard_and_mouse_listeners():
    hook, kb, mouse, _ = make_hook()
    assert kb.started and mouse.started
    assert set(kb.callbacks) == {"on_press", "on_release"}
    assert set(mouse.callbacks) == {"on_move", "on_click", "on_scroll"}


def test_key_press_emits_key_down_with_canonical_name():
    _, kb, _, events = make_hook(clock_value=1.5)
    kb.callbacks["on_press"](Key.f9)
    assert events == [InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=1500, key="f9")]


def test_key_release_emits_key_up_and_lowercases_char():
    _, kb, _, events = make_hook()
    kb.callbacks["on_release"](KeyCode.from_char("A"))
    assert events == [InputEvent(kind=EventKind.KEY_UP, timestamp_ms=1500, key="a")]


def test_unrecognized_key_is_skipped():
    _, kb, _, events = make_hook()
    kb.callbacks["on_press"](Key.media_play_pause)
    assert events == []


def test_click_emits_mouse_down_then_up():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_click"](10, 20, Button.left, True)
    mouse.callbacks["on_click"](10, 20, Button.left, False)
    assert [e.kind for e in events] == [EventKind.MOUSE_DOWN, EventKind.MOUSE_UP]
    assert events[0].button is MouseButton.LEFT
    assert (events[0].x, events[0].y) == (10, 20)


def test_unsupported_button_is_skipped():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_click"](1, 2, SimpleNamespace(name="x1"), True)
    assert events == []


def test_move_emits_mouse_move_with_int_coords():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_move"](10.7, 20.2)
    assert events == [InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=1500, x=10, y=20)]


def test_scroll_emits_scroll_event():
    _, _, mouse, events = make_hook()
    mouse.callbacks["on_scroll"](5, 6, 0, -3)
    assert events == [InputEvent(kind=EventKind.SCROLL, timestamp_ms=1500, x=5, y=6, dx=0, dy=-3)]


def test_double_start_raises_in_chinese():
    hook, _, _, _ = make_hook()
    with pytest.raises(RuntimeError, match="重複啟動"):
        hook.start(lambda e: None)


def test_stop_stops_both_listeners_and_allows_restart():
    hook, kb, mouse, _ = make_hook()
    hook.stop()
    assert kb.stopped and mouse.stopped
    hook.start(lambda e: None)  # stop 後可重新 start，不拋錯
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_hook_pynput.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.common.hook_pynput'`

- [ ] **Step 3: 實作 hook_pynput.py**

`src/keyboard_executor/platforms/common/hook_pynput.py`：

```python
"""pynput 全域輸入監聽：把 keyboard/mouse Listener callbacks 轉為 InputEvent。

macOS 需要「輸入監控」權限；缺權限時 pynput 可能靜默收不到事件（不一定拋錯），
CLI 層以繁中訊息提示（見 cli.py）。Listener 類注入供測試；None 時 lazy import
真實 pynput Listener（與 win32 input 的 pdi 注入模式一致）。
"""
from __future__ import annotations

import time
from typing import Callable

from keyboard_executor.platforms.base import (
    EventKind,
    InputEvent,
    InputHook,
    MouseButton,
)
from keyboard_executor.platforms.common.keymap import key_to_name

_BUTTON_NAMES = {
    "left": MouseButton.LEFT,
    "right": MouseButton.RIGHT,
    "middle": MouseButton.MIDDLE,
}


class PynputInputHook(InputHook):
    def __init__(self, keyboard_listener_cls=None, mouse_listener_cls=None,
                 clock=time.monotonic):
        self._kb_cls = keyboard_listener_cls
        self._mouse_cls = mouse_listener_cls
        self._clock = clock
        self._kb_listener = None
        self._mouse_listener = None
        self._on_event: Callable[[InputEvent], None] | None = None

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        if self._kb_listener is not None:
            raise RuntimeError("輸入監聽已啟動，不能重複啟動")
        kb_cls = self._kb_cls
        mouse_cls = self._mouse_cls
        if kb_cls is None:
            from pynput import keyboard
            kb_cls = keyboard.Listener
        if mouse_cls is None:
            from pynput import mouse
            mouse_cls = mouse.Listener
        self._on_event = on_event
        self._kb_listener = kb_cls(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener = mouse_cls(
            on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll)
        self._kb_listener.start()
        self._mouse_listener.start()

    def stop(self) -> None:
        if self._kb_listener is not None:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        self._on_event = None

    # -- pynput callbacks → InputEvent --

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _emit(self, event: InputEvent) -> None:
        if self._on_event is not None:  # stop 後 listener 執行緒可能還送遲到事件
            self._on_event(event)

    def _on_press(self, key) -> None:
        name = key_to_name(key)
        if name is None:
            return  # 不支援的鍵（媒體鍵等）：略過，不進錄製
        self._emit(InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=self._now_ms(), key=name))

    def _on_release(self, key) -> None:
        name = key_to_name(key)
        if name is None:
            return
        self._emit(InputEvent(kind=EventKind.KEY_UP, timestamp_ms=self._now_ms(), key=name))

    def _on_move(self, x, y) -> None:
        self._emit(InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y)))

    def _on_click(self, x, y, button, pressed) -> None:
        mb = _BUTTON_NAMES.get(getattr(button, "name", None))
        if mb is None:
            return  # 左/中/右以外的按鍵：略過
        kind = EventKind.MOUSE_DOWN if pressed else EventKind.MOUSE_UP
        self._emit(InputEvent(kind=kind, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y), button=mb))

    def _on_scroll(self, x, y, dx, dy) -> None:
        self._emit(InputEvent(kind=EventKind.SCROLL, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y), dx=int(dx), dy=int(dy)))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_hook_pynput.py -v`
Expected: 10 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **163 passed, 1 skipped**（153 + 10）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/common/hook_pynput.py tests/platforms/test_hook_pynput.py
git commit -m "feat: PynputInputHook 全域輸入監聽（InputHook 首個真實實作）"
```

---

### Task 7: Recorder 錄製引擎——鍵盤與延遲

事件流 → Action 的純演算法（core 層，不碰平台 API）。本任務先做鍵盤合成與 delay 插入；滑鼠在 Task 8。

演算法（spec §6）：
- 追蹤按住中的修飾鍵（canonical 家族名 ctrl/shift/alt/cmd——`key_to_name` 已把左右變體與別名正規化，Recorder 只需認這四個）
- KEY_DOWN 修飾鍵 → 加入 held 集合，不輸出動作
- KEY_DOWN 非修飾鍵 → held 非空時輸出 `key_combo([按 ctrl,shift,alt,cmd 固定順序排列的 held..., key])`；否則輸出 `key_press(key)`
- KEY_UP 修飾鍵 → 移出 held；KEY_UP 非修飾鍵 → 忽略
- 兩個「輸出動作」的觸發事件時間差 `dt_ms >= 50` → 先插入 `delay {"ms": dt_ms}`（第一個動作前不插）
- 產出的 `Action` params 形狀與 `action_from_dict` 正規化後一致（含 `hold_ms: 0`），保證存檔後可原樣載回

**Files:**
- Create: `src/keyboard_executor/core/recorder.py`
- Test: `tests/core/test_recorder_keys.py`（新檔）

**Interfaces:**
- Consumes: `Action`/`ActionType`（models）、`Point`（geometry）、`InputEvent`/`EventKind`（Task 3）
- Produces（Task 8/11 依賴）:
  - `Recorder(origin: Point, mode: str = "simplified")` — mode 僅接受 `"simplified"`/`"full"`，其他 → `ValueError`（繁中）
    - `feed(event: InputEvent) -> None`
    - `finish() -> list[Action]` — 回傳 `models.Action` 清單（副本）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_recorder_keys.py`：

```python
import pytest

from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ActionType, action_from_dict, action_to_dict
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.platforms.base import EventKind, InputEvent


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


def record(events, mode="simplified"):
    recorder = Recorder(Point(0, 0), mode=mode)
    for e in events:
        recorder.feed(e)
    return recorder.finish()


def test_plain_typing_becomes_key_presses():
    actions = record([key_down("h", 0), key_up("h", 10), key_down("i", 20), key_up("i", 30)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "h", "hold_ms": 0}),
        (ActionType.KEY_PRESS, {"key": "i", "hold_ms": 0}),
    ]


def test_ctrl_hold_plus_s_becomes_combo():
    actions = record([key_down("ctrl", 0), key_down("s", 30),
                      key_up("s", 40), key_up("ctrl", 45)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_COMBO, {"keys": ["ctrl", "s"]}),
    ]


def test_modifier_order_is_fixed_ctrl_shift_alt_cmd():
    actions = record([key_down("shift", 0), key_down("ctrl", 10), key_down("a", 20)])
    assert actions[0].params == {"keys": ["ctrl", "shift", "a"]}


def test_multiple_keys_under_held_modifier_each_become_combo():
    actions = record([
        key_down("ctrl", 0),
        key_down("a", 10), key_up("a", 15),
        key_down("b", 30), key_up("b", 35),
        key_up("ctrl", 40),
    ])
    assert [a.params for a in actions] == [
        {"keys": ["ctrl", "a"]},
        {"keys": ["ctrl", "b"]},
    ]


def test_released_modifier_no_longer_combines():
    actions = record([key_down("ctrl", 0), key_up("ctrl", 10), key_down("a", 20)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "a", "hold_ms": 0}),
    ]


def test_gap_of_50ms_or_more_inserts_delay():
    actions = record([key_down("a", 0), key_down("b", 300)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "a", "hold_ms": 0}),
        (ActionType.DELAY, {"ms": 300}),
        (ActionType.KEY_PRESS, {"key": "b", "hold_ms": 0}),
    ]


def test_gap_under_50ms_has_no_delay():
    actions = record([key_down("a", 0), key_down("b", 30)])
    assert [a.type for a in actions] == [ActionType.KEY_PRESS, ActionType.KEY_PRESS]


def test_no_delay_before_first_action():
    actions = record([key_down("a", 99999)])
    assert [a.type for a in actions] == [ActionType.KEY_PRESS]


def test_recorded_actions_round_trip_through_models():
    actions = record([key_down("ctrl", 0), key_down("s", 10), key_down("a", 200)])
    assert len(actions) == 3  # combo, delay(190), combo
    for action in actions:
        assert action_from_dict(action_to_dict(action)) == action


def test_invalid_mode_raises_in_chinese():
    with pytest.raises(ValueError, match="未知的錄製模式"):
        Recorder(Point(0, 0), mode="fancy")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_recorder_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.recorder'`

- [ ] **Step 3: 實作 recorder.py（鍵盤部分）**

`src/keyboard_executor/core/recorder.py`：

```python
"""錄製引擎：把 InputHook 的事件流轉為 Action 序列（純邏輯，不碰平台 API）。

演算法（spec §6）：
- 修飾鍵（ctrl/shift/alt/cmd）按住時按下的一般鍵 → key_combo；否則 key_press
- 相鄰輸出動作的觸發事件時間差 >= 50ms → 先插入 delay
- 滑鼠 down/up 位移（Chebyshev）<= 5px → mouse_click，否則 mouse_drag（Task 8）
- 座標一律轉為視窗相對座標（origin = 錄製當下的視窗左上角）
- 控制熱鍵（F9/F10）由呼叫端以 SessionGuard.is_control_event 過濾，不會進到 feed
- 產出的 Action params 形狀與 action_from_dict 正規化結果一致，存檔後可原樣載回
"""
from __future__ import annotations

from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import Action, ActionType
from keyboard_executor.platforms.base import EventKind, InputEvent

# 修飾鍵 canonical 名稱與 combo 內的固定順序（key_to_name 已把左右變體/別名正規化）
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "cmd")
_MODIFIERS = frozenset(_MODIFIER_ORDER)

_MIN_DELAY_MS = 50  # 相鄰輸出動作間隔 >= 此值才插入 delay


class Recorder:
    """mode: "simplified"（預設，丟棄滑鼠移動軌跡）或 "full"（取樣保留 mouse_move）。"""

    def __init__(self, origin: Point, mode: str = "simplified"):
        if mode not in ("simplified", "full"):
            raise ValueError(f"未知的錄製模式: {mode!r}")
        self._origin = origin
        self._mode = mode
        self._actions: list[Action] = []
        self._held: set[str] = set()
        self._last_output_ts: int | None = None

    def feed(self, event: InputEvent) -> None:
        if event.kind is EventKind.KEY_DOWN:
            self._on_key_down(event)
        elif event.kind is EventKind.KEY_UP:
            self._held.discard(event.key)

    def finish(self) -> list[Action]:
        return list(self._actions)

    # -- 鍵盤 --

    def _on_key_down(self, event: InputEvent) -> None:
        key = event.key
        if key in _MODIFIERS:
            self._held.add(key)
            return
        if self._held:
            keys = [m for m in _MODIFIER_ORDER if m in self._held] + [key]
            self._output(Action(type=ActionType.KEY_COMBO, params={"keys": keys}),
                         event.timestamp_ms)
        else:
            self._output(Action(type=ActionType.KEY_PRESS,
                                params={"key": key, "hold_ms": 0}),
                         event.timestamp_ms)

    # -- 共用輸出（含 delay 插入） --

    def _output(self, action: Action, timestamp_ms: int) -> None:
        if self._last_output_ts is not None:
            dt = timestamp_ms - self._last_output_ts
            if dt >= _MIN_DELAY_MS:
                self._actions.append(Action(type=ActionType.DELAY, params={"ms": dt}))
        self._actions.append(action)
        self._last_output_ts = timestamp_ms
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_recorder_keys.py -v`
Expected: 10 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **173 passed, 1 skipped**（163 + 10）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/recorder.py tests/core/test_recorder_keys.py
git commit -m "feat: Recorder 錄製引擎——鍵盤合成（key_press/key_combo）與 delay 插入"
```

---

### Task 8: Recorder 錄製引擎——滑鼠與軌跡模式

滑鼠部分：down/up 配對成 click（Chebyshev 位移 `max(|dx|,|dy|) <= 5px`，用 down 的座標）或 drag（起迄座標）；scroll 直接輸出；mouse_move 在 simplified 模式忽略、full 模式以 100ms 取樣（第一個 move 保留）；拖曳進行中（pending down 存在）兩種模式都忽略 move（drag 已含起迄）。座標一律 `to_relative(origin, ...)`。delay 規則沿用 Task 7。

**Files:**
- Modify: `src/keyboard_executor/core/recorder.py`
- Test: `tests/core/test_recorder_mouse.py`（新檔）

**Interfaces:**
- Consumes: Task 7 的 `Recorder` 內部結構、`to_relative`（geometry）
- Produces:
  - MOUSE_DOWN → 記 pending（button, x, y, ts）；pending 已存在時忽略其他按鍵的 down（不支援多鍵拖曳，先到者優先）
  - MOUSE_UP 同鍵 → 位移 <= 5px 輸出 `mouse_click {x, y, button, count: 1}`（down 座標），否則 `mouse_drag {from, to, button}`；不同鍵或無 pending → 忽略
  - SCROLL → `scroll {x, y, dx, dy}`（相對座標）
  - MOUSE_MOVE → 依模式/取樣輸出 `mouse_move {x, y}`

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_recorder_mouse.py`：

```python
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ActionType
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton

ORIGIN = Point(100, 200)


def mouse_down(x, y, ts=0, button=MouseButton.LEFT):
    return InputEvent(kind=EventKind.MOUSE_DOWN, timestamp_ms=ts, x=x, y=y, button=button)


def mouse_up(x, y, ts=0, button=MouseButton.LEFT):
    return InputEvent(kind=EventKind.MOUSE_UP, timestamp_ms=ts, x=x, y=y, button=button)


def mouse_move(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=ts, x=x, y=y)


def scroll(x, y, dx=0, dy=0, ts=0):
    return InputEvent(kind=EventKind.SCROLL, timestamp_ms=ts, x=x, y=y, dx=dx, dy=dy)


def record(events, mode="simplified"):
    recorder = Recorder(ORIGIN, mode=mode)
    for e in events:
        recorder.feed(e)
    return recorder.finish()


def test_down_up_without_movement_is_click_at_relative_coords():
    actions = record([mouse_down(150, 260, ts=0), mouse_up(150, 260, ts=30)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_CLICK, {"x": 50, "y": 60, "button": "left", "count": 1}),
    ]


def test_displacement_within_5px_still_click_uses_down_coords():
    actions = record([mouse_down(150, 260, ts=0), mouse_up(155, 264, ts=30)])
    assert actions[0].type is ActionType.MOUSE_CLICK
    assert (actions[0].params["x"], actions[0].params["y"]) == (50, 60)


def test_displacement_beyond_5px_becomes_drag():
    actions = record([mouse_down(150, 260, ts=0, button=MouseButton.RIGHT),
                      mouse_up(200, 300, ts=30, button=MouseButton.RIGHT)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_DRAG, {"from": [50, 60], "to": [100, 100], "button": "right"}),
    ]


def test_scroll_records_relative_position_and_deltas():
    actions = record([scroll(110, 220, dx=0, dy=-3)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.SCROLL, {"x": 10, "y": 20, "dx": 0, "dy": -3}),
    ]


def test_simplified_mode_drops_mouse_moves():
    actions = record([mouse_move(110, 210, ts=0), mouse_move(120, 220, ts=200)])
    assert actions == []


def test_full_mode_samples_moves_every_100ms():
    actions = record([
        mouse_move(110, 210, ts=0),    # 第一個 move 保留
        mouse_move(111, 211, ts=50),   # 距上次保留 50ms < 100ms，丟棄
        mouse_move(120, 220, ts=120),  # 120ms >= 100ms，保留
        mouse_move(130, 230, ts=300),  # 180ms >= 100ms，保留
    ], mode="full")
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_MOVE, {"x": 10, "y": 10}),
        (ActionType.DELAY, {"ms": 120}),
        (ActionType.MOUSE_MOVE, {"x": 20, "y": 20}),
        (ActionType.DELAY, {"ms": 180}),
        (ActionType.MOUSE_MOVE, {"x": 30, "y": 30}),
    ]


def test_moves_during_drag_are_ignored_in_both_modes():
    for mode in ("simplified", "full"):
        actions = record([
            mouse_down(150, 260, ts=0),
            mouse_move(180, 280, ts=40),
            mouse_move(200, 300, ts=200),
            mouse_up(200, 300, ts=240),
        ], mode=mode)
        assert [a.type for a in actions] == [ActionType.MOUSE_DRAG]


def test_mouse_up_without_down_is_ignored():
    actions = record([mouse_up(150, 260, ts=0)])
    assert actions == []


def test_delay_inserted_between_clicks():
    actions = record([
        mouse_down(150, 260, ts=0), mouse_up(150, 260, ts=20),
        mouse_down(160, 270, ts=520), mouse_up(160, 270, ts=540),
    ])
    assert [a.type for a in actions] == [
        ActionType.MOUSE_CLICK, ActionType.DELAY, ActionType.MOUSE_CLICK,
    ]
    assert actions[1].params == {"ms": 520}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_recorder_mouse.py -v`
Expected: 9 failed — 現行 `feed` 對滑鼠事件不動作，`actions` 為空（`test_simplified_mode_drops_mouse_moves`、`test_mouse_up_without_down_is_ignored` 兩個此時恰好通過——它們是行為邊界的迴歸保護，其餘 7 個失敗）

- [ ] **Step 3: 修改 recorder.py 加入滑鼠處理**

(a) import 行 `from keyboard_executor.core.geometry import Point` 替換為：

```python
from keyboard_executor.core.geometry import Point, to_relative
```

(b) 常數區 `_MIN_DELAY_MS = 50` 之後追加：

```python
_CLICK_TOLERANCE_PX = 5  # down/up Chebyshev 位移 <= 此值視為點擊
_MOVE_SAMPLE_MS = 100    # full 模式 mouse_move 取樣間隔
```

(c) `__init__` 末尾（`self._last_output_ts = None` 之後）追加：

```python
        self._pending_down: tuple | None = None  # (button, x, y, ts)，拖曳/點擊配對用
        self._last_move_ts: int | None = None    # full 模式最後保留的 move 時間
```

(d) `feed` 整個方法替換為：

```python
    def feed(self, event: InputEvent) -> None:
        if event.kind is EventKind.KEY_DOWN:
            self._on_key_down(event)
        elif event.kind is EventKind.KEY_UP:
            self._held.discard(event.key)
        elif event.kind is EventKind.MOUSE_DOWN:
            self._on_mouse_down(event)
        elif event.kind is EventKind.MOUSE_UP:
            self._on_mouse_up(event)
        elif event.kind is EventKind.MOUSE_MOVE:
            self._on_mouse_move(event)
        elif event.kind is EventKind.SCROLL:
            self._on_scroll(event)
```

(e) `_on_key_down` 之後（`_output` 之前）追加滑鼠方法：

```python
    # -- 滑鼠 --

    def _on_mouse_down(self, event: InputEvent) -> None:
        if self._pending_down is not None:
            return  # 已有按鍵按住（拖曳中）：忽略其他按鍵的 down（不支援多鍵拖曳）
        self._pending_down = (event.button, event.x, event.y, event.timestamp_ms)

    def _on_mouse_up(self, event: InputEvent) -> None:
        if self._pending_down is None or event.button != self._pending_down[0]:
            return
        button, down_x, down_y, _down_ts = self._pending_down
        self._pending_down = None
        rel_down = to_relative(self._origin, Point(down_x, down_y))
        moved = max(abs(event.x - down_x), abs(event.y - down_y))  # Chebyshev 位移
        if moved <= _CLICK_TOLERANCE_PX:
            self._output(Action(type=ActionType.MOUSE_CLICK,
                                params={"x": rel_down.x, "y": rel_down.y,
                                        "button": str(button), "count": 1}),
                         event.timestamp_ms)
        else:
            rel_up = to_relative(self._origin, Point(event.x, event.y))
            self._output(Action(type=ActionType.MOUSE_DRAG,
                                params={"from": [rel_down.x, rel_down.y],
                                        "to": [rel_up.x, rel_up.y],
                                        "button": str(button)}),
                         event.timestamp_ms)

    def _on_mouse_move(self, event: InputEvent) -> None:
        if self._pending_down is not None:
            return  # 拖曳進行中：drag 已含起迄，不記錄中途移動
        if self._mode != "full":
            return  # simplified：丟棄移動軌跡
        if (self._last_move_ts is not None
                and event.timestamp_ms - self._last_move_ts < _MOVE_SAMPLE_MS):
            return
        rel = to_relative(self._origin, Point(event.x, event.y))
        self._output(Action(type=ActionType.MOUSE_MOVE, params={"x": rel.x, "y": rel.y}),
                     event.timestamp_ms)
        self._last_move_ts = event.timestamp_ms

    def _on_scroll(self, event: InputEvent) -> None:
        rel = to_relative(self._origin, Point(event.x, event.y))
        self._output(Action(type=ActionType.SCROLL,
                            params={"x": rel.x, "y": rel.y,
                                    "dx": event.dx, "dy": event.dy}),
                     event.timestamp_ms)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_recorder_mouse.py tests/core/test_recorder_keys.py -v`
Expected: 19 passed（mouse 9 + keys 10；鍵盤測試不得回歸）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **182 passed, 1 skipped**（173 + 9）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/recorder.py tests/core/test_recorder_mouse.py
git commit -m "feat: Recorder 錄製引擎——click/drag 判定、scroll、簡化與完整軌跡模式"
```

---

### Task 9: SessionGuard——F9/F10 熱鍵與左上角 failsafe

錄製與回放共用的控制語義（spec §6 熱鍵控制/自我過濾、§7 緊急停止雙保險）：F10 按下 → `stop_event.set()`；F9 按下 → `on_toggle()`；滑鼠移進螢幕左上角 `corner_size` 範圍 → `stop_event.set()`（failsafe）。`is_control_event()` 供錄製流程過濾控制鍵本身（不錄進腳本）。

**設計說明（相對鎖定決策的最小調整）**：鎖定決策把事件處理入口寫為 `_handle`；此處公開為 `handle`——因為同一個 hook 只能 `start` 一次（`PynputInputHook` 重複 start 會拋錯），Task 11 的錄製流程必須用自己的 dispatcher 同時做「控制處理」與「事件轉送給 Recorder」，控制處理入口必須可由外部 dispatcher 呼叫。`start()` 仍照鎖定設計把 `handle` 掛給 `hook.start`（回放路徑獨占 hook 時的便利入口），行為完全一致。

**Files:**
- Create: `src/keyboard_executor/core/guard.py`
- Modify: `tests/fakes.py`（新增 `FakeInputHook`）
- Test: `tests/core/test_guard.py`（新檔）

**Interfaces:**
- Consumes: `InputHook`/`InputEvent`/`EventKind`（Task 3）
- Produces（Task 11 依賴）:
  - `SessionGuard(hook: InputHook, stop_event: threading.Event, on_toggle: Callable[[], None] | None = None, toggle_key: str = "f9", stop_key: str = "f10", corner_size: int = 5)`
    - `start() -> None` — `hook.start(self.handle)`；`stop() -> None` — `hook.stop()`
    - `handle(event: InputEvent) -> None` — 控制語義（可由外部 dispatcher 呼叫）
    - `is_control_event(event: InputEvent) -> bool` — 事件是否為 toggle/stop 鍵的 down/up
  - `tests/fakes.py` 的 `FakeInputHook` — 記 `on_event`/start/stop 次數，`push(event)` 手動注入事件

- [ ] **Step 1: 寫失敗測試**

在 `tests/fakes.py` 頂部 import 區塊改為（新增 `Callable` 與 `InputEvent`/`InputHook`）：

```python
"""core 層測試用的平台假實作。"""
from __future__ import annotations

import re
from typing import Callable

from keyboard_executor.platforms.base import (
    InputBackend,
    InputEvent,
    InputHook,
    MouseButton,
    WindowInfo,
    WindowManager,
)
```

`tests/fakes.py` 檔尾追加：

```python
class FakeInputHook(InputHook):
    """測試用輸入監聽：不開真實 listener，由測試以 push() 注入事件。"""

    def __init__(self) -> None:
        self.on_event: Callable[[InputEvent], None] | None = None
        self.started = 0
        self.stopped = 0

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        self.on_event = on_event
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def push(self, event: InputEvent) -> None:
        assert self.on_event is not None, "hook 尚未 start"
        self.on_event(event)
```

`tests/core/test_guard.py`：

```python
import threading

from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.platforms.base import EventKind, InputEvent
from tests.fakes import FakeInputHook


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


def mouse_move(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=ts, x=x, y=y)


def make_guard(**kwargs):
    hook = FakeInputHook()
    stop = threading.Event()
    guard = SessionGuard(hook, stop, **kwargs)
    guard.start()
    return guard, hook, stop


def test_stop_key_down_sets_stop_event():
    _, hook, stop = make_guard()
    hook.push(key_down("f10"))
    assert stop.is_set()


def test_toggle_key_calls_on_toggle_per_key_down_only():
    toggles = []
    _, hook, stop = make_guard(on_toggle=lambda: toggles.append(1))
    hook.push(key_down("f9"))
    hook.push(key_up("f9"))
    hook.push(key_down("f9"))
    assert len(toggles) == 2  # 只有 down 觸發，up 不觸發
    assert not stop.is_set()


def test_toggle_without_callback_is_noop():
    _, hook, stop = make_guard()  # on_toggle=None
    hook.push(key_down("f9"))
    assert not stop.is_set()


def test_corner_move_triggers_failsafe():
    _, hook, stop = make_guard()
    hook.push(mouse_move(3, 4))
    assert stop.is_set()


def test_move_outside_corner_does_not_stop():
    _, hook, stop = make_guard()
    hook.push(mouse_move(6, 0))
    hook.push(mouse_move(0, 6))
    hook.push(mouse_move(100, 100))
    assert not stop.is_set()


def test_is_control_event_matches_toggle_and_stop_keys_only():
    guard, _, _ = make_guard()
    assert guard.is_control_event(key_down("f9")) is True
    assert guard.is_control_event(key_up("f9")) is True
    assert guard.is_control_event(key_down("f10")) is True
    assert guard.is_control_event(key_down("a")) is False
    assert guard.is_control_event(mouse_move(0, 0)) is False


def test_start_and_stop_delegate_to_hook():
    guard, hook, _ = make_guard()
    assert hook.started == 1
    guard.stop()
    assert hook.stopped == 1


def test_custom_keys():
    toggles = []
    guard, hook, stop = make_guard(on_toggle=lambda: toggles.append(1),
                                   toggle_key="f5", stop_key="f6")
    hook.push(key_down("f9"))  # 換鍵後 f9 不再是控制鍵
    hook.push(key_down("f5"))
    hook.push(key_down("f6"))
    assert len(toggles) == 1
    assert stop.is_set()
    assert guard.is_control_event(key_down("f5")) is True
    assert guard.is_control_event(key_down("f9")) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.guard'`

- [ ] **Step 3: 實作 guard.py**

`src/keyboard_executor/core/guard.py`：

```python
"""錄製/回放共用的全域控制守護：熱鍵與滑鼠角落 failsafe（spec §6/§7）。

- stop_key（預設 F10）按下 → stop_event.set()（緊急停止/放棄錄製）
- toggle_key（預設 F9）按下 → on_toggle()（錄製開始/停止；未提供則忽略）
- 滑鼠移進螢幕左上角 corner_size 範圍 → stop_event.set()（failsafe）
- is_control_event() 供錄製流程過濾控制鍵本身（自我過濾，不錄進腳本）

handle() 為公開方法：獨占 hook 時用 start() 直接掛上；錄製流程（cli.run_record）
用自己的 dispatcher 先呼叫 handle() 再決定是否轉送給 Recorder——同一個 hook
只能 start 一次，控制與轉送必須共用同一條事件流。
"""
from __future__ import annotations

import threading
from typing import Callable

from keyboard_executor.platforms.base import EventKind, InputEvent, InputHook


class SessionGuard:
    def __init__(self, hook: InputHook, stop_event: threading.Event,
                 on_toggle: Callable[[], None] | None = None,
                 toggle_key: str = "f9", stop_key: str = "f10",
                 corner_size: int = 5):
        self._hook = hook
        self._stop_event = stop_event
        self._on_toggle = on_toggle
        self._toggle_key = toggle_key
        self._stop_key = stop_key
        self._corner_size = corner_size

    def start(self) -> None:
        """獨占使用 hook 時的便利入口（回放路徑）。"""
        self._hook.start(self.handle)

    def stop(self) -> None:
        self._hook.stop()

    def handle(self, event: InputEvent) -> None:
        """處理單一事件的控制語義（hook callback；也可由外部 dispatcher 呼叫）。"""
        if event.kind is EventKind.KEY_DOWN:
            if event.key == self._stop_key:
                self._stop_event.set()
            elif event.key == self._toggle_key and self._on_toggle is not None:
                self._on_toggle()
        elif event.kind is EventKind.MOUSE_MOVE:
            if (event.x is not None and event.y is not None
                    and 0 <= event.x <= self._corner_size
                    and 0 <= event.y <= self._corner_size):
                self._stop_event.set()

    def is_control_event(self, event: InputEvent) -> bool:
        """事件是否為控制鍵（toggle/stop）本身的 down/up——錄製時應過濾，不錄進腳本。"""
        return (event.kind in (EventKind.KEY_DOWN, EventKind.KEY_UP)
                and event.key in (self._toggle_key, self._stop_key))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_guard.py -v`
Expected: 8 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **190 passed, 1 skipped**（182 + 8）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/guard.py tests/fakes.py tests/core/test_guard.py
git commit -m "feat: SessionGuard——F9/F10 全域熱鍵與滑鼠左上角 failsafe"
```

---

### Task 10: Win32 game-mode 覆蓋擴充與 settle 統一

M1 審查決策點 1/2：game mode 下 `text_input`/`mouse_drag` 目前仍走 SendInput，在攔截虛擬鍵碼的遊戲中靜默失效；settle 政策不一致（pdi click 無 settle、scroll 無 settle）。統一：(1) `pdi.PAUSE = 0` 對注入的 pdi 也設定；(2) game-mode `type_text` 全 ASCII 可列印字元時逐字 `pdi.press`，否則 fallback pynput；(3) game-mode `mouse_drag` 走 pdi moveTo/mouseDown/moveTo/mouseUp（各步間 settle）；(4) game-mode `mouse_click` 在 moveTo 後 settle；(5) 共用層 `scroll` 移動後 settle。

**注意（既有測試破壞點）**：(5) 會讓 `tests/platforms/test_input_pynput.py` 的 `test_scroll_moves_then_scrolls` 的 sleeps 期望改變，本任務同步更新該測試（本計畫修改既有測試的兩處之一；另一處是 Task 1 Step 3b 的 `test_player_basic.py` 配套更新）。

**Files:**
- Modify: `src/keyboard_executor/platforms/win32/input.py`（整檔替換）
- Modify: `src/keyboard_executor/platforms/common/input_pynput.py`（scroll 加 settle）
- Modify: `tests/platforms/test_input_pynput.py`（更新 1 個既有測試）
- Test: `tests/platforms/test_win32_input.py`（SpyPdi 擴充 + 追加 5 個測試）

**Interfaces:**
- Consumes: `PynputInputBackend`/`_SETTLE`（M1）、pydirectinput 介面（keyDown/keyUp/press/moveTo/click/mouseDown/mouseUp/PAUSE）
- Produces:
  - `Win32InputBackend.type_text(text)` — game mode 且 `text` 全為 ASCII 可列印字元（`" " <= ch <= "~"`）時逐字 `pdi.press(ch)`；否則 `super().type_text(text)`
  - `Win32InputBackend.mouse_drag(...)` — game mode 走 `pdi.moveTo(from) → settle → pdi.mouseDown(button) → settle → pdi.moveTo(to) → settle → pdi.mouseUp(button)`
  - `Win32InputBackend.mouse_click(...)` — game mode 在 moveTo 後加 settle
  - `PynputInputBackend.scroll(...)` — 移動後 settle 再捲動（統一政策）
  - `pdi.PAUSE = 0` 於建構時設定（含注入的 pdi）

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_win32_input.py` 的 `SpyPdi` 類別追加三個方法（`click` 之後）：

```python
    def press(self, key):
        self.ops.append(("press", key))

    def mouseDown(self, button):
        self.ops.append(("mouseDown", button))

    def mouseUp(self, button):
        self.ops.append(("mouseUp", button))
```

檔尾追加：

```python
def test_pause_zero_is_set_on_injected_pdi():
    _, pdi, _, _, _ = make_game_backend()
    assert pdi.PAUSE == 0  # SpyPdi 初始為 0.1，建構子必須歸零


def test_game_mode_ascii_text_pressed_char_by_char():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.type_text("hi 42!")
    assert pdi.ops == [("press", ch) for ch in "hi 42!"]
    assert kb.ops == []  # 不走 pynput


def test_game_mode_non_ascii_text_falls_back_to_pynput():
    backend, pdi, kb, _, _ = make_game_backend()
    backend.type_text("哈囉 world")
    assert pdi.ops == []
    assert kb.ops == [("type", "哈囉 world")]


def test_game_mode_drag_uses_pdi_with_settles():
    backend, pdi, _, mouse, sleeps = make_game_backend()
    backend.mouse_drag(10, 20, 30, 40, MouseButton.LEFT)
    assert pdi.ops == [
        ("moveTo", 10, 20), ("mouseDown", "left"),
        ("moveTo", 30, 40), ("mouseUp", "left"),
    ]
    assert sleeps == [0.05, 0.05, 0.05]
    assert mouse.ops == []


def test_game_mode_click_settles_after_move():
    backend, pdi, _, _, sleeps = make_game_backend()
    backend.mouse_click(100, 200)
    assert pdi.ops == [("moveTo", 100, 200), ("click", "left")]
    assert sleeps == [0.05]
```

在 `tests/platforms/test_input_pynput.py` 把 `test_scroll_moves_then_scrolls` 整段替換為：

```python
def test_scroll_moves_then_scrolls():
    backend, _, mouse, sleeps = make_backend()
    backend.scroll(5, 6, 0, -3)
    assert mouse.ops == [("move", (5, 6)), ("scroll", 0, -3)]
    assert sleeps == [0.05]  # 移動後 settle 再捲動（M2b 統一政策）
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_win32_input.py tests/platforms/test_input_pynput.py -v`
Expected: 6 failed — 5 個新 win32 測試（PAUSE 仍為 0.1、text/drag 走 pynput、click 無 settle）+ 更新後的 scroll 測試（sleeps 為空）

- [ ] **Step 3: 實作**

(a) `src/keyboard_executor/platforms/win32/input.py` 整檔替換為：

```python
"""Windows 輸入實作。game_input_mode=True 時改走 pydirectinput（DirectInput scan code），
供攔截 SendInput 虛擬鍵碼的遊戲使用。不做任何反偵測——遊戲若阻擋輸入則如實失效。

game mode 覆蓋：key_press/key_combo/mouse_click/mouse_drag 全走 pdi；type_text 全為
ASCII 可列印字元時逐字 pdi.press，否則 fallback pynput（pdi 打不出非 ASCII 字元，
文件化限制：遊戲內輸入中文請用剪貼簿或改用非 game mode）。滑鼠動作各步間以
_SETTLE 等待，與共用層政策一致。
"""
from __future__ import annotations

from keyboard_executor.platforms.base import MouseButton
from keyboard_executor.platforms.common.input_pynput import _SETTLE, PynputInputBackend


def _is_ascii_printable(text: str) -> bool:
    return all(" " <= ch <= "~" for ch in text)


class Win32InputBackend(PynputInputBackend):
    def __init__(self, game_input_mode: bool = False, pdi=None, **kwargs):
        super().__init__(**kwargs)
        self._pdi = None
        if game_input_mode:
            if pdi is None:
                import pydirectinput as pdi
            pdi.PAUSE = 0  # 由我們自己的 delay 動作控制節奏（注入的 pdi 也一併設定）
            self._pdi = pdi

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        if self._pdi is None:
            return super().key_press(key, hold_ms)
        self._pdi.keyDown(key)
        if hold_ms > 0:
            self._sleep(hold_ms / 1000)
        self._pdi.keyUp(key)

    def key_combo(self, keys: list[str]) -> None:
        if self._pdi is None:
            return super().key_combo(keys)
        for k in keys:
            self._pdi.keyDown(k)
        for k in reversed(keys):
            self._pdi.keyUp(k)

    def type_text(self, text: str) -> None:
        if self._pdi is None or not _is_ascii_printable(text):
            return super().type_text(text)
        for ch in text:
            self._pdi.press(ch)

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        if self._pdi is None:
            return super().mouse_click(x, y, button, count)
        self._pdi.moveTo(x, y)
        self._sleep(_SETTLE)
        for _ in range(count):
            self._pdi.click(button=str(button))

    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None:
        if self._pdi is None:
            return super().mouse_drag(from_x, from_y, to_x, to_y, button)
        self._pdi.moveTo(from_x, from_y)
        self._sleep(_SETTLE)
        self._pdi.mouseDown(button=str(button))
        self._sleep(_SETTLE)
        self._pdi.moveTo(to_x, to_y)
        self._sleep(_SETTLE)
        self._pdi.mouseUp(button=str(button))
```

(b) `src/keyboard_executor/platforms/common/input_pynput.py` 的 `scroll` 方法替換為：

```python
    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._mouse.position = (x, y)
        self._sleep(_SETTLE)
        self._mouse.scroll(dx, dy)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_win32_input.py tests/platforms/test_input_pynput.py -v`
Expected: 17 passed（win32 10 + pynput 7）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **195 passed, 1 skipped**（190 + 5；scroll 測試是修改不是新增）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/win32/input.py src/keyboard_executor/platforms/common/input_pynput.py tests/platforms/test_win32_input.py tests/platforms/test_input_pynput.py
git commit -m "feat: Win32 game-mode 覆蓋 type_text/mouse_drag 並統一 settle 政策"
```

---

### Task 11: picker 抽出 + CLI record 子命令 + play 緊急停止守護

組裝層：把 demo 的互動式視窗選擇器抽成共用模組；新增 `record` 子命令（可測的 `run_record` 函式 + `main()` 組真實元件）；`play` 以 best-effort 掛上 SessionGuard（F10/角落 failsafe），失敗不阻斷回放（缺輸入監控權限時仍可 Ctrl+C）。

**範圍限制註記**：本任務的 live 錄製（真實全域監聽）需要 macOS「輸入監控」權限且會實際攔截鍵盤滑鼠，**不在自動測試內**——列入計畫末尾的人工總驗收清單。`run_record` 的自動測試以 ScriptedHook（同步注入事件的 fake hook）+ FakeRecorder 驗證組裝邏輯；SessionGuard 用真實實作（Task 9 已完整單測，此處驗證的是組裝）。play 守護的失敗分支以 try/except 包裹、不做單元測試（真實 PynputInputHook 無法在無頭環境啟動），由人工驗收涵蓋。

**Files:**
- Create: `src/keyboard_executor/picker.py`
- Modify: `src/keyboard_executor/demo.py`（choose_window 改為 re-export）
- Modify: `src/keyboard_executor/cli.py`（整檔替換）
- Test: `tests/test_picker.py`（新檔，1 個測試）
- Test: `tests/test_cli.py`（追加 2 個 parser 測試）
- Test: `tests/test_cli_record.py`（新檔，8 個測試）

**Interfaces:**
- Consumes: `SessionGuard`（Task 9）、`Recorder`（Task 7/8）、`PynputInputHook`（Task 6）、`ScriptStorage`/`Player`/`get_platform`/models（既有）
- Produces:
  - `picker.choose_window(windows: list[WindowInfo], ask=input, echo=print) -> WindowInfo | None` — 自 demo.py 原樣移入；`demo.choose_window` 為 re-export（`tests/test_demo.py` 既有 import 不變仍過）
  - `cli.run_record(platform, storage, hook, ask=input, echo=print, guard_factory=SessionGuard, recorder_factory=Recorder, title_pattern: str | None = None, full_trajectory: bool = False) -> int` — 0 成功存檔；1 放棄/空錄製/找不到視窗/存檔失敗
    - `guard_factory(hook, stop_event, on_toggle=...)` 契約：回傳物件需有 `handle(event)`/`is_control_event(event)`（`start`/`stop` 由 run_record 直接操作 hook，不經 guard）
    - `recorder_factory(origin: Point, mode: str)` 契約：回傳物件需有 `feed(event)`/`finish() -> list[Action]`
  - `record` 子命令：`record [--dir DIR] [--title REGEX] [--full-trajectory]`
  - play 守護：`_start_play_guard(player) -> SessionGuard | None` — 建構/啟動失敗印警告回傳 None；結束時 `guard.stop()` 包 try/except

- [ ] **Step 1: 寫失敗測試**

`tests/test_picker.py`：

```python
from keyboard_executor import demo, picker


def test_demo_reexports_picker_choose_window():
    assert demo.choose_window is picker.choose_window
```

在 `tests/test_cli.py` 檔尾追加：

```python
def test_record_parses_dir_title_and_full_trajectory():
    args = build_parser().parse_args(
        ["record", "--dir", "/tmp/s", "--title", "記事本.*", "--full-trajectory"])
    assert args.command == "record"
    assert args.dir == "/tmp/s"
    assert args.title == "記事本.*"
    assert args.full_trajectory is True


def test_record_defaults():
    args = build_parser().parse_args(["record"])
    assert args.dir is None
    assert args.title is None
    assert args.full_trajectory is False
```

`tests/test_cli_record.py`：

```python
import re

from keyboard_executor.cli import run_record
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import Action, ActionType
from keyboard_executor.platforms.base import EventKind, InputEvent, InputHook, WindowInfo
from keyboard_executor.platforms.factory import Platform
from keyboard_executor.storage.scripts import ScriptStorage
from tests.fakes import FakeInputBackend, FakeWindowManager


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


class ScriptedHook(InputHook):
    """start 時同步把預先安排好的事件全部送進 callback（模擬使用者操作）。"""

    def __init__(self, events):
        self._events = list(events)
        self.started = 0
        self.stopped = 0

    def start(self, on_event):
        self.started += 1
        for event in self._events:
            on_event(event)

    def stop(self):
        self.stopped += 1


class FakeRecorder:
    """記錄 feed 呼叫；finish 回傳注入的動作清單。"""

    def __init__(self, origin, mode="simplified"):
        self.origin = origin
        self.mode = mode
        self.fed = []
        self.finish_actions = [
            Action(type=ActionType.KEY_PRESS, params={"key": "a", "hold_ms": 0}),
        ]

    def feed(self, event):
        self.fed.append(event)

    def finish(self):
        return list(self.finish_actions)


def make_window(title="記事本", app="Notepad"):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=100, y=200, width=800, height=600, is_active=False)


def make_platform(windows=None):
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    return Platform(input_backend=FakeInputBackend(), window_manager=manager)


def run(events, tmp_path, answers=("我的腳本",), title_pattern="記事本",
        full_trajectory=False, platform=None, finish_actions=None):
    storage = ScriptStorage(tmp_path)
    hook = ScriptedHook(events)
    recorders = []

    def recorder_factory(origin, mode="simplified"):
        recorder = FakeRecorder(origin, mode)
        if finish_actions is not None:
            recorder.finish_actions = list(finish_actions)
        recorders.append(recorder)
        return recorder

    answer_iter = iter(answers)
    echoes = []
    code = run_record(platform if platform is not None else make_platform(),
                      storage, hook,
                      ask=lambda _prompt: next(answer_iter),
                      echo=echoes.append,
                      recorder_factory=recorder_factory,
                      title_pattern=title_pattern,
                      full_trajectory=full_trajectory)
    return code, storage, recorders, echoes, hook


HAPPY_EVENTS = [
    key_down("x", ts=0),     # F9 之前：不得進 recorder
    key_down("f9", ts=10),   # 開始錄製（控制鍵，不得進 recorder）
    key_up("f9", ts=20),
    key_down("a", ts=100),
    key_up("a", ts=150),
    key_down("f9", ts=500),  # 停止錄製
]


def test_record_happy_path_saves_script(tmp_path):
    code, storage, recorders, echoes, hook = run(HAPPY_EVENTS, tmp_path)
    assert code == 0
    assert hook.started == 1 and hook.stopped == 1
    [recorder] = recorders
    assert recorder.origin == Point(100, 200)
    assert recorder.mode == "simplified"
    assert [(e.kind, e.key) for e in recorder.fed] == [
        (EventKind.KEY_DOWN, "a"), (EventKind.KEY_UP, "a"),
    ]
    loaded = storage.load("我的腳本")
    assert loaded.target_window.title_pattern == re.escape("記事本")
    assert [a.type for a in loaded.actions] == [ActionType.KEY_PRESS]
    assert any("已儲存" in line for line in echoes)


def test_record_f10_abandons_without_saving(tmp_path):
    events = [key_down("f9", ts=0), key_down("a", ts=10), key_down("f10", ts=20)]
    code, storage, _, echoes, _ = run(events, tmp_path)
    assert code == 1
    assert any("已放棄" in line for line in echoes)
    assert storage.list_names() == []


def test_record_empty_recording_returns_error(tmp_path):
    events = [key_down("f9", ts=0), key_down("f9", ts=100)]
    code, storage, _, echoes, _ = run(events, tmp_path, finish_actions=[])
    assert code == 1
    assert any("沒有錄到" in line for line in echoes)
    assert storage.list_names() == []


def test_record_full_trajectory_uses_full_mode(tmp_path):
    code, _, recorders, _, _ = run(HAPPY_EVENTS, tmp_path, full_trajectory=True)
    assert code == 0
    assert recorders[0].mode == "full"


def test_record_title_pattern_not_found_returns_error(tmp_path):
    code, _, _, echoes, _ = run(HAPPY_EVENTS, tmp_path, title_pattern="無此視窗")
    assert code == 1
    assert any("找不到符合" in line for line in echoes)


def test_record_picker_flow_selects_window(tmp_path):
    # 不給 title_pattern → 走互動選單：先答視窗編號，再答腳本名稱
    code, storage, _, _, _ = run(HAPPY_EVENTS, tmp_path,
                                 answers=("1", "選單腳本"), title_pattern=None)
    assert code == 0
    assert storage.list_names() == ["選單腳本"]


def test_record_picker_cancel_returns_error(tmp_path):
    code, storage, _, _, hook = run(HAPPY_EVENTS, tmp_path,
                                    answers=("q",), title_pattern=None)
    assert code == 1
    assert storage.list_names() == []
    assert hook.started == 0  # 取消選視窗就不開監聽


def test_record_invalid_script_name_returns_error(tmp_path):
    code, storage, _, echoes, _ = run(HAPPY_EVENTS, tmp_path, answers=("a/b",))
    assert code == 1
    assert any("儲存失敗" in line for line in echoes)
    assert storage.list_names() == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_picker.py tests/test_cli.py tests/test_cli_record.py -v`
Expected: FAIL — `test_picker.py` 整檔 collection error（`ModuleNotFoundError: No module named 'keyboard_executor.picker'`）；`test_cli_record.py` 整檔 collection error（`ImportError: cannot import name 'run_record'`）；兩個 record parser 測試以 `SystemExit: 2`（未知子命令）失敗

- [ ] **Step 3: 實作**

(a) 建立 `src/keyboard_executor/picker.py`（choose_window 自 demo.py 原樣移入）：

```python
"""互動式視窗選擇器（demo 與 CLI record 共用）。"""
from __future__ import annotations

from keyboard_executor.platforms.base import WindowInfo


def choose_window(windows: list[WindowInfo], ask=input, echo=print) -> WindowInfo | None:
    """列出視窗讓使用者輸入編號選擇；q 取消回傳 None。無標題的視窗不列入。"""
    candidates = [w for w in windows if w.title.strip()]
    if not candidates:
        echo("目前沒有可選擇的視窗")
        return None
    for i, w in enumerate(candidates, start=1):
        echo(f"{i:3d}. {w.title}（{w.app_name}）")
    while True:
        answer = ask("輸入視窗編號（q 取消）: ").strip()
        if answer.lower() == "q":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        echo(f"請輸入 1–{len(candidates)} 的數字")
```

(b) `src/keyboard_executor/demo.py` 整檔替換為（僅移除 choose_window 本體與 WindowInfo import、改為 re-export，其餘不變）：

```python
"""M1 驗收 demo：把目標視窗切到前景，執行一段寫死的動作序列。

不給 --title 時會列出目前所有視窗，輸入編號選擇目標：
    python -m keyboard_executor.demo
也可用標題 regex 直接指定：
    python -m keyboard_executor.demo --title "未命名|Untitled"   # macOS 文字編輯
    python -m keyboard_executor.demo --title "記事本|Notepad"    # Windows 記事本
"""
from __future__ import annotations

import argparse
import sys
import time

from keyboard_executor.core.geometry import Point, to_absolute
from keyboard_executor.picker import choose_window  # re-export：既有測試/呼叫端沿用此路徑
from keyboard_executor.platforms.factory import get_platform

__all__ = ["build_parser", "choose_window", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M1 demo：對指定視窗執行寫死的動作序列")
    parser.add_argument("--title", default=None, help="目標視窗標題（regex）；省略時改用互動式選單")
    parser.add_argument(
        "--game-input", action="store_true",
        help="Windows 遊戲輸入模式（pydirectinput scan code）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if sys.platform == "darwin":
        from keyboard_executor.platforms.darwin.permissions import (
            ACCESSIBILITY_GUIDE,
            check_accessibility,
        )

        if not check_accessibility():
            print(ACCESSIBILITY_GUIDE, file=sys.stderr)
            return 1

    platform = get_platform(game_input_mode=args.game_input)

    if args.title:
        windows = platform.window_manager.find_windows(title_pattern=args.title)
        if not windows:
            print(f"找不到符合 {args.title!r} 的視窗", file=sys.stderr)
            return 1
        win = windows[0]
    else:
        win = choose_window(platform.window_manager.list_all())
        if win is None:
            return 1
    print(f"目標視窗：{win.title}（{win.app_name}）@ ({win.x}, {win.y}) {win.width}x{win.height}")

    if not platform.window_manager.activate(win):
        print("無法將視窗切到前景", file=sys.stderr)
        return 1
    time.sleep(0.3)  # 前景切換後留給系統穩定的時間

    origin = Point(win.x, win.y)
    center = to_absolute(origin, Point(win.width // 2, win.height // 2))
    backend = platform.input_backend
    backend.mouse_click(center.x, center.y)
    backend.type_text("hello from keyboard-executor")
    backend.key_press("enter")
    backend.type_text("M1 acceptance ok")
    print("動作序列執行完畢")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(c) `src/keyboard_executor/cli.py` 整檔替換為：

```python
"""CLI 進入點。

    python -m keyboard_executor.cli list                 # 列出腳本
    python -m keyboard_executor.cli play <腳本名稱>      # 回放（F10/左上角/Ctrl+C 可中斷）
    python -m keyboard_executor.cli record               # 錄製（F9 開始/停止，F10 放棄）

腳本目錄預設 ~/.keyboard-executor/scripts，可用 --dir 覆寫。
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
from pathlib import Path

from keyboard_executor.core.geometry import Point
from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.core.models import (
    Script,
    ScriptSettings,
    ScriptValidationError,
    TargetWindow,
)
from keyboard_executor.core.player import Player
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.picker import choose_window
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook
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

    record = sub.add_parser("record", help="錄製腳本（F9 開始/停止，F10 放棄）")
    record.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")
    record.add_argument("--title", default=None,
                        help="目標視窗標題（regex）；省略時改用互動式選單")
    record.add_argument("--full-trajectory", action="store_true",
                        help="完整軌跡模式：保留滑鼠移動路徑（預設只留點擊/拖曳/捲動）")
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


def run_record(platform, storage, hook, ask=input, echo=print,
               guard_factory=SessionGuard, recorder_factory=Recorder,
               title_pattern: str | None = None, full_trajectory: bool = False) -> int:
    """錄製流程（元件全注入，供單元測試）。回傳 exit code：0 成功存檔、1 失敗/放棄。"""
    wm = platform.window_manager
    if title_pattern:
        windows = wm.find_windows(title_pattern=title_pattern)
        if not windows:
            echo(f"找不到符合 {title_pattern!r} 的視窗")
            return 1
        win = windows[0]
    else:
        win = choose_window(wm.list_all(), ask=ask, echo=echo)
        if win is None:
            return 1
    echo(f"目標視窗：{win.title}（{win.app_name}）")

    recorder = recorder_factory(Point(win.x, win.y),
                                mode="full" if full_trajectory else "simplified")
    stop_event = threading.Event()
    done = threading.Event()
    recording = False

    def on_toggle() -> None:
        nonlocal recording
        if done.is_set():
            return
        if recording:
            done.set()
        else:
            recording = True
            echo("錄製中……再按 F9 停止")

    guard = guard_factory(hook, stop_event, on_toggle=on_toggle)

    def dispatch(event) -> None:
        guard.handle(event)  # 控制語義優先（F9 切換、F10/角落停止）
        if recording and not done.is_set() and not guard.is_control_event(event):
            recorder.feed(event)  # 自我過濾：控制鍵與 toggle 前的事件不進腳本

    try:
        hook.start(dispatch)
    except Exception as e:
        echo(f"無法啟動輸入監聽（可能缺輸入監控權限）：{e}")
        return 1
    echo("按 F9 開始錄製，再按 F9 停止，F10 放棄")
    try:
        while not done.is_set() and not stop_event.is_set():
            stop_event.wait(0.05)
    finally:
        hook.stop()

    if stop_event.is_set():
        echo("已放棄錄製")
        return 1
    actions = recorder.finish()
    if not actions:
        echo("沒有錄到任何動作")
        return 1

    title = re.escape(win.title) if win.title.strip() else None
    app = win.app_name if win.app_name.strip() else None
    if title is None and app is None:
        echo("目標視窗沒有標題與應用程式名稱，無法建立腳本")
        return 1
    target = TargetWindow(title_pattern=title, app_name=None if title else app)
    name = ask("腳本名稱: ").strip()
    script = Script(name=name, target_window=target,
                    actions=tuple(actions), settings=ScriptSettings())
    try:
        path = storage.save(script)
    except ScriptValidationError as e:
        echo(f"儲存失敗：{e}")
        return 1
    echo(f"已儲存：{path}（共 {len(actions)} 個動作）")
    return 0


def _start_play_guard(player: Player) -> SessionGuard | None:
    """best-effort 啟動 F10/左上角緊急停止；失敗（如缺輸入監控權限）不阻斷回放。"""
    try:
        guard = SessionGuard(PynputInputHook(), player.stop_event)
        guard.start()
        return guard
    except Exception:
        print("緊急停止熱鍵無法啟用（可能缺輸入監控權限），仍可用 Ctrl+C", file=sys.stderr)
        return None


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

    if args.command == "record":
        if not _check_darwin_permissions():
            return 1
        platform = get_platform()
        return run_record(platform, storage, PynputInputHook(),
                          title_pattern=args.title,
                          full_trajectory=args.full_trajectory)

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
    guard = _start_play_guard(player)
    print(f"開始回放：{script.name}（F10 或滑鼠甩到螢幕左上角可緊急停止；Ctrl+C 亦可）")
    try:
        result = player.play(script)
    except KeyboardInterrupt:
        print("\n已中斷（Ctrl+C）", file=sys.stderr)
        return 1
    finally:
        if guard is not None:
            try:
                guard.stop()
            except Exception:
                pass  # 守護收尾失敗不影響回放結果
    if result.ok:
        print(f"回放完成，共執行 {result.actions_run} 個動作")
        return 0
    print(f"回放中止：{result.error}（已執行 {result.actions_run} 個動作）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_picker.py tests/test_cli.py tests/test_cli_record.py tests/test_demo.py -v`
Expected: 25 passed（picker 1 + cli 7 + cli_record 8 + demo 9；demo 既有測試靠 re-export 不變仍過）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **206 passed, 1 skipped**（195 + 11）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/picker.py src/keyboard_executor/demo.py src/keyboard_executor/cli.py tests/test_picker.py tests/test_cli.py tests/test_cli_record.py
git commit -m "feat: CLI record 子命令與 play 緊急停止守護（M2b 驗收入口）"
```

---

## 完成定義（M2b）

- [ ] `python -m pytest -q` 全綠：**206 passed, 1 skipped**（含錄製演算法單元覆蓋：test_recorder_keys 10 + test_recorder_mouse 9）
- [ ] 所有面向使用者的訊息為繁體中文；key typo 於載入時即報錯（Task 1）
- [ ] 人工總驗收（macOS，由人執行——會實際攔截/送出鍵盤滑鼠）：
  1. **權限**：系統設定授予終端機「輔助使用」與「輸入監控」（監聽需要後者；缺輸入監控時 pynput 可能靜默收不到事件——錄不到東西先查權限再判 bug）
  2. **錄製**：開「文字編輯」→ `python -m keyboard_executor.cli record --title "未命名|Untitled"` → F9 → 打幾個字 + Ctrl+S 以外的組合鍵 + 點擊 + 捲動 → F9 → 命名存檔。檢查 JSON：key_press/key_combo/mouse_click/scroll/delay 合理、座標為視窗相對、F9 本身沒被錄進去
  3. **放棄**：重錄一次，中途按 F10 → 顯示「已放棄錄製」、無檔案
  4. **完整軌跡**：`record --full-trajectory` 錄一段滑鼠移動 → JSON 含取樣後的 mouse_move
  5. **回放**：`play <剛錄的腳本>` → 動作重現於目標視窗
  6. **F10 緊急停止**：手編腳本加 `{"type": "delay", "ms": 30000}` 後 play，於 delay 中按 F10 → 立即停止（驗 Task 2 可中斷 sleep）
  7. **角落 failsafe**：回放中把滑鼠甩到螢幕左上角 → 立即停止
  8. **權限缺失降級**：撤銷輸入監控權限後 play → 印「緊急停止熱鍵無法啟用……仍可用 Ctrl+C」且回放照常
  9. **Windows backlog（M5 前必補）**：game-mode ASCII type_text/drag/PAUSE=0 實機驗證、錄製 smoke、125%/150% DPI

## 後續計畫（不在本計畫範圍）

- **M3**：截圖（mss）+ OCR + 模板比對 + 規則引擎。已知前置（見 m2a-final-review「M3 計畫預告」與 m1-final-review 架構風險）：
  - macOS Retina 座標換算設計（ScreenCapture scale factor）必須先解——mss 是實體像素、輸入層是 Cocoa 點
  - `wait_*` 的 `on_timeout: goto` 需要 `_run_actions` 改索引機、`_run_one` 回傳控制訊號
  - `action_to_dict` 的動作清單特例鍵擴充（`then`/`else`），考慮 per-type serializer
  - `ScriptStorage.load` 可檢查 `stem == data["name"]`（檔名與內部 name 背離）
  - `find_windows` 先過 title 再查 appname（watcher 輪詢效能）
- **M4**：GUI（PySide6）——錄製面板沿用 Recorder/SessionGuard/PynputInputHook 組合；Qt6 DPI awareness 呼叫順序確認
- **M5**：打包（PyInstaller）+ macOS 權限引導（含「自動化」與「螢幕錄製」）
