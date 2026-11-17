# M3 視覺辨識與規則引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 M3：以 mss 定時截圖、平台原生 OCR 與 OpenCV 模板比對驅動兩條管線——(1) 腳本內流程控制動作 `wait_text` / `wait_image` / `if_text` / `if_image` / `click_text` / `click_image`（含 `on_timeout: goto` 索引跳轉、Retina 座標換算後點擊命中中心）；(2) 獨立監看規則引擎 `RuleEngine`，各規則以自身間隔輪詢畫面、命中且不在冷卻期時觸發 `run_script` / `stop_all` / `notify`。同時吸收 M2b 最終審查的收尾待辦（`cli.main()` 分派單元測試、`storage.save` 的 OSError 對稱處理）。

**Architecture:** 風險（無法在無頭 CI 測的原生 OCR、mss 實機截圖）全部收斂為 `platforms/` 層的薄適配器（`MssScreenCapture`、`WindowsOcrEngine`、`VisionOcrEngine`），躲在 `ScreenCapture` / `OcrEngine` ABC 之後；所有可測邏輯（模板比對、文字搜尋、輪詢/逾時/goto 索引機、規則評估與冷卻、座標換算）留在 `core/`（`vision.py`、`player.py`、`rule_engine.py`）純函式/類，以 `FakeScreenCapture` / `FakeOcrEngine` / 固定生成圖 / 注入時鐘測到底。`Platform` dataclass 以 `None` 預設新增 `screen_capture`、`ocr_engine` 兩欄位，既有建構點不受影響。

**Tech Stack:** Python 3.11+（StrEnum）、mss（截圖）、opencv-python-headless + numpy（模板比對）、winsdk（Windows.Media.Ocr，Windows）、pyobjc-framework-Vision（Apple Vision，macOS）、pynput / pywinctl（沿用）、pytest。

**對應 spec:** `docs/superpowers/specs/2026-07-06-keyboard-executor-design.md` §5.2（新增六種視覺/流程動作欄位）、§5.3（Rule 模型）、§8（擷取與辨識管線、模板比對細節、OCR 引擎）、§10（錯誤處理：`on_timeout` abort/continue/goto、OCR/截圖失敗跳過、視窗消失安全中止）、§13-M3。吸收 `docs/superpowers/notes/2026-07-06-m2b-final-review.md`「M3 計畫必須吸收的待辦」1/2 與「M3 結構性預告」全部；解決 `docs/superpowers/notes/2026-07-06-m1-final-review.md`「M3 規劃前必須解決」的 Retina 座標單位風險。

## Global Constraints

- Python `>=3.11`；src layout：程式碼一律在 `src/keyboard_executor/` 下（spec §4）
- 判斷作業系統（`sys.platform`）只允許出現在 `platforms/` 層；CLI 的 darwin 權限檢查沿用已核准的 `_check_darwin_permissions` 例外模式
- 所有面向使用者的訊息（錯誤、CLI 輸出、docstring 內操作說明）一律繁體中文（台灣用語）
- 外部依賴（mss `sct`、OCR 原生 recognizer/converter、listener 類、clock、sleep、rng、stop_event、notifier、player_factory、engine_factory、storage、ask/echo）一律建構子/參數注入，預設為真實實作（spec §12）
- 腳本座標一律為「目標視窗左上角為原點」的相對座標（平台輸入座標單位＝點；見 `core/geometry.py`）；`region` 亦以視窗相對座標（點）表示，`null` 代表整個視窗
- Commit 訊息用 conventional commits；直接在 main 工作，不開分支（用戶既定選擇）
- TDD：RED 一律用計畫指定的 pytest 指令執行，報告需貼 `rtk proxy python -m pytest ...` 的**原始 transcript**（本機 RTK proxy 會壓縮 pytest 輸出，需用 `rtk proxy` 取原始格式）；全套件回歸在 repo 根目錄跑 `python -m pytest -q`
- YAGNI：只實作本計畫列出的行為，不加「順手」的參數或抽象；多尺度搜尋（spec §8.2 進階選項）本版不做
- 全套件基準（計畫撰寫時已實測於 macOS）：**213 passed, 1 skipped**（`test_win32_input` 的 1 個 win32-gated skip）。各任務結束的精確累計總數列在該任務回歸步驟

### 跨任務型別契約（先鎖定，後續任務一致消費）

| 名稱 | 位置 | 簽名／形狀 | 引入任務 |
|------|------|-----------|---------|
| `Platform.screen_capture` | `platforms/factory.py` | `ScreenCapture \| None = None` | Task 2 |
| `Platform.ocr_engine` | `platforms/factory.py` | `OcrEngine \| None = None` | Task 5 |
| `ScreenCapture.scale_factor` | `platforms/base.py` | `(self) -> float`（螢幕實體像素 / 輸入點） | Task 2 |
| `FakeScreenCapture` | `tests/fakes.py` | `(image=None, scale=1.0)`；`capture(region)` 記錄 region 回傳 image；`scale_factor()` 回傳 scale | Task 2 |
| `FakeOcrEngine` | `tests/fakes.py` | `(boxes=None)`；`recognize(image) -> list[TextBox]` 回傳注入清單（可佇列多輪） | Task 4 |
| `TemplateMatch` | `core/vision.py` | frozen `(found: bool, x: int, y: int, confidence: float)`；x,y=命中中心（搜尋影像座標） | Task 3 |
| `match_template` | `core/vision.py` | `(image, template, threshold=0.85, grayscale=True) -> TemplateMatch` | Task 3 |
| `find_text` | `core/vision.py` | `(boxes: list[TextBox], pattern: str, mode="contains") -> TextBox \| None` | Task 4 |
| `_Goto` | `core/player.py` | frozen `(index: int)`；`_run_one` 的控制訊號回傳型別 | Task 7a |
| `Player(..., templates=None)` | `core/player.py` | `templates: Callable[[str], np.ndarray] \| None`（模板名→影像） | Task 7a |
| `Rule` / `rule_from_dict` / `rule_to_dict` | `core/models.py` | 見 Task 8 | Task 8 |
| `RuleStorage` / `TemplateStore` | `storage/rules.py` / `storage/templates.py` | 見 Task 8 | Task 8 |
| `RuleEngine` | `core/rule_engine.py` | 見 Task 9 | Task 9 |

### 座標換算鏈（Retina，Task 7 實作、以 scale=2 驗算）

視覺動作命中後要換算回輸入點，方向如下（`points` = pywinctl/pynput 的輸入點；`px` = mss 實體像素）：

```
region（視窗相對，點）: (rx, ry, rw, rh)   # null → (0, 0, win.width, win.height)
win 原點（螢幕絕對，點）: (win.x, win.y)     # 每次動作前 refresh 重新查詢
scale = screen_capture.scale_factor()       # Windows=1.0；Retina=2.0

擷取用實體像素 Rect（傳給 capture）:
  cap = Rect(round((win.x + rx) * scale), round((win.y + ry) * scale),
             round(rw * scale), round(rh * scale))
capture(cap) → 影像（px），左上角對應 region 左上角

命中中心（px，region 相對，0 起算）: (cx, cy)
  - 模板: TemplateMatch.x/.y
  - 文字: box.x + box.width // 2, box.y + box.height // 2

換回視窗相對點: (rx + round(cx / scale), ry + round(cy / scale))
換回螢幕絕對點: to_absolute(Point(win.x, win.y), Point(...))  → backend.mouse_click
```

---

### Task 1: 依賴宣告 + M2b 收尾批次（cli.main 分派測試、storage.save OSError 對稱）

新增 M3 三方依賴宣告與安裝，並吸收 M2b 最終審查兩項待辦：`cli.main()` 的 list/play/record 分派目前無單元測試（只有 parser 有測）；`ScriptStorage.save` 未對稱處理 `OSError`（`load` 有攔）。把 `main()` 重構為注入外部元件工廠的可測形式（預設真實），並補 `save` 的 OSError 包裝。

**Files:**
- Modify: `pyproject.toml`（新增依賴、版本 0.1.0→0.3.0）
- Modify: `src/keyboard_executor/cli.py`（`main()` 加注入 seam；不改行為）
- Modify: `src/keyboard_executor/storage/scripts.py`（`save` 包 OSError）
- Test: `tests/test_cli_main.py`（新檔，8 個）
- Test: `tests/storage/test_scripts.py`（追加 1 個）

**Interfaces:**
- Consumes: 既有 `main`、`run_record`、`_check_darwin_permissions`、`_start_play_guard`、`Player`、`get_platform`、`ScriptStorage`
- Produces:
  - `main(argv=None, *, get_platform=get_platform, player_factory=Player, check_permissions=_check_darwin_permissions, run_record_fn=run_record, guard_starter=_start_play_guard, hook_factory=PynputInputHook) -> int` — 各 seam 預設真實實作，測試注入假件驗證「parser→分派」接線（不啟真實 listener/平台）
  - `ScriptStorage.save` 行為：`OSError`（含權限/磁碟）→ `ScriptValidationError`（繁中），與 `load` 對稱

- [ ] **Step 0: 安裝 M3 依賴（一次性）**

M3 的 numpy / opencv-python-headless / mss 尚未安裝於環境。先寫 pyproject（Step 1）再安裝：

Run: `python -m pip install "mss>=9.0" "opencv-python-headless>=4.8" "numpy>=1.24"`
（`winsdk`、`pyobjc-framework-Vision` 為平台限定，於各自平台安裝；macOS CI 只需前三者即可跑本計畫所有單元測試。）

- [ ] **Step 1: 寫失敗測試**

`tests/test_cli_main.py`（新檔）：

```python
import pytest

from keyboard_executor.cli import main
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import PlayResult
from keyboard_executor.storage.scripts import ScriptStorage


class FakePlayer:
    def __init__(self, result):
        self._result = result
        self.played = []
        import threading
        self.stop_event = threading.Event()

    def play(self, script):
        self.played.append(script.name)
        return self._result


def save_script(tmp_path, name="簽到"):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}],
    }))
    return storage


def test_list_empty_prints_placeholder(tmp_path, capsys):
    code = main(["list", "--dir", str(tmp_path)])
    assert code == 0
    assert "（沒有腳本）" in capsys.readouterr().out


def test_list_nonempty_prints_names(tmp_path, capsys):
    save_script(tmp_path, "甲")
    save_script(tmp_path, "乙")
    code = main(["list", "--dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "甲" in out and "乙" in out


def test_play_load_error_exits_1(tmp_path, capsys):
    code = main(["play", "不存在", "--dir", str(tmp_path)],
                check_permissions=lambda: True)
    assert code == 1
    assert "腳本載入失敗" in capsys.readouterr().err


def test_play_happy_dispatch_returns_0(tmp_path, capsys):
    save_script(tmp_path, "甲")
    player = FakePlayer(PlayResult(ok=True, actions_run=1))
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                player_factory=lambda *a, **k: player,
                guard_starter=lambda p: None)
    assert code == 0
    assert player.played == ["甲"]
    assert "回放完成" in capsys.readouterr().out


def test_play_result_failure_exits_1(tmp_path, capsys):
    save_script(tmp_path, "甲")
    player = FakePlayer(PlayResult(ok=False, actions_run=2, error="視窗已關閉"))
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                player_factory=lambda *a, **k: player,
                guard_starter=lambda p: None)
    assert code == 1
    assert "回放中止" in capsys.readouterr().err


def test_play_permission_denied_blocks(tmp_path):
    save_script(tmp_path, "甲")
    called = []
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                player_factory=lambda *a, **k: called.append(1) or FakePlayer(None))
    assert code == 1
    assert called == []  # 權限擋下，不建 Player


def test_record_dispatches_to_run_record(tmp_path):
    seen = {}

    def spy_run_record(platform, storage, hook, *, title_pattern, full_trajectory):
        seen["title"] = title_pattern
        seen["full"] = full_trajectory
        return 0

    code = main(["record", "--dir", str(tmp_path), "--title", "記事本.*",
                 "--full-trajectory"],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                hook_factory=lambda: object(),
                run_record_fn=spy_run_record)
    assert code == 0
    assert seen == {"title": "記事本.*", "full": True}


def test_record_permission_denied_blocks(tmp_path):
    called = []
    code = main(["record", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                run_record_fn=lambda *a, **k: called.append(1) or 0)
    assert code == 1
    assert called == []
```

在 `tests/storage/test_scripts.py` 檔尾追加：

```python
def test_save_oserror_wrapped_as_validation_error(tmp_path, monkeypatch):
    storage = ScriptStorage(tmp_path)

    def boom(*a, **k):
        raise OSError("磁碟已滿")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(ScriptValidationError, match="無法儲存"):
        storage.save(make_script("甲"))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_cli_main.py tests/storage/test_scripts.py -v`
Expected: FAIL — `test_cli_main.py` 的注入 seam（`check_permissions=`、`get_platform=` 等關鍵字）現行 `main()` 不接受 → `TypeError: main() got an unexpected keyword argument`；`test_save_oserror_wrapped_as_validation_error` 因 `save` 未攔 `OSError` 而拋 `OSError` 而非 `ScriptValidationError`。

- [ ] **Step 3: 實作**

(a) `pyproject.toml`——`version` 改 `0.3.0`，`dependencies` 整段替換為：

```toml
version = "0.3.0"
description = "跨平台鍵盤滑鼠自動化工具（模擬/錄製/回放 + OCR 畫面判斷）"
requires-python = ">=3.11"
dependencies = [
    "pynput>=1.7.6",
    "pywinctl>=0.3",
    "mss>=9.0",
    "opencv-python-headless>=4.8",
    "numpy>=1.24",
    "pydirectinput>=1.0.4; sys_platform == 'win32'",
    "winsdk>=1.0.0b10; sys_platform == 'win32'",
    "pyobjc-framework-ApplicationServices>=10.0; sys_platform == 'darwin'",
    "pyobjc-framework-Vision>=10.0; sys_platform == 'darwin'",
]
```

(b) `src/keyboard_executor/storage/scripts.py` 的 `save` 整個方法替換為：

```python
    def save(self, script: Script) -> Path:
        path = self.path_for(script.name)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(script_to_dict(script), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            raise ScriptValidationError(f"腳本 {script.name!r} 無法儲存: {e}") from e
        return path
```

(c) `src/keyboard_executor/cli.py` 的 `main` 整個函式替換為（僅加 seam，分派邏輯不變）：

```python
def main(argv: list[str] | None = None, *,
         get_platform=get_platform, player_factory=Player,
         check_permissions=_check_darwin_permissions,
         run_record_fn=run_record, guard_starter=_start_play_guard,
         hook_factory=PynputInputHook) -> int:
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
        if not check_permissions():
            return 1
        platform = get_platform()
        return run_record_fn(platform, storage, hook_factory(),
                             title_pattern=args.title,
                             full_trajectory=args.full_trajectory)

    # play
    if not check_permissions():
        return 1
    try:
        script = storage.load(args.name)
    except ScriptValidationError as e:
        print(f"腳本載入失敗：{e}", file=sys.stderr)
        return 1

    platform = get_platform(game_input_mode=script.settings.game_input_mode)
    player = player_factory(platform, storage=storage)
    guard = guard_starter(player)
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_cli_main.py tests/storage/test_scripts.py tests/test_cli.py -v`
Expected: 24 passed（cli_main 8 + scripts 9 + cli 7）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **222 passed, 1 skipped**（213 + 9）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/keyboard_executor/cli.py src/keyboard_executor/storage/scripts.py tests/test_cli_main.py tests/storage/test_scripts.py
git commit -m "chore: M3 依賴宣告與 cli.main 分派測試、storage.save OSError 對稱"
```

---

### Task 2: ScreenCapture（mss）實作 + Retina scale factor

`ScreenCapture` ABC 補 `scale_factor()`（M1 審查的 Retina 風險：mss 是實體像素、輸入層是點）。`MssScreenCapture` 以 mss 擷取「螢幕絕對實體像素」區域回傳 BGR `np.ndarray`，並用「mss grab 的實體像素寬 ÷ 邏輯 monitor 寬」推得 scale。`Platform` 以 `None` 預設新增 `screen_capture` 欄位（既有建構點不破）。`FakeScreenCapture` 進 `tests/fakes.py` 供後續任務消費。

**Files:**
- Modify: `src/keyboard_executor/platforms/base.py`（`ScreenCapture` 加 `scale_factor` 抽象方法）
- Create: `src/keyboard_executor/platforms/common/capture_mss.py`
- Modify: `src/keyboard_executor/platforms/factory.py`（`Platform` 加 `screen_capture=None`；兩平台 wiring）
- Modify: `tests/fakes.py`（新增 `FakeScreenCapture`）
- Test: `tests/platforms/test_capture_mss.py`（新檔，4 個）
- Test: `tests/platforms/test_base.py`（追加 1 個：FakeScreenCapture）
- Test: `tests/platforms/test_factory.py`（追加 1 個：darwin 有 screen_capture）

**Platform dataclass 遷移（採 None 預設，不改任何既有建構點）:**
既有 `Platform(...)` 建構點（grep 確認）——`factory.py`×2、`tests/core/test_player_alive.py`、`test_player_basic.py`×4、`test_player_flow.py`×4、`test_player_stop.py`、`tests/test_cli_record.py`——全部只傳 `input_backend=`、`window_manager=` 兩個關鍵字。因為新欄位 `screen_capture: ScreenCapture | None = None` 有預設值，**這些建構點一律不需修改**。工廠內兩處 `Platform(...)` 由本任務補上 `screen_capture=`。

**Interfaces:**
- Consumes: `Rect`（geometry）、`ScreenCapture`（base）
- Produces（Task 7/9 依賴）:
  - `ScreenCapture.scale_factor(self) -> float`（抽象）
  - `MssScreenCapture(sct=None)`：`capture(region: Rect) -> np.ndarray`（BGR，region 為螢幕絕對實體像素）；`scale_factor() -> float`（快取，首次以 grab 主 monitor 的實體寬 ÷ 邏輯寬）；`sct=None` 時 lazy import `mss.mss()`
  - `Platform.screen_capture: ScreenCapture | None = None`
  - `FakeScreenCapture(image=None, scale=1.0)`：`capture(region)` 把 region 記入 `self.captures` 並回傳 `image`（`None` 時回傳 1×1×3 零圖）；`scale_factor()` 回傳注入 scale

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_capture_mss.py`（新檔）：

```python
import numpy as np

from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.common.capture_mss import MssScreenCapture


class StubSct:
    """模擬 mss.mss()：monitors[1] 為主螢幕邏輯尺寸；grab 回傳固定 BGRA 陣列。"""

    def __init__(self, logical_w=100, logical_h=80, phys_scale=1):
        self.monitors = [
            {"left": 0, "top": 0, "width": logical_w, "height": logical_h},   # [0] 全部
            {"left": 0, "top": 0, "width": logical_w, "height": logical_h},   # [1] 主
        ]
        self._scale = phys_scale
        self.grabs = []

    def grab(self, region):
        self.grabs.append(region)
        w = region["width"] if isinstance(region, dict) else region.width
        h = region["height"] if isinstance(region, dict) else region.height
        # 模擬 mss：Retina 時 grab 回傳 scale 倍的實體像素影像
        s = self._scale
        arr = np.zeros((h * s if h else self.monitors[1]["height"] * s,
                        w * s if w else self.monitors[1]["width"] * s, 4), dtype=np.uint8)
        arr[..., 0] = 10  # B
        arr[..., 1] = 20  # G
        arr[..., 2] = 30  # R
        arr[..., 3] = 255
        return arr


def test_capture_returns_bgr_ndarray_dropping_alpha():
    cap = MssScreenCapture(sct=StubSct())
    img = cap.capture(Rect(0, 0, 4, 3))
    assert isinstance(img, np.ndarray)
    assert img.shape == (3, 4, 3)  # 去掉 alpha 通道
    assert tuple(img[0, 0]) == (10, 20, 30)  # BGR 順序保留


def test_capture_passes_absolute_region_to_grab():
    sct = StubSct()
    MssScreenCapture(sct=sct).capture(Rect(200, 100, 40, 30))
    assert sct.grabs == [{"left": 200, "top": 100, "width": 40, "height": 30}]


def test_scale_factor_retina_is_two():
    cap = MssScreenCapture(sct=StubSct(logical_w=100, logical_h=80, phys_scale=2))
    assert cap.scale_factor() == 2.0


def test_scale_factor_non_retina_is_one_and_cached():
    sct = StubSct(logical_w=100, logical_h=80, phys_scale=1)
    cap = MssScreenCapture(sct=sct)
    assert cap.scale_factor() == 1.0
    cap.scale_factor()
    assert len(sct.grabs) == 1  # 快取：只 grab 一次
```

在 `tests/platforms/test_base.py` 檔尾追加：

```python
def test_fake_screen_capture_records_region_and_returns_image():
    import numpy as np
    from keyboard_executor.core.geometry import Rect
    from tests.fakes import FakeScreenCapture

    img = np.zeros((6, 8, 3), dtype=np.uint8)
    cap = FakeScreenCapture(image=img, scale=2.0)
    out = cap.capture(Rect(10, 20, 8, 6))
    assert out is img
    assert cap.captures == [Rect(10, 20, 8, 6)]
    assert cap.scale_factor() == 2.0
```

在 `tests/platforms/test_factory.py` 檔尾追加：

```python
@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_wires_screen_capture():
    from keyboard_executor.platforms.common.capture_mss import MssScreenCapture

    platform = get_platform()
    assert isinstance(platform.screen_capture, MssScreenCapture)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_capture_mss.py tests/platforms/test_base.py tests/platforms/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.common.capture_mss'`（capture_mss 整檔）；`test_fake_screen_capture...`（`FakeScreenCapture` 不存在）；`test_darwin_wires_screen_capture`（`Platform` 無 `screen_capture` 屬性）。

- [ ] **Step 3: 實作**

(a) `src/keyboard_executor/platforms/base.py` 的 `ScreenCapture` 整個類別替換為：

```python
class ScreenCapture(ABC):
    @abstractmethod
    def capture(self, region: Rect) -> Any:
        """擷取螢幕區域（螢幕絕對實體像素座標），回傳 numpy BGR 影像。"""
        ...

    @abstractmethod
    def scale_factor(self) -> float:
        """螢幕實體像素 / 輸入座標點的比值：Windows 為 1.0；Retina 為 2.0。
        呼叫端據此把「點」單位的視窗/區域幾何換算為 mss 擷取用的實體像素。"""
        ...
```

(b) 建立 `src/keyboard_executor/platforms/common/capture_mss.py`：

```python
"""mss 螢幕擷取：把螢幕絕對實體像素區域擷成 BGR numpy 影像。

Retina（M1 審查風險）：mss 的 monitor 幾何為邏輯點，但 grab 回傳實體像素影像；
scale_factor 以「grab 主螢幕的實體寬 ÷ 邏輯寬」推得（Windows=1.0、Retina=2.0），
供呼叫端把「點」單位的視窗/區域幾何換算為 mss 擷取用的實體像素座標。
sct 注入供測試；None 時 lazy import mss（macOS 需「螢幕錄製」權限）。
"""
from __future__ import annotations

import numpy as np

from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.base import ScreenCapture


class MssScreenCapture(ScreenCapture):
    def __init__(self, sct=None):
        if sct is None:
            import mss
            sct = mss.mss()
        self._sct = sct
        self._scale: float | None = None

    def capture(self, region: Rect) -> np.ndarray:
        shot = self._sct.grab({"left": region.x, "top": region.y,
                               "width": region.width, "height": region.height})
        arr = np.asarray(shot)              # (h, w, 4) BGRA
        return np.ascontiguousarray(arr[:, :, :3])  # 去 alpha，保留 BGR

    def scale_factor(self) -> float:
        if self._scale is None:
            mon = self._sct.monitors[1]     # [1] = 主螢幕
            shot = np.asarray(self._sct.grab(mon))
            logical_w = mon["width"]
            self._scale = float(shot.shape[1]) / logical_w if logical_w else 1.0
        return self._scale
```

(c) `src/keyboard_executor/platforms/factory.py`——import 行改為：

```python
from keyboard_executor.platforms.base import InputBackend, ScreenCapture, WindowManager
```

`Platform` dataclass 替換為：

```python
@dataclass(frozen=True)
class Platform:
    input_backend: InputBackend
    window_manager: WindowManager
    screen_capture: ScreenCapture | None = None
```

win32 分支的 `return Platform(...)` 替換為：

```python
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture

        ensure_dpi_awareness()
        return Platform(
            input_backend=Win32InputBackend(game_input_mode=game_input_mode),
            window_manager=PywinctlWindowManager(),
            screen_capture=MssScreenCapture(),
        )
```

darwin 分支的 `return Platform(...)` 替換為：

```python
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture

        return Platform(
            input_backend=PynputInputBackend(),
            window_manager=PywinctlWindowManager(),
            screen_capture=MssScreenCapture(),
        )
```

（`from ...window_pywinctl import PywinctlWindowManager` 等既有 import 保留原位。）

(d) `tests/fakes.py`——import 區塊補 `ScreenCapture`、`Rect`，並在檔尾新增 `FakeScreenCapture`：

import 行改為：

```python
from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.base import (
    InputBackend,
    InputEvent,
    InputHook,
    MouseButton,
    ScreenCapture,
    WindowInfo,
    WindowManager,
)
```

（`import numpy as np` 加在檔頭。）檔尾追加：

```python
class FakeScreenCapture(ScreenCapture):
    """測試用截圖：capture 記錄請求的 region、回傳注入影像；scale_factor 回傳注入值。"""

    def __init__(self, image=None, scale: float = 1.0) -> None:
        self.image = image if image is not None else np.zeros((1, 1, 3), dtype=np.uint8)
        self._scale = scale
        self.captures: list[Rect] = []

    def capture(self, region: Rect):
        self.captures.append(region)
        return self.image

    def scale_factor(self) -> float:
        return self._scale
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_capture_mss.py tests/platforms/test_base.py tests/platforms/test_factory.py -v`
Expected: 15 passed（capture_mss 4 + base 10 + factory 1 新增，darwin gated 另 1；實測依平台）；於 macOS 為 15 passed。

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **228 passed, 1 skipped**（222 + 6）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/base.py src/keyboard_executor/platforms/common/capture_mss.py src/keyboard_executor/platforms/factory.py tests/fakes.py tests/platforms/test_capture_mss.py tests/platforms/test_base.py tests/platforms/test_factory.py
git commit -m "feat: MssScreenCapture 與 ScreenCapture.scale_factor（Retina 換算）"
```

---

### Task 3: vision.py 模板比對（OpenCV，純演算法，完整單元測試）

`core/vision.py` 首個內容：`TemplateMatch` 結果模型與 `match_template`（`cv2.matchTemplate` + `TM_CCOEFF_NORMED`，回傳命中中心座標）。模板比對對截圖矩陣運算無平台差異（spec §8.2），完全可單元測試——以 numpy 生成大圖植入已知圖塊驗證。

**Files:**
- Create: `src/keyboard_executor/core/vision.py`
- Test: `tests/core/test_vision_template.py`（新檔，5 個）

**Interfaces:**
- Consumes: `cv2`、`numpy`
- Produces（Task 7/9 依賴）:
  - `TemplateMatch(found: bool, x: int, y: int, confidence: float)`（frozen dataclass；`x,y` = 命中區域中心，搜尋影像座標系，實體像素）
  - `match_template(image: np.ndarray, template: np.ndarray, threshold: float = 0.85, grayscale: bool = True) -> TemplateMatch` — `confidence >= threshold` 時 `found=True`；預設先轉灰階再比對

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_vision_template.py`（新檔）：

```python
import numpy as np

from keyboard_executor.core.vision import TemplateMatch, match_template


def make_scene(patch, at):
    """640x480x3 灰底大圖，把 patch 貼到 (x, y)=at 位置。"""
    scene = np.full((480, 640, 3), 128, dtype=np.uint8)
    x, y = at
    h, w = patch.shape[:2]
    scene[y:y + h, x:x + w] = patch
    return scene


def make_patch():
    patch = np.zeros((40, 60, 3), dtype=np.uint8)
    patch[:, :, 2] = 255  # 紅色圖塊（BGR）
    patch[10:30, 20:40] = (0, 255, 0)  # 內含綠色方塊，具辨識特徵
    return patch


def test_found_returns_center_within_tolerance():
    patch = make_patch()
    scene = make_scene(patch, at=(300, 200))
    m = match_template(scene, patch, threshold=0.85)
    assert m.found is True
    # 中心 = (300 + 60/2, 200 + 40/2) = (330, 220)
    assert abs(m.x - 330) <= 1 and abs(m.y - 220) <= 1
    assert m.confidence >= 0.85


def test_not_found_below_threshold():
    scene = np.full((480, 640, 3), 128, dtype=np.uint8)
    other = np.zeros((40, 60, 3), dtype=np.uint8)
    other[:, :, 0] = 255  # 場景裡沒有的藍塊
    m = match_template(scene, other, threshold=0.95)
    assert m.found is False
    assert m.confidence < 0.95


def test_grayscale_default_still_matches_color_patch():
    patch = make_patch()
    scene = make_scene(patch, at=(100, 50))
    m = match_template(scene, patch)  # grayscale=True 預設
    assert m.found is True
    assert abs(m.x - 130) <= 1 and abs(m.y - 70) <= 1


def test_color_mode_matches_too():
    patch = make_patch()
    scene = make_scene(patch, at=(10, 10))
    m = match_template(scene, patch, grayscale=False)
    assert m.found is True
    assert abs(m.x - 40) <= 1 and abs(m.y - 30) <= 1


def test_confidence_high_for_exact_patch():
    patch = make_patch()
    scene = make_scene(patch, at=(0, 0))
    m = match_template(scene, patch)
    assert m.confidence > 0.99
    assert isinstance(m, TemplateMatch)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_vision_template.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.vision'`（整檔 collection error）

- [ ] **Step 3: 實作 vision.py**

`src/keyboard_executor/core/vision.py`：

```python
"""跨平台視覺演算法（純 numpy/OpenCV，無平台差異，可完整單元測試）。

- 模板比對：cv2.matchTemplate + TM_CCOEFF_NORMED，回傳命中中心座標與信心值
- 文字搜尋（Task 4）：對 OCR 產出的 TextBox 清單做 contains/regex 比對
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class TemplateMatch:
    found: bool
    x: int          # 命中區域中心（搜尋影像座標系，實體像素）
    y: int
    confidence: float


def match_template(image: np.ndarray, template: np.ndarray,
                   threshold: float = 0.85, grayscale: bool = True) -> TemplateMatch:
    """在 image 中找 template。grayscale 預設 True（對亮度變化較穩健，spec §8.2）。
    回傳命中中心座標；confidence >= threshold 時 found=True。"""
    img = image
    tpl = template
    if grayscale:
        img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(result)
    th, tw = template.shape[:2]
    center_x = int(max_loc[0] + tw / 2)
    center_y = int(max_loc[1] + th / 2)
    return TemplateMatch(found=bool(max_v >= threshold),
                         x=center_x, y=center_y, confidence=float(max_v))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_vision_template.py -v`
Expected: 5 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **233 passed, 1 skipped**（228 + 5）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/vision.py tests/core/test_vision_template.py
git commit -m "feat: vision.match_template（OpenCV 模板比對，回傳命中中心）"
```

---

### Task 4: OCR 文字搜尋 find_text（純邏輯）+ FakeOcrEngine

`vision.py` 追加 `find_text`：對 OCR 引擎產出的 `TextBox` 清單做 contains（子字串）/ regex（`re.search`）比對，回傳第一個命中或 `None`。`TextBox` 已在 `base.py`。真實 OCR 引擎（Task 5）不進 CI，所有規則/動作邏輯一律對 `FakeOcrEngine` 回傳的罐頭 `TextBox` 清單測試——本任務把 `FakeOcrEngine` 加進 `tests/fakes.py`。

**Files:**
- Modify: `src/keyboard_executor/core/vision.py`（追加 `find_text`）
- Modify: `tests/fakes.py`（新增 `FakeOcrEngine`）
- Test: `tests/core/test_vision_text.py`（新檔，5 個）

**Interfaces:**
- Consumes: `TextBox`（base）、`re`
- Produces（Task 7/9 依賴）:
  - `find_text(boxes: list[TextBox], pattern: str, mode: str = "contains") -> TextBox | None` — `mode="contains"` 用 `pattern in box.text`；`mode="regex"` 用 `re.search(pattern, box.text)`；回傳第一個命中，皆不中回傳 `None`
  - `FakeOcrEngine(boxes=None)`：`recognize(image) -> list[TextBox]`；`boxes` 為單一清單（每次都回同一份）或清單的佇列（`list[list[TextBox]]`，逐輪 pop 供輪詢測試）；記錄呼叫進 `self.calls`

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_vision_text.py`（新檔）：

```python
import numpy as np

from keyboard_executor.core.vision import find_text
from keyboard_executor.platforms.base import TextBox
from tests.fakes import FakeOcrEngine


def box(text, x=0, y=0, w=10, h=10, conf=0.9):
    return TextBox(text=text, x=x, y=y, width=w, height=h, confidence=conf)


def test_find_text_contains_substring():
    boxes = [box("開始遊戲"), box("連線中斷，請重試")]
    hit = find_text(boxes, "連線中斷", mode="contains")
    assert hit is not None and hit.text == "連線中斷，請重試"


def test_find_text_contains_no_match_returns_none():
    boxes = [box("開始遊戲"), box("設定")]
    assert find_text(boxes, "連線中斷") is None


def test_find_text_regex_mode():
    boxes = [box("HP 100/100"), box("等級 42")]
    hit = find_text(boxes, r"等級 \d+", mode="regex")
    assert hit is not None and hit.text == "等級 42"


def test_find_text_returns_first_match():
    boxes = [box("重試 A"), box("重試 B")]
    hit = find_text(boxes, "重試")
    assert hit.text == "重試 A"


def test_fake_ocr_engine_recognize_returns_queued_boxes():
    eng = FakeOcrEngine(boxes=[[box("第一輪")], [box("第二輪")]])
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    assert [b.text for b in eng.recognize(img)] == ["第一輪"]
    assert [b.text for b in eng.recognize(img)] == ["第二輪"]
    assert len(eng.calls) == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_vision_text.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_text'`（`find_text` 未實作）；`FakeOcrEngine` 不存在。

- [ ] **Step 3: 實作**

(a) `src/keyboard_executor/core/vision.py`——檔頭 `from dataclasses import dataclass` 之後加 `import re`；並在檔尾追加：

```python
def find_text(boxes: "list", pattern: str, mode: str = "contains"):
    """在 OCR TextBox 清單中找符合 pattern 的第一個框；皆不中回傳 None。
    mode="contains"：子字串；mode="regex"：re.search。"""
    for b in boxes:
        if mode == "regex":
            if re.search(pattern, b.text):
                return b
        elif pattern in b.text:
            return b
    return None
```

（型別註記用字串避免對 `TextBox` 產生循環 import；`vision.py` 不需 import `base`。）

(b) `tests/fakes.py`——import 區塊補 `TextBox`，檔尾新增 `FakeOcrEngine`：

import 行內補入 `TextBox`（與 `OcrEngine`）：

```python
from keyboard_executor.platforms.base import (
    InputBackend,
    InputEvent,
    InputHook,
    MouseButton,
    OcrEngine,
    ScreenCapture,
    TextBox,
    WindowInfo,
    WindowManager,
)
```

檔尾追加：

```python
class FakeOcrEngine(OcrEngine):
    """測試用 OCR：recognize 回傳注入的 TextBox 清單。

    boxes 為單一 list[TextBox]（每輪都回同一份），或 list[list[TextBox]]
    佇列（逐輪 pop(0) 供輪詢測試；耗盡後持續回傳最後一份）。
    """

    def __init__(self, boxes=None) -> None:
        self._boxes = boxes if boxes is not None else []
        self._queued = bool(boxes) and isinstance(boxes[0], list)
        self.calls: list = []

    def recognize(self, image) -> list[TextBox]:
        self.calls.append(image)
        if not self._queued:
            return list(self._boxes)
        if len(self._boxes) > 1:
            return self._boxes.pop(0)
        return list(self._boxes[0]) if self._boxes else []
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_vision_text.py -v`
Expected: 5 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **238 passed, 1 skipped**（233 + 5）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/vision.py tests/fakes.py tests/core/test_vision_text.py
git commit -m "feat: vision.find_text 與 FakeOcrEngine（OCR 文字搜尋純邏輯）"
```

---

### Task 5: 平台 OCR 引擎骨架（薄適配器，不在 CI 測真實引擎）

`OcrEngine` 的兩個平台實作：`WindowsOcrEngine`（Windows.Media.Ocr / winsdk）、`VisionOcrEngine`（Apple Vision / pyobjc）。原生引擎無法在無頭 CI 跑，故把「影像→原生點陣圖」與「原生辨識器」都做成注入 seam：單元測試只驗（1）建構不觸發原生 import（lazy）、（2）`recognize` 把原生結果正確映射成 `TextBox`（以注入假件驅動）。真實辨識列人工驗收。`Platform` 以 `None` 預設新增 `ocr_engine`，工廠依平台 wiring。

**Files:**
- Create: `src/keyboard_executor/platforms/win32/ocr.py`
- Create: `src/keyboard_executor/platforms/darwin/ocr.py`
- Modify: `src/keyboard_executor/platforms/factory.py`（`Platform` 加 `ocr_engine=None`；兩平台 wiring）
- Test: `tests/platforms/test_ocr.py`（新檔，4 個）
- Test: `tests/platforms/test_factory.py`（追加 1 個：darwin 有 ocr_engine）

**Platform dataclass 遷移（第二個新欄位，同採 None 預設）:**
`ocr_engine: OcrEngine | None = None` 加在 `screen_capture` 之後。既有建構點（Task 2 已列舉，全部只傳 `input_backend=`/`window_manager=`，Task 2 又補了工廠兩處的 `screen_capture=`）仍不需改。工廠兩處補 `ocr_engine=`。**無其他建構點受影響。**

**Interfaces:**
- Consumes: `OcrEngine`/`TextBox`（base）
- Produces（Task 9 依賴）:
  - `WindowsOcrEngine(recognizer=None, to_bitmap=None)`：`recognize(image) -> list[TextBox]`；`recognizer`/`to_bitmap` 為 `None` 時於首次 `recognize` lazy import winsdk（`_default_recognizer` / `_default_to_bitmap`）；把原生「行/字 + bbox」映射為 `TextBox`
  - `VisionOcrEngine(recognizer=None, to_image=None)`：同上，lazy import pyobjc Vision
  - `Platform.ocr_engine: OcrEngine | None = None`

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_ocr.py`（新檔）：

```python
import numpy as np

from keyboard_executor.platforms.base import OcrEngine, TextBox
from keyboard_executor.platforms.darwin.ocr import VisionOcrEngine
from keyboard_executor.platforms.win32.ocr import WindowsOcrEngine


def image():
    return np.zeros((20, 40, 3), dtype=np.uint8)


class NativeLine:
    """模擬原生辨識器回傳的一行結果：文字 + (x, y, w, h) 框 + 信心。"""

    def __init__(self, text, bbox, conf):
        self.text = text
        self.bbox = bbox
        self.conf = conf


def test_windows_construction_does_not_import_native():
    # 不注入、也不呼叫 recognize —— 建構不得觸發 winsdk import
    eng = WindowsOcrEngine()
    assert isinstance(eng, OcrEngine)


def test_windows_recognize_maps_native_to_textboxes():
    lines = [NativeLine("連線中斷", (10, 20, 80, 16), 0.95)]
    eng = WindowsOcrEngine(recognizer=lambda bmp: lines,
                           to_bitmap=lambda img: ("bitmap", img.shape))
    boxes = eng.recognize(image())
    assert boxes == [TextBox(text="連線中斷", x=10, y=20, width=80, height=16,
                             confidence=0.95)]


def test_darwin_construction_does_not_import_native():
    eng = VisionOcrEngine()
    assert isinstance(eng, OcrEngine)


def test_darwin_recognize_maps_native_to_textboxes():
    lines = [NativeLine("重試", (5, 6, 30, 12), 0.88)]
    eng = VisionOcrEngine(recognizer=lambda cg: lines,
                          to_image=lambda img: ("cgimage", img.shape))
    boxes = eng.recognize(image())
    assert boxes == [TextBox(text="重試", x=5, y=6, width=30, height=12,
                             confidence=0.88)]
```

在 `tests/platforms/test_factory.py` 檔尾追加：

```python
@pytest.mark.skipif(sys.platform != "darwin", reason="僅在 macOS 驗證")
def test_darwin_wires_ocr_engine():
    from keyboard_executor.platforms.darwin.ocr import VisionOcrEngine

    platform = get_platform()
    assert isinstance(platform.ocr_engine, VisionOcrEngine)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/platforms/test_ocr.py tests/platforms/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.platforms.win32.ocr'`（test_ocr 整檔）；`test_darwin_wires_ocr_engine`（`Platform` 無 `ocr_engine`）。

- [ ] **Step 3: 實作**

(a) 建立 `src/keyboard_executor/platforms/win32/ocr.py`：

```python
"""Windows.Media.Ocr（winsdk）OCR 適配器。

薄適配器：影像→SoftwareBitmap 轉換與原生辨識器都做成注入 seam，
CI 只測「建構不觸發 winsdk import」與「原生結果→TextBox 映射」；
真實辨識列人工驗收。recognizer/to_bitmap 為 None 時於首次 recognize
lazy import winsdk（風險收斂在 _default_* 兩個 helper）。
"""
from __future__ import annotations

from keyboard_executor.platforms.base import OcrEngine, TextBox


class WindowsOcrEngine(OcrEngine):
    def __init__(self, recognizer=None, to_bitmap=None):
        self._recognizer = recognizer
        self._to_bitmap = to_bitmap

    def recognize(self, image) -> list[TextBox]:
        to_bitmap = self._to_bitmap or _default_to_bitmap
        recognizer = self._recognizer or _default_recognizer
        bitmap = to_bitmap(image)
        lines = recognizer(bitmap)
        return [TextBox(text=line.text, x=line.bbox[0], y=line.bbox[1],
                        width=line.bbox[2], height=line.bbox[3],
                        confidence=line.conf) for line in lines]


def _default_to_bitmap(image):  # pragma: no cover - 需原生環境，列人工驗收
    """numpy BGR → winsdk SoftwareBitmap（BGRA8）。"""
    import numpy as np
    from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    h, w = image.shape[:2]
    bgra = np.dstack([image, np.full((h, w), 255, dtype=image.dtype)])
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(bgra.tobytes())
    return SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)


def _default_recognizer(bitmap):  # pragma: no cover - 需原生環境，列人工驗收
    """SoftwareBitmap → 原生行結果（text/bbox/conf）。"""
    import asyncio

    from winsdk.windows.media.ocr import OcrEngine as WinOcrEngine

    class _Line:
        def __init__(self, text, bbox, conf):
            self.text, self.bbox, self.conf = text, bbox, conf

    engine = WinOcrEngine.try_create_from_user_profile_languages()
    result = asyncio.run(engine.recognize_async(bitmap))
    lines = []
    for line in result.lines:
        rects = [w.bounding_rect for w in line.words]
        left = int(min(r.x for r in rects))
        top = int(min(r.y for r in rects))
        right = int(max(r.x + r.width for r in rects))
        bottom = int(max(r.y + r.height for r in rects))
        lines.append(_Line(line.text, (left, top, right - left, bottom - top), 1.0))
    return lines
```

(b) 建立 `src/keyboard_executor/platforms/darwin/ocr.py`：

```python
"""Apple Vision（pyobjc）OCR 適配器。

薄適配器：影像→CGImage 轉換與原生辨識器都做成注入 seam，
CI 只測「建構不觸發 pyobjc import」與「原生結果→TextBox 映射」；
真實辨識列人工驗收。recognizer/to_image 為 None 時於首次 recognize
lazy import Vision（風險收斂在 _default_* 兩個 helper）。
"""
from __future__ import annotations

from keyboard_executor.platforms.base import OcrEngine, TextBox


class VisionOcrEngine(OcrEngine):
    def __init__(self, recognizer=None, to_image=None):
        self._recognizer = recognizer
        self._to_image = to_image

    def recognize(self, image) -> list[TextBox]:
        to_image = self._to_image or _default_to_image
        recognizer = self._recognizer or _default_recognizer
        cg = to_image(image)
        lines = recognizer(cg)
        return [TextBox(text=line.text, x=line.bbox[0], y=line.bbox[1],
                        width=line.bbox[2], height=line.bbox[3],
                        confidence=line.conf) for line in lines]


def _default_to_image(image):  # pragma: no cover - 需原生環境，列人工驗收
    """numpy BGR → CGImage。"""
    import cv2
    import Quartz

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    provider = Quartz.CGDataProviderCreateWithData(None, rgb.tobytes(), rgb.nbytes, None)
    colorspace = Quartz.CGColorSpaceCreateDeviceRGB()
    return Quartz.CGImageCreate(w, h, 8, 24, w * 3, colorspace,
                                Quartz.kCGImageAlphaNone, provider, None, False,
                                Quartz.kCGRenderingIntentDefault)


def _default_recognizer(cg_image):  # pragma: no cover - 需原生環境，列人工驗收
    """CGImage → 原生行結果（text/bbox/conf）。Vision 座標為 0–1 正規化、原點左下，
    映射回像素時翻 y。"""
    import Quartz
    import Vision

    class _Line:
        def __init__(self, text, bbox, conf):
            self.text, self.bbox, self.conf = text, bbox, conf

    w = Quartz.CGImageGetWidth(cg_image)
    h = Quartz.CGImageGetHeight(cg_image)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    handler.performRequests_error_([request], None)
    lines = []
    for obs in request.results() or []:
        top = obs.topCandidates_(1)[0]
        bb = obs.boundingBox()
        px = int(bb.origin.x * w)
        pw = int(bb.size.width * w)
        ph = int(bb.size.height * h)
        py = int((1 - bb.origin.y - bb.size.height) * h)  # 翻 y：Vision 原點左下
        lines.append(_Line(top.string(), (px, py, pw, ph), float(top.confidence())))
    return lines
```

(c) `src/keyboard_executor/platforms/factory.py`——import 行改為：

```python
from keyboard_executor.platforms.base import (
    InputBackend,
    OcrEngine,
    ScreenCapture,
    WindowManager,
)
```

`Platform` dataclass 替換為：

```python
@dataclass(frozen=True)
class Platform:
    input_backend: InputBackend
    window_manager: WindowManager
    screen_capture: ScreenCapture | None = None
    ocr_engine: OcrEngine | None = None
```

win32 分支的 `return Platform(...)` 替換為（補 `ocr_engine`）：

```python
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
        from keyboard_executor.platforms.win32.ocr import WindowsOcrEngine

        ensure_dpi_awareness()
        return Platform(
            input_backend=Win32InputBackend(game_input_mode=game_input_mode),
            window_manager=PywinctlWindowManager(),
            screen_capture=MssScreenCapture(),
            ocr_engine=WindowsOcrEngine(),
        )
```

darwin 分支的 `return Platform(...)` 替換為：

```python
        from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
        from keyboard_executor.platforms.darwin.ocr import VisionOcrEngine

        return Platform(
            input_backend=PynputInputBackend(),
            window_manager=PywinctlWindowManager(),
            screen_capture=MssScreenCapture(),
            ocr_engine=VisionOcrEngine(),
        )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/platforms/test_ocr.py tests/platforms/test_factory.py -v`
Expected: 6 passed（ocr 4 + factory darwin 2；於 macOS）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **243 passed, 1 skipped**（238 + 5）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/platforms/win32/ocr.py src/keyboard_executor/platforms/darwin/ocr.py src/keyboard_executor/platforms/factory.py tests/platforms/test_ocr.py tests/platforms/test_factory.py
git commit -m "feat: WindowsOcrEngine/VisionOcrEngine 薄適配器與工廠 wiring"
```

---

### Task 6: 新視覺/流程動作類型驗證（models.py 擴充）

新增六種 ActionType 與嚴格驗證器（spec §5.2）：`wait_text` / `wait_image` / `if_text` / `if_image` / `click_text` / `click_image`。`action_to_dict` 泛化巢狀動作清單處理，一次涵蓋 `actions`（loop）與 `then` / `else`（if_*），避免特例散落。純驗證邏輯，完整單元測試。

**Files:**
- Modify: `src/keyboard_executor/core/models.py`
- Test: `tests/core/test_models_vision_actions.py`（新檔，20 個）

**Interfaces:**
- Consumes: 既有 `_check_no_extra`/`_get_int`/`_get_str`/`action_from_dict`
- Produces（Task 7 依賴）——各動作正規化後 params 形狀：
  - `wait_text`：`{region, pattern, mode, timeout_ms, on_timeout, goto_index}`（`region`=`None` 或 `[x,y,w,h]`；`mode`∈`contains/regex` 預設 `contains`；`timeout_ms`≥0 預設 5000；`on_timeout`∈`abort/continue/goto` 預設 `abort`；`goto_index`≥0 僅 `on_timeout=goto` 時必填、否則不得出現）
  - `wait_image`：`{region, template, threshold, timeout_ms, on_timeout, goto_index}`（`template`=非空字串模板名；`threshold` 0–1 預設 0.85）
  - `if_text`：`{region, pattern, mode, then, else}`（`then`=非空 Action 清單；`else`=Action 清單，預設 `[]`）
  - `if_image`：`{region, template, threshold, then, else}`
  - `click_text`：`{region, pattern, mode}`
  - `click_image`：`{region, template, threshold}`
  - `action_to_dict` 對 `actions`/`then`/`else` 三鍵遞迴序列化

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_models_vision_actions.py`（新檔）：

```python
import pytest

from keyboard_executor.core.models import (
    ActionType,
    ScriptValidationError,
    action_from_dict,
    action_to_dict,
)


def test_wait_text_minimal_defaults():
    a = action_from_dict({"type": "wait_text", "pattern": "完成"})
    assert a.type is ActionType.WAIT_TEXT
    assert a.params == {"region": None, "pattern": "完成", "mode": "contains",
                        "timeout_ms": 5000, "on_timeout": "abort", "goto_index": None}


def test_wait_text_region_four_ints():
    a = action_from_dict({"type": "wait_text", "pattern": "x",
                          "region": [10, 20, 100, 40]})
    assert a.params["region"] == [10, 20, 100, 40]


def test_wait_text_region_bad_length_rejected():
    with pytest.raises(ScriptValidationError, match="region"):
        action_from_dict({"type": "wait_text", "pattern": "x", "region": [1, 2, 3]})


def test_wait_text_mode_must_be_contains_or_regex():
    with pytest.raises(ScriptValidationError, match="mode"):
        action_from_dict({"type": "wait_text", "pattern": "x", "mode": "glob"})


def test_wait_text_on_timeout_goto_requires_index():
    with pytest.raises(ScriptValidationError, match="goto_index"):
        action_from_dict({"type": "wait_text", "pattern": "x", "on_timeout": "goto"})
    a = action_from_dict({"type": "wait_text", "pattern": "x",
                          "on_timeout": "goto", "goto_index": 3})
    assert a.params["on_timeout"] == "goto" and a.params["goto_index"] == 3


def test_wait_text_goto_index_forbidden_without_goto():
    with pytest.raises(ScriptValidationError, match="goto_index"):
        action_from_dict({"type": "wait_text", "pattern": "x",
                          "on_timeout": "continue", "goto_index": 1})


def test_wait_text_on_timeout_bad_value():
    with pytest.raises(ScriptValidationError, match="on_timeout"):
        action_from_dict({"type": "wait_text", "pattern": "x", "on_timeout": "die"})


def test_wait_text_missing_pattern():
    with pytest.raises(ScriptValidationError, match="pattern"):
        action_from_dict({"type": "wait_text"})


def test_wait_image_minimal_defaults():
    a = action_from_dict({"type": "wait_image", "template": "按鈕"})
    assert a.type is ActionType.WAIT_IMAGE
    assert a.params == {"region": None, "template": "按鈕", "threshold": 0.85,
                        "timeout_ms": 5000, "on_timeout": "abort", "goto_index": None}


def test_wait_image_threshold_out_of_range():
    with pytest.raises(ScriptValidationError, match="threshold"):
        action_from_dict({"type": "wait_image", "template": "x", "threshold": 1.5})


def test_wait_image_missing_template():
    with pytest.raises(ScriptValidationError, match="template"):
        action_from_dict({"type": "wait_image"})


def test_if_text_then_else_recursively_validated():
    a = action_from_dict({
        "type": "if_text", "pattern": "勝利",
        "then": [{"type": "key_press", "key": "a"}],
        "else": [{"type": "key_press", "key": "b"}],
    })
    assert a.type is ActionType.IF_TEXT
    assert [x.type for x in a.params["then"]] == [ActionType.KEY_PRESS]
    assert [x.type for x in a.params["else"]] == [ActionType.KEY_PRESS]


def test_if_text_then_required_else_optional():
    a = action_from_dict({"type": "if_text", "pattern": "x",
                          "then": [{"type": "key_press", "key": "a"}]})
    assert a.params["else"] == []
    with pytest.raises(ScriptValidationError, match="then"):
        action_from_dict({"type": "if_text", "pattern": "x", "then": []})


def test_if_text_nested_invalid_action_rejected():
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        action_from_dict({"type": "if_text", "pattern": "x",
                          "then": [{"type": "key_press", "key": "entr"}]})


def test_if_image_valid():
    a = action_from_dict({"type": "if_image", "template": "圖",
                          "then": [{"type": "delay", "ms": 100}]})
    assert a.params["template"] == "圖" and a.params["threshold"] == 0.85


def test_click_text_minimal():
    a = action_from_dict({"type": "click_text", "pattern": "登入"})
    assert a.type is ActionType.CLICK_TEXT
    assert a.params == {"region": None, "pattern": "登入", "mode": "contains"}


def test_click_image_minimal():
    a = action_from_dict({"type": "click_image", "template": "確定鈕"})
    assert a.type is ActionType.CLICK_IMAGE
    assert a.params == {"region": None, "template": "確定鈕", "threshold": 0.85}


def test_click_text_rejects_timeout_fields():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        action_from_dict({"type": "click_text", "pattern": "x", "timeout_ms": 100})


def test_action_to_dict_roundtrips_wait_text():
    src = {"type": "wait_text", "pattern": "完成", "region": [0, 0, 10, 10],
           "mode": "regex", "timeout_ms": 3000, "on_timeout": "goto", "goto_index": 2}
    assert action_to_dict(action_from_dict(src)) == {
        "type": "wait_text", "region": [0, 0, 10, 10], "pattern": "完成",
        "mode": "regex", "timeout_ms": 3000, "on_timeout": "goto", "goto_index": 2}


def test_action_to_dict_roundtrips_if_text_then_else():
    src = {"type": "if_text", "pattern": "x",
           "then": [{"type": "key_press", "key": "a", "hold_ms": 0}],
           "else": [{"type": "loop", "count": 2,
                     "actions": [{"type": "key_press", "key": "b", "hold_ms": 0}]}]}
    out = action_to_dict(action_from_dict(src))
    assert out["then"] == [{"type": "key_press", "key": "a", "hold_ms": 0}]
    assert out["else"][0]["type"] == "loop"
    assert out["else"][0]["actions"] == [{"type": "key_press", "key": "b", "hold_ms": 0}]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_models_vision_actions.py -v`
Expected: FAIL — 大量 `未知動作類型: 'wait_text'` 等（`ActionType` 尚無這些成員，`action_from_dict` 於 `ActionType(raw_type)` 拋 `ValueError` → 轉 `未知動作類型`）。

- [ ] **Step 3: 實作 models.py**

(a) `ActionType` StrEnum 在 `RUN_SCRIPT = "run_script"` 之後追加：

```python
    WAIT_TEXT = "wait_text"
    WAIT_IMAGE = "wait_image"
    IF_TEXT = "if_text"
    IF_IMAGE = "if_image"
    CLICK_TEXT = "click_text"
    CLICK_IMAGE = "click_image"
```

(b) 在 `_validate_run_script` 之後、`_VALIDATORS` 之前插入共用 helper 與六個驗證器：

```python
_MODES = {"contains", "regex"}
_ON_TIMEOUT = {"abort", "continue", "goto"}


def _get_region(params: dict, atype: str):
    """region：None（整個視窗）或 [x, y, w, h] 四整數（視窗相對，w/h > 0）。"""
    region = params.get("region")
    if region is None:
        return None
    ok = (isinstance(region, (list, tuple)) and len(region) == 4
          and all(isinstance(v, int) and not isinstance(v, bool) for v in region)
          and region[2] > 0 and region[3] > 0)
    if not ok:
        _err(f"動作 {atype} 欄位 region 必須是 null 或 [x, y, w, h] 四整數（w、h > 0）")
    return [region[0], region[1], region[2], region[3]]


def _get_mode(params: dict, atype: str) -> str:
    mode = params.get("mode", "contains")
    if mode not in _MODES:
        _err(f"動作 {atype} 欄位 mode 必須是 contains 或 regex")
    return mode


def _get_threshold(params: dict, atype: str) -> float:
    threshold = params.get("threshold", 0.85)
    if (not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
            or not 0 < threshold <= 1):
        _err(f"動作 {atype} 欄位 threshold 必須是 (0, 1] 的數字")
    return float(threshold)


def _get_wait_common(p: dict, atype: str) -> dict:
    """wait_* 共用：timeout_ms、on_timeout、goto_index。"""
    timeout_ms = _get_int(p, atype, "timeout_ms", minimum=0, default=5000, required=False)
    on_timeout = p.get("on_timeout", "abort")
    if on_timeout not in _ON_TIMEOUT:
        _err(f"動作 {atype} 欄位 on_timeout 必須是 abort、continue 或 goto")
    if on_timeout == "goto":
        if "goto_index" not in p:
            _err(f"動作 {atype} on_timeout=goto 時必須提供 goto_index")
        goto_index = _get_int(p, atype, "goto_index", minimum=0)
    else:
        if "goto_index" in p:
            _err(f"動作 {atype} 欄位 goto_index 只在 on_timeout=goto 時允許")
        goto_index = None
    return {"timeout_ms": timeout_ms, "on_timeout": on_timeout, "goto_index": goto_index}


def _get_then_else(p: dict, atype: str) -> dict:
    then = p.get("then")
    if not isinstance(then, list) or not then:
        _err(f"動作 {atype} 欄位 then 必須是至少一個動作的清單")
    els = p.get("else", [])
    if not isinstance(els, list):
        _err(f"動作 {atype} 欄位 else 必須是動作清單")
    return {"then": [action_from_dict(a) for a in then],
            "else": [action_from_dict(a) for a in els]}


def _validate_wait_text(p: dict) -> dict:
    _check_no_extra(p, "動作 wait_text",
                    {"region", "pattern", "mode", "timeout_ms", "on_timeout", "goto_index"})
    result = {"region": _get_region(p, "wait_text"),
              "pattern": _get_str(p, "wait_text", "pattern"),
              "mode": _get_mode(p, "wait_text")}
    result.update(_get_wait_common(p, "wait_text"))
    return result


def _validate_wait_image(p: dict) -> dict:
    _check_no_extra(p, "動作 wait_image",
                    {"region", "template", "threshold", "timeout_ms", "on_timeout", "goto_index"})
    result = {"region": _get_region(p, "wait_image"),
              "template": _get_str(p, "wait_image", "template"),
              "threshold": _get_threshold(p, "wait_image")}
    result.update(_get_wait_common(p, "wait_image"))
    return result


def _validate_if_text(p: dict) -> dict:
    _check_no_extra(p, "動作 if_text", {"region", "pattern", "mode", "then", "else"})
    result = {"region": _get_region(p, "if_text"),
              "pattern": _get_str(p, "if_text", "pattern"),
              "mode": _get_mode(p, "if_text")}
    result.update(_get_then_else(p, "if_text"))
    return result


def _validate_if_image(p: dict) -> dict:
    _check_no_extra(p, "動作 if_image", {"region", "template", "threshold", "then", "else"})
    result = {"region": _get_region(p, "if_image"),
              "template": _get_str(p, "if_image", "template"),
              "threshold": _get_threshold(p, "if_image")}
    result.update(_get_then_else(p, "if_image"))
    return result


def _validate_click_text(p: dict) -> dict:
    _check_no_extra(p, "動作 click_text", {"region", "pattern", "mode"})
    return {"region": _get_region(p, "click_text"),
            "pattern": _get_str(p, "click_text", "pattern"),
            "mode": _get_mode(p, "click_text")}


def _validate_click_image(p: dict) -> dict:
    _check_no_extra(p, "動作 click_image", {"region", "template", "threshold"})
    return {"region": _get_region(p, "click_image"),
            "template": _get_str(p, "click_image", "template"),
            "threshold": _get_threshold(p, "click_image")}
```

(c) `_VALIDATORS` dict 於 `ActionType.RUN_SCRIPT: _validate_run_script,` 之後追加：

```python
    ActionType.WAIT_TEXT: _validate_wait_text,
    ActionType.WAIT_IMAGE: _validate_wait_image,
    ActionType.IF_TEXT: _validate_if_text,
    ActionType.IF_IMAGE: _validate_if_image,
    ActionType.CLICK_TEXT: _validate_click_text,
    ActionType.CLICK_IMAGE: _validate_click_image,
```

(d) `action_to_dict` 整個函式替換為（`actions`/`then`/`else` 三個巢狀動作鍵統一遞迴）：

```python
_NESTED_ACTION_KEYS = ("actions", "then", "else")


def action_to_dict(action: Action) -> dict:
    result: dict[str, Any] = {"type": str(action.type)}
    for key, value in action.params.items():
        if key in _NESTED_ACTION_KEYS:
            result[key] = [action_to_dict(a) for a in value]
        else:
            result[key] = value
    return result
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_models_vision_actions.py tests/core/test_models_action.py -v`
Expected: 45 passed（vision_actions 20 + models_action 25）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **263 passed, 1 skipped**（243 + 20）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_vision_actions.py
git commit -m "feat: wait_/if_/click_ 六種視覺動作驗證與 action_to_dict 巢狀泛化"
```

---

### Task 7a: Player 索引機重構 + wait_text / wait_image（輪詢、逾時、goto）

把 `_run_actions` 由 for 迴圈改為索引機、`_run_one` 回傳可選控制訊號，讓 `on_timeout: goto` 能跳到同層 `goto_index`（spec §5.2/§10）。實作 `wait_text` / `wait_image`：輪詢擷取 region、比對，命中即繼續；逾時依 `on_timeout` abort/continue/goto；輪詢等待走可中斷的 `_sleep`（stop_event 提早醒來）。Retina 座標鏈於此建立（擷取用實體像素 region）。模板由注入的 `templates` loader 依名載入。

**控制訊號契約：** `_run_one` 回傳 `None`（正常，index += 1）或 `_Goto(index)`（跳轉，index 設為該值，不 +1）。`_run_actions` 為索引機：`i = 0; while i < len(actions): sig = _run_one(...); i = sig.index if isinstance(sig, _Goto) else i + 1`。`goto_index` 超出範圍 → `_PlayerAbort`。巢狀清單（loop/if 的 `then`/`else`）各自呼叫 `_run_actions`，goto 僅在動作所在的那一層生效。

**Files:**
- Modify: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_wait.py`（新檔，10 個）

**Interfaces:**
- Consumes: `screen_capture`/`ocr_engine`（platform，Task 2/5）、`match_template`/`find_text`（vision，Task 3/4）、`Rect`（geometry）
- Produces（Task 7b/9 依賴）:
  - `_Goto(index: int)` frozen dataclass
  - `Player(platform, storage=None, stop_event=None, sleep=None, rng=None, templates=None)` — `templates: Callable[[str], np.ndarray] | None`（模板名→BGR 影像）；視覺動作無 `screen_capture`/`ocr_engine`/`templates` 時 `_PlayerAbort` 繁中
  - `Player._capture_region(win, region) -> np.ndarray`（依座標鏈換算為實體像素 region 後 `capture`）
  - `Player._region_center_to_screen(win, region, cx, cy) -> tuple[int,int]`（命中中心 px → 螢幕絕對點）
  - `_run_actions(actions, script, win) -> None`（索引機）；`_run_one(...) -> _Goto | None`

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_wait.py`（新檔）：

```python
import threading

import numpy as np

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window(x=0, y=0, w=200, h=100):
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=x, y=y, width=w, height=h, is_active=False)


def box(text, x=0, y=0, w=10, h=10):
    return TextBox(text=text, x=x, y=y, width=w, height=h, confidence=0.9)


def make_platform(capture=None, ocr=None, windows=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    platform = Platform(input_backend=backend, window_manager=manager,
                        screen_capture=capture, ocr_engine=ocr)
    return platform, backend, manager


def make_script(actions):
    return script_from_dict({"name": "測試",
                             "target_window": {"title_pattern": "記事本"},
                             "actions": actions})


def test_wait_text_matches_immediately_then_continues():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("已完成")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([
        {"type": "wait_text", "pattern": "完成"},
        {"type": "key_press", "key": "a"},
    ])
    result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", 0)]


def test_wait_text_polls_until_match():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[[box("讀取中")], [box("讀取中")], [box("完成")]])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    sleeps = []
    script = make_script([{"type": "wait_text", "pattern": "完成", "timeout_ms": 100000}])
    result = Player(platform, sleep=sleeps.append).play(script)
    assert result.ok
    assert len(ocr.calls) == 3       # 前兩輪不中、第三輪命中
    assert len(sleeps) == 2          # 兩次輪詢間隔


def test_wait_text_timeout_abort():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    # 注入固定時鐘：第一次檢查 deadline 未到、第二次已過
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([{"type": "wait_text", "pattern": "沒有", "timeout_ms": 500}])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok is False
    assert "逾時" in result.error


def test_wait_text_timeout_continue_runs_next():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([
        {"type": "wait_text", "pattern": "沒有", "timeout_ms": 500, "on_timeout": "continue"},
        {"type": "key_press", "key": "a"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", 0)]


def test_wait_text_timeout_goto_jumps():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([
        {"type": "wait_text", "pattern": "沒有", "timeout_ms": 500,
         "on_timeout": "goto", "goto_index": 2},
        {"type": "key_press", "key": "z"},   # 被 goto 跳過
        {"type": "key_press", "key": "b"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "b", 0)]


def test_goto_can_jump_backward():
    cap = FakeScreenCapture(scale=1.0)
    # 第一輪不中→goto 回 index 0 再等一次→第二輪命中
    ocr = FakeOcrEngine(boxes=[[box("其他")], [box("完成")]])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 999.0, 0.0, 0.0])
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "timeout_ms": 1,
         "on_timeout": "goto", "goto_index": 0},
        {"type": "key_press", "key": "d"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "d", 0)]


def test_wait_text_stop_event_interrupts_poll():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    stop = threading.Event()

    def sleeper(_s):
        stop.set()  # 第一次輪詢等待即設停止

    script = make_script([{"type": "wait_text", "pattern": "沒有", "timeout_ms": 100000}])
    result = Player(platform, stop_event=stop, sleep=sleeper).play(script)
    assert result.ok is False
    assert "手動停止" in result.error


def test_wait_image_matches_via_template_loader():
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[40:50, 80:92] = tpl
    cap = FakeScreenCapture(image=scene, scale=1.0)
    platform, backend, _ = make_platform(capture=cap)
    script = make_script([
        {"type": "wait_image", "template": "綠塊"},
        {"type": "key_press", "key": "a"},
    ])
    result = Player(platform, sleep=lambda s: None,
                    templates=lambda name: tpl).play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", 0)]


def test_wait_text_captures_region_in_physical_pixels_with_scale():
    from keyboard_executor.core.geometry import Rect

    cap = FakeScreenCapture(scale=2.0)
    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, _, _ = make_platform(capture=cap,
                                   ocr=ocr, windows=[make_window(x=10, y=20)])
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "region": [5, 6, 30, 40]},
    ])
    Player(platform, sleep=lambda s: None).play(script)
    # (win.x+rx)*scale=(10+5)*2=30, (20+6)*2=52, 30*2=60, 40*2=80
    assert cap.captures == [Rect(30, 52, 60, 80)]


def test_vision_action_without_screen_capture_aborts():
    platform, _, _ = make_platform(capture=None, ocr=FakeOcrEngine(boxes=[]))
    script = make_script([{"type": "wait_text", "pattern": "x"}])
    result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok is False
    assert "螢幕擷取" in result.error
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_wait.py -v`
Expected: FAIL — `wait_text`/`wait_image` 落到 `_run_one` 的 else 分支 `動作類型尚未支援`（`result.ok` False 但 error 訊息不含「完成/逾時/手動停止」）；`_Goto`、`_clock`、`templates` 參數不存在的相關測試各自失敗。

- [ ] **Step 3: 修改 player.py**

(a) import 區塊——`from keyboard_executor.core.geometry import Point, to_absolute` 改為：

```python
from keyboard_executor.core.geometry import Point, Rect, to_absolute
from keyboard_executor.core.vision import find_text, match_template
```

並加 `import time`（clock 用）於 `import threading` 之後。

(b) `_PlayerAbort` 之後新增控制訊號：

```python
@dataclass(frozen=True)
class _Goto:
    """_run_one 的控制訊號：跳到同層動作清單的 index（不 +1）。"""
    index: int
```

(c) `__init__` 簽名與 body 補 `templates` 與 `_clock`：

```python
    def __init__(self, platform: Platform, storage=None, stop_event=None,
                 sleep=None, rng=None, templates=None, clock=time.monotonic):
        self._platform = platform
        self._storage = storage
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep if sleep is not None else (
            lambda seconds: self._stop.wait(seconds) and None)
        self._rng = rng if rng is not None else random.Random()
        self._templates = templates
        self._clock = clock
        self._actions_run = 0
        self._script_stack: list[str] = []
        self._current_depth = 0
```

（`Player` 類 docstring 補一句：「視覺動作（wait_/if_/click_）需 platform 提供 screen_capture、ocr_engine，模板動作另需 templates loader；缺任一則安全中止。輪詢間隔 `_POLL_INTERVAL_MS`（500ms）以可中斷 `_sleep` 等待。」）

模組頂部常數區（`_MAX_RUN_SCRIPT_DEPTH = 8` 附近）加：

```python
_POLL_INTERVAL_MS = 500  # wait_* 輪詢間隔（毫秒）
```

(d) `_run_actions` 整個方法替換為索引機：

```python
    def _run_actions(self, actions, script: Script, win: WindowInfo) -> None:
        i = 0
        while i < len(actions):
            self._check_stop()
            signal = self._run_one(actions[i], script, win)
            self._actions_run += 1
            if isinstance(signal, _Goto):
                if not 0 <= signal.index < len(actions):
                    raise _PlayerAbort(f"goto_index 超出範圍: {signal.index}")
                i = signal.index
            else:
                i = i + 1
```

(e) `_ensure_alive` 之後新增視覺共用 helper：

```python
    def _require_capture(self):
        cap = self._platform.screen_capture
        if cap is None:
            raise _PlayerAbort("此動作需要螢幕擷取能力，但平台未提供")
        return cap

    def _region_rect(self, win: WindowInfo, region):
        """region（視窗相對，點；None=整個視窗）→ 螢幕絕對實體像素 Rect，並回傳
        (Rect, rx, ry, scale) 供命中中心換算。"""
        fresh = self._platform.window_manager.refresh(win)
        if fresh is None:
            raise _PlayerAbort("目標視窗已關閉")
        cap = self._require_capture()
        scale = cap.scale_factor()
        if region is None:
            rx, ry, rw, rh = 0, 0, fresh.width, fresh.height
        else:
            rx, ry, rw, rh = region
        rect = Rect(round((fresh.x + rx) * scale), round((fresh.y + ry) * scale),
                    round(rw * scale), round(rh * scale))
        return rect, rx, ry, scale, fresh

    def _center_to_screen(self, fresh, rx, ry, scale, cx, cy) -> tuple[int, int]:
        """命中中心（region 相對，實體像素）→ 螢幕絕對點。"""
        rel = Point(rx + round(cx / scale), ry + round(cy / scale))
        pt = to_absolute(Point(fresh.x, fresh.y), rel)
        return pt.x, pt.y

    def _load_template(self, name: str):
        if self._templates is None:
            raise _PlayerAbort("此動作需要模板來源，但未提供")
        return self._templates(name)

    def _match_once_text(self, win, region, pattern, mode):
        rect, rx, ry, scale, fresh = self._region_rect(win, region)
        cap = self._require_capture()
        ocr = self._platform.ocr_engine
        if ocr is None:
            raise _PlayerAbort("此動作需要 OCR 能力，但平台未提供")
        image = cap.capture(rect)
        hit = find_text(ocr.recognize(image), pattern, mode)
        if hit is None:
            return None
        cx = hit.x + hit.width // 2
        cy = hit.y + hit.height // 2
        return self._center_to_screen(fresh, rx, ry, scale, cx, cy)

    def _match_once_image(self, win, region, template_name, threshold):
        rect, rx, ry, scale, fresh = self._region_rect(win, region)
        cap = self._require_capture()
        image = cap.capture(rect)
        template = self._load_template(template_name)
        m = match_template(image, template, threshold=threshold)
        if not m.found:
            return None
        return self._center_to_screen(fresh, rx, ry, scale, m.x, m.y)

    def _poll_until(self, matcher, timeout_ms) -> tuple[int, int] | None:
        """輪詢 matcher() 直到回傳座標或逾時；stop_event 於 _sleep 途中提早醒來。
        逾時回傳 None。"""
        deadline = self._clock() + timeout_ms / 1000
        while True:
            self._check_stop()
            hit = matcher()
            if hit is not None:
                return hit
            if self._clock() >= deadline:
                return None
            self._sleep(_POLL_INTERVAL_MS / 1000)

    def _run_wait(self, action, win) -> _Goto | None:
        p = action.params
        if action.type is ActionType.WAIT_TEXT:
            hit = self._poll_until(
                lambda: self._match_once_text(win, p["region"], p["pattern"], p["mode"]),
                p["timeout_ms"])
        else:  # WAIT_IMAGE
            hit = self._poll_until(
                lambda: self._match_once_image(win, p["region"], p["template"], p["threshold"]),
                p["timeout_ms"])
        if hit is not None:
            return None
        on_timeout = p["on_timeout"]
        if on_timeout == "continue":
            return None
        if on_timeout == "goto":
            return _Goto(p["goto_index"])
        raise _PlayerAbort(f"動作 {action.type} 等待逾時（{p['timeout_ms']}ms）")
```

（`_check_stop` 於 `_poll_until` 每輪呼叫；`_sleep` 途中設 stop → 下一輪 `_check_stop` 拋 `已手動停止`。）

(f) `_run_one` 簽名改為回傳控制訊號，並在 `RUN_SCRIPT` 分支之後、`else` 之前插入 wait 分派；所有既有分支結尾維持隱含回傳 `None`：

`def _run_one(...)` 的回傳型別註記改為 `-> _Goto | None`；在 `elif atype is ActionType.RUN_SCRIPT:` 區塊之後插入：

```python
        elif atype in (ActionType.WAIT_TEXT, ActionType.WAIT_IMAGE):
            return self._run_wait(action, win)
```

（`_run_one` 其餘既有分支不動；函式最後隱含回傳 `None`。`LOOP` 分支內部呼叫 `self._run_actions(...)` 已是索引機，goto 不會穿透 loop 邊界。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_wait.py tests/core/test_player_basic.py tests/core/test_player_flow.py tests/core/test_player_alive.py tests/core/test_player_stop.py -v`
Expected: 37 passed（wait 10 + basic 9 + flow 13 + alive 3 + stop 2；既有 27 個回放測試不得回歸）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **273 passed, 1 skipped**（263 + 10）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_wait.py
git commit -m "feat: Player 索引機重構與 wait_text/wait_image（輪詢/逾時/goto）"
```

---

### Task 7b: Player if_text / if_image 分支 + click_text / click_image 點擊命中中心

在 7a 的索引機與座標鏈之上，補 `if_text` / `if_image`（單次比對 → 走 `then` 或 `else` 巢狀清單）與 `click_text` / `click_image`（找到 → 點擊命中中心，走完整 Retina 座標鏈；找不到 → 記錄並略過，不點擊）。

**Files:**
- Modify: `src/keyboard_executor/core/player.py`
- Test: `tests/core/test_player_vision.py`（新檔，11 個）

**Interfaces:**
- Consumes: 7a 的 `_match_once_text`/`_match_once_image`/`_run_actions`
- Produces:
  - `if_*`：條件一次比對；true→`_run_actions(then)`、false→`_run_actions(else)`（`else` 預設 `[]`）；分支內動作照常計入 `actions_run`
  - `click_*`：命中→`backend.mouse_click(sx, sy, LEFT, 1)`；未命中→不點擊、正常前進（不視為錯誤，spec §8 管線比對不中不觸發）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_player_vision.py`（新檔）：

```python
import numpy as np

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import MouseButton, TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window(x=0, y=0, w=200, h=100):
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=x, y=y, width=w, height=h, is_active=False)


def tbox(text, x=0, y=0, w=10, h=10):
    return TextBox(text=text, x=x, y=y, width=w, height=h, confidence=0.9)


def make_platform(capture=None, ocr=None, windows=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    platform = Platform(input_backend=backend, window_manager=manager,
                        screen_capture=capture, ocr_engine=ocr)
    return platform, backend, manager


def make_script(actions):
    return script_from_dict({"name": "測試",
                             "target_window": {"title_pattern": "記事本"},
                             "actions": actions})


def run(actions, capture=None, ocr=None, windows=None, templates=None):
    platform, backend, _ = make_platform(capture=capture, ocr=ocr, windows=windows)
    result = Player(platform, sleep=lambda s: None, templates=templates).play(
        make_script(actions))
    return result, backend


def green_scene_and_template():
    # 12x12 模板，置於 (x=80, y=40) → 中心 (86, 46)：偶數座標，scale=2 除法無捨入歧義
    tpl = np.zeros((12, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[40:52, 80:92] = tpl
    return scene, tpl


def test_if_text_true_runs_then():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("勝利")]))
    assert result.ok
    assert backend.calls == [("key_press", "a", 0)]


def test_if_text_false_runs_else():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("失敗")]))
    assert result.ok
    assert backend.calls == [("key_press", "b", 0)]


def test_if_text_false_no_else_is_noop():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("失敗")]))
    assert result.ok
    assert backend.calls == []


def test_if_image_true_runs_then():
    scene, tpl = green_scene_and_template()
    result, backend = run(
        [{"type": "if_image", "template": "綠",
          "then": [{"type": "key_press", "key": "a"}]}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("key_press", "a", 0)]


def test_if_image_false_runs_else():
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 0] = 255  # 場景沒有的藍塊
    result, backend = run(
        [{"type": "if_image", "template": "藍", "threshold": 0.99,
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("key_press", "b", 0)]


def test_click_text_clicks_center():
    # box 位於 region 影像 (x=80,y=40,w=20,h=10) → 中心 (90,45)；scale=1、win 原點 0
    result, backend = run(
        [{"type": "click_text", "pattern": "登入"}],
        capture=FakeScreenCapture(scale=1.0),
        ocr=FakeOcrEngine(boxes=[tbox("登入", x=80, y=40, w=20, h=10)]))
    assert result.ok
    assert backend.calls == [("mouse_click", 90, 45, MouseButton.LEFT, 1)]


def test_click_text_not_found_is_noop():
    result, backend = run(
        [{"type": "click_text", "pattern": "登入"}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("其他")]))
    assert result.ok
    assert backend.calls == []


def test_click_image_clicks_center_with_scale():
    scene, tpl = green_scene_and_template()  # 綠塊中心 px=(86,46) 於 region 影像
    # scale=2、win 原點 (10,20)、region=None：
    #   window-rel 點 = (round(86/2), round(46/2)) = (43, 23)
    #   螢幕絕對點 = (10+43, 20+23) = (53, 43)
    result, backend = run(
        [{"type": "click_image", "template": "綠"}],
        capture=FakeScreenCapture(image=scene, scale=2.0),
        windows=[make_window(x=10, y=20)], templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("mouse_click", 53, 43, MouseButton.LEFT, 1)]


def test_click_image_not_found_is_noop():
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 0] = 255
    result, backend = run(
        [{"type": "click_image", "template": "藍", "threshold": 0.99}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == []


def test_click_text_region_offset_center_with_scale():
    # region=[5,6,...]（點）、scale=2、win 原點 (10,20)
    # box 中心於 region 影像 px=(40,20)：
    #   window-rel 點 = (5 + round(40/2), 6 + round(20/2)) = (25, 16)
    #   螢幕絕對點 = (10+25, 20+16) = (35, 36)
    result, backend = run(
        [{"type": "click_text", "pattern": "確定", "region": [5, 6, 60, 40]}],
        capture=FakeScreenCapture(scale=2.0),
        windows=[make_window(x=10, y=20)],
        ocr=FakeOcrEngine(boxes=[tbox("確定", x=30, y=10, w=20, h=20)]))
    assert result.ok
    assert backend.calls == [("mouse_click", 35, 36, MouseButton.LEFT, 1)]


def test_if_text_nested_then_runs_through_index_machine():
    result, backend = run(
        [{"type": "if_text", "pattern": "x",
          "then": [{"type": "key_press", "key": "a"},
                   {"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("x")]))
    assert result.ok
    assert backend.calls == [("key_press", "a", 0), ("key_press", "b", 0)]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_player_vision.py -v`
Expected: FAIL — `if_*`/`click_*` 落到 `_run_one` 的 else 分支「動作類型尚未支援」，全部 11 個 `result.ok` False（或 error 訊息不符）。

- [ ] **Step 3: 修改 player.py**

在 `_run_one` 的 wait 分派之後插入 if 與 click 分派：

```python
        elif atype in (ActionType.IF_TEXT, ActionType.IF_IMAGE):
            self._run_if(action, script, win)
        elif atype in (ActionType.CLICK_TEXT, ActionType.CLICK_IMAGE):
            self._run_click(action, win)
```

`_run_wait` 之後新增：

```python
    def _run_if(self, action, script: Script, win: WindowInfo) -> None:
        p = action.params
        if action.type is ActionType.IF_TEXT:
            hit = self._match_once_text(win, p["region"], p["pattern"], p["mode"])
        else:  # IF_IMAGE
            hit = self._match_once_image(win, p["region"], p["template"], p["threshold"])
        branch = p["then"] if hit is not None else p["else"]
        self._run_actions(branch, script, win)

    def _run_click(self, action, win: WindowInfo) -> None:
        p = action.params
        if action.type is ActionType.CLICK_TEXT:
            hit = self._match_once_text(win, p["region"], p["pattern"], p["mode"])
        else:  # CLICK_IMAGE
            hit = self._match_once_image(win, p["region"], p["template"], p["threshold"])
        if hit is None:
            return  # 比對不中：不點擊、正常前進（spec §8 管線不中不觸發）
        self._platform.input_backend.mouse_click(hit[0], hit[1], MouseButton.LEFT, 1)
```

（`_match_once_text`/`_match_once_image` 回傳的是已換算好的螢幕絕對點 `(sx, sy)`，直接送 backend。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_player_vision.py tests/core/test_player_wait.py -v`
Expected: 21 passed（vision 11 + wait 10）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **284 passed, 1 skipped**（273 + 11）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/player.py tests/core/test_player_vision.py
git commit -m "feat: Player if_/click_ 視覺動作（分支與點擊命中中心，Retina 換算）"
```

---

### Task 8: Rule 模型 + 規則/模板儲存

`core/models.py` 新增 `Rule` dataclass 與 `rule_from_dict`/`rule_to_dict`（spec §5.3，重用既有 `_validate_target_window`/`_get_region`/`_get_int` 等 helper，故置於 models.py 而非新模組——內聚於「腳本資料模型與驗證」）。`storage/rules.py`（`RuleStorage`，rules/ 子目錄）與 `storage/templates.py`（`TemplateStore`，templates/ 子目錄，OpenCV 讀寫 PNG）。

**磁碟佈局（定義）:** 使用者資料目錄 `<root>/`：腳本 `<root>/<name>.json`；規則 `<root>/rules/<name>.json`；模板 `<root>/templates/<name>.png`（spec §5「同目錄的 templates/ 子目錄」、§8.2）。

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（Rule 模型）
- Create: `src/keyboard_executor/storage/rules.py`
- Create: `src/keyboard_executor/storage/templates.py`
- Test: `tests/core/test_models_rule.py`（新檔，15 個）
- Test: `tests/storage/test_rule_storage.py`（新檔，5 個）
- Test: `tests/storage/test_templates.py`（新檔，3 個）

**Interfaces:**
- Produces（Task 9/10 依賴）:
  - `Rule(name, target_window: TargetWindow, region, condition: RuleCondition, interval_sec: float, cooldown_sec: float, trigger: RuleTrigger, enabled: bool)`（frozen）
  - `RuleCondition(type: "text"|"image", pattern|template, mode|threshold)`；`RuleTrigger(type: "run_script"|"stop_all"|"notify", script_name?, message?)`
  - `rule_from_dict(data) -> Rule` / `rule_to_dict(rule) -> dict`（嚴格驗證，繁中）
  - `RuleStorage(root)`：`save`/`load`/`list_names`/`load_enabled() -> list[Rule]`（rules/ 子目錄；OSError→ScriptValidationError）
  - `TemplateStore(root)`：`save_template(name, image)`/`load_template(name) -> np.ndarray`（templates/ 子目錄；缺檔→ScriptValidationError）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_models_rule.py`（新檔）：

```python
import pytest

from keyboard_executor.core.models import ScriptValidationError, rule_from_dict, rule_to_dict


def minimal(**over):
    data = {
        "name": "斷線重連",
        "target_window": {"title_pattern": ".*遊戲.*"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "run_script", "script_name": "重連流程"},
    }
    data.update(over)
    return data


def test_rule_minimal_defaults():
    r = rule_from_dict(minimal())
    assert r.name == "斷線重連"
    assert r.region is None
    assert r.condition.type == "text" and r.condition.pattern == "連線中斷"
    assert r.condition.mode == "contains"
    assert r.interval_sec == 5.0 and r.cooldown_sec == 60.0
    assert r.trigger.type == "run_script" and r.trigger.script_name == "重連流程"
    assert r.enabled is True


def test_rule_condition_text_regex_mode():
    r = rule_from_dict(minimal(condition={"type": "text", "pattern": r"\d+",
                                          "mode": "regex"}))
    assert r.condition.mode == "regex"


def test_rule_condition_image_threshold_default():
    r = rule_from_dict(minimal(condition={"type": "image", "template": "圖"}))
    assert r.condition.type == "image" and r.condition.template == "圖"
    assert r.condition.threshold == 0.85


def test_rule_condition_type_must_be_text_or_image():
    with pytest.raises(ScriptValidationError, match="condition"):
        rule_from_dict(minimal(condition={"type": "audio", "pattern": "x"}))


def test_rule_region_null_or_four_ints():
    r = rule_from_dict(minimal(region=[0, 0, 100, 50]))
    assert r.region == [0, 0, 100, 50]
    with pytest.raises(ScriptValidationError, match="region"):
        rule_from_dict(minimal(region=[1, 2]))


def test_rule_interval_must_be_positive():
    with pytest.raises(ScriptValidationError, match="interval_sec"):
        rule_from_dict(minimal(interval_sec=0))


def test_rule_cooldown_non_negative():
    with pytest.raises(ScriptValidationError, match="cooldown_sec"):
        rule_from_dict(minimal(cooldown_sec=-1))
    assert rule_from_dict(minimal(cooldown_sec=0)).cooldown_sec == 0.0


def test_rule_trigger_run_script_needs_name():
    with pytest.raises(ScriptValidationError, match="script_name"):
        rule_from_dict(minimal(trigger={"type": "run_script"}))


def test_rule_trigger_stop_all_no_extra():
    r = rule_from_dict(minimal(trigger={"type": "stop_all"}))
    assert r.trigger.type == "stop_all"
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        rule_from_dict(minimal(trigger={"type": "stop_all", "script_name": "x"}))


def test_rule_trigger_notify_message():
    r = rule_from_dict(minimal(trigger={"type": "notify", "message": "有事發生"}))
    assert r.trigger.type == "notify" and r.trigger.message == "有事發生"


def test_rule_trigger_type_invalid():
    with pytest.raises(ScriptValidationError, match="trigger"):
        rule_from_dict(minimal(trigger={"type": "explode"}))


def test_rule_enabled_must_be_bool():
    with pytest.raises(ScriptValidationError, match="enabled"):
        rule_from_dict(minimal(enabled="yes"))
    assert rule_from_dict(minimal(enabled=False)).enabled is False


def test_rule_name_path_safe():
    with pytest.raises(ScriptValidationError, match="name"):
        rule_from_dict(minimal(name="a/b"))


def test_rule_unknown_field_rejected():
    with pytest.raises(ScriptValidationError, match="不支援的欄位"):
        rule_from_dict(minimal(extra=1))


def test_rule_to_dict_round_trips():
    src = minimal(region=[1, 2, 30, 40], interval_sec=3, cooldown_sec=10,
                  condition={"type": "image", "template": "圖", "threshold": 0.9},
                  trigger={"type": "notify", "message": "嗨"}, enabled=False)
    assert rule_from_dict(rule_to_dict(rule_from_dict(src))) == rule_from_dict(src)
```

`tests/storage/test_rule_storage.py`（新檔）：

```python
import pytest

from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
from keyboard_executor.storage.rules import RuleStorage


def make_rule(name="規則", enabled=True):
    return rule_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "stop_all"},
        "enabled": enabled,
    })


def test_save_then_load_in_rules_subdir(tmp_path):
    storage = RuleStorage(tmp_path)
    path = storage.save(make_rule("甲"))
    assert path == tmp_path / "rules" / "甲.json"
    assert path.exists()
    assert storage.load("甲") == make_rule("甲")


def test_load_missing_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到規則"):
        RuleStorage(tmp_path).load("無")


def test_load_broken_json_raises(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "壞.json").write_text("{壞", encoding="utf-8")
    with pytest.raises(ScriptValidationError, match="JSON"):
        RuleStorage(tmp_path).load("壞")


def test_load_enabled_filters_disabled(tmp_path):
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("開", enabled=True))
    storage.save(make_rule("關", enabled=False))
    names = [r.name for r in storage.load_enabled()]
    assert names == ["開"]


def test_save_oserror_wrapped(tmp_path, monkeypatch):
    storage = RuleStorage(tmp_path)
    monkeypatch.setattr("pathlib.Path.write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("滿")))
    with pytest.raises(ScriptValidationError, match="無法儲存"):
        storage.save(make_rule("甲"))
```

`tests/storage/test_templates.py`（新檔）：

```python
import numpy as np
import pytest

from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.storage.templates import TemplateStore


def test_save_template_writes_png_in_templates_subdir(tmp_path):
    store = TemplateStore(tmp_path)
    img = np.zeros((8, 12, 3), dtype=np.uint8)
    img[:, :, 2] = 255
    path = store.save_template("紅", img)
    assert path == tmp_path / "templates" / "紅.png"
    assert path.exists()


def test_load_template_returns_ndarray(tmp_path):
    store = TemplateStore(tmp_path)
    img = np.zeros((8, 12, 3), dtype=np.uint8)
    img[2:6, 3:9] = (0, 255, 0)
    store.save_template("綠", img)
    loaded = store.load_template("綠")
    assert isinstance(loaded, np.ndarray)
    assert loaded.shape == (8, 12, 3)


def test_load_template_missing_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到模板"):
        TemplateStore(tmp_path).load_template("無")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_models_rule.py tests/storage/test_rule_storage.py tests/storage/test_templates.py -v`
Expected: FAIL — `ImportError: cannot import name 'rule_from_dict'`（models）、`ModuleNotFoundError` rules/templates 兩模組。

- [ ] **Step 3: 實作**

(a) `src/keyboard_executor/core/models.py`——`script_to_dict` 之後追加 Rule 模型（重用既有 helper）：

```python
@dataclass(frozen=True)
class RuleCondition:
    type: str                       # "text" | "image"
    pattern: str | None = None
    mode: str = "contains"
    template: str | None = None
    threshold: float = 0.85


@dataclass(frozen=True)
class RuleTrigger:
    type: str                       # "run_script" | "stop_all" | "notify"
    script_name: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Rule:
    name: str
    target_window: TargetWindow
    condition: RuleCondition
    trigger: RuleTrigger
    region: list[int] | None = None
    interval_sec: float = 5.0
    cooldown_sec: float = 60.0
    enabled: bool = True


def _get_positive_number(data: dict, name: str, default: float, *, allow_zero: bool) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _err(f"規則欄位 {name} 必須是數字")
    if allow_zero and value < 0:
        _err(f"規則欄位 {name} 必須 >= 0")
    if not allow_zero and value <= 0:
        _err(f"規則欄位 {name} 必須 > 0")
    return float(value)


def _validate_rule_condition(data: Any) -> RuleCondition:
    if not isinstance(data, dict) or "type" not in data:
        _err("規則 condition 必須是含 type 的 JSON 物件")
    ctype = data["type"]
    if ctype == "text":
        _check_no_extra(data, "規則 condition", {"type", "pattern", "mode"})
        return RuleCondition(type="text", pattern=_get_str(data, "condition", "pattern"),
                             mode=_get_mode(data, "condition"))
    if ctype == "image":
        _check_no_extra(data, "規則 condition", {"type", "template", "threshold"})
        return RuleCondition(type="image", template=_get_str(data, "condition", "template"),
                             threshold=_get_threshold(data, "condition"))
    _err(f"規則 condition.type 必須是 text 或 image: {ctype!r}")


def _validate_rule_trigger(data: Any) -> RuleTrigger:
    if not isinstance(data, dict) or "type" not in data:
        _err("規則 trigger 必須是含 type 的 JSON 物件")
    ttype = data["type"]
    if ttype == "run_script":
        _check_no_extra(data, "規則 trigger", {"type", "script_name"})
        return RuleTrigger(type="run_script",
                           script_name=_get_str(data, "trigger", "script_name"))
    if ttype == "stop_all":
        _check_no_extra(data, "規則 trigger", {"type"})
        return RuleTrigger(type="stop_all")
    if ttype == "notify":
        _check_no_extra(data, "規則 trigger", {"type", "message"})
        return RuleTrigger(type="notify", message=_get_str(data, "trigger", "message"))
    _err(f"規則 trigger.type 必須是 run_script、stop_all 或 notify: {ttype!r}")


def rule_from_dict(data: Any) -> Rule:
    if not isinstance(data, dict):
        _err("規則必須是 JSON 物件")
    _check_no_extra(data, "規則", {"name", "target_window", "region", "condition",
                                   "interval_sec", "cooldown_sec", "trigger", "enabled"})
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        _err("規則欄位 name 必須是非空字串且不含路徑分隔字元")
    if "target_window" not in data:
        _err("規則缺少欄位 target_window")
    target = _validate_target_window(data["target_window"])
    region = _get_region(data, "規則")
    if "condition" not in data:
        _err("規則缺少欄位 condition")
    condition = _validate_rule_condition(data["condition"])
    if "trigger" not in data:
        _err("規則缺少欄位 trigger")
    trigger = _validate_rule_trigger(data["trigger"])
    interval = _get_positive_number(data, "interval_sec", 5.0, allow_zero=False)
    cooldown = _get_positive_number(data, "cooldown_sec", 60.0, allow_zero=True)
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        _err("規則欄位 enabled 必須是布林值")
    return Rule(name=name, target_window=target, condition=condition, trigger=trigger,
                region=region, interval_sec=interval, cooldown_sec=cooldown, enabled=enabled)


def rule_to_dict(rule: Rule) -> dict:
    if rule.condition.type == "text":
        cond = {"type": "text", "pattern": rule.condition.pattern,
                "mode": rule.condition.mode}
    else:
        cond = {"type": "image", "template": rule.condition.template,
                "threshold": rule.condition.threshold}
    trig: dict[str, Any] = {"type": rule.trigger.type}
    if rule.trigger.type == "run_script":
        trig["script_name"] = rule.trigger.script_name
    elif rule.trigger.type == "notify":
        trig["message"] = rule.trigger.message
    return {
        "name": rule.name,
        "target_window": {"title_pattern": rule.target_window.title_pattern,
                          "app_name": rule.target_window.app_name},
        "region": rule.region,
        "condition": cond,
        "interval_sec": rule.interval_sec,
        "cooldown_sec": rule.cooldown_sec,
        "trigger": trig,
        "enabled": rule.enabled,
    }
```

（`_get_region`/`_get_mode`/`_get_threshold` 已於 Task 6 定義於 models.py，此處重用；`region` 傳整個 rule dict、鍵名 `region`——`_get_region` 讀 `params.get("region")`，語意一致。）

(b) 建立 `src/keyboard_executor/storage/rules.py`：

```python
"""規則 JSON 檔案存取。一個規則一個檔：<root>/rules/<name>.json。"""
from __future__ import annotations

import json
from pathlib import Path

from keyboard_executor.core.models import (
    Rule,
    ScriptValidationError,
    rule_from_dict,
    rule_to_dict,
)


class RuleStorage:
    def __init__(self, root: str | Path):
        self._dir = Path(root) / "rules"

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or not name.strip():
            raise ScriptValidationError(f"規則名稱不合法: {name!r}")
        return self._dir / f"{name}.json"

    def save(self, rule: Rule) -> Path:
        path = self.path_for(rule.name)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(rule_to_dict(rule), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
        except OSError as e:
            raise ScriptValidationError(f"規則 {rule.name!r} 無法儲存: {e}") from e
        return path

    def load(self, name: str) -> Rule:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到規則 {name!r}（{path}）")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ScriptValidationError(f"規則 {name!r} 不是合法 JSON: {e}") from e
        except (UnicodeDecodeError, OSError) as e:
            raise ScriptValidationError(f"規則 {name!r} 無法讀取: {e}") from e
        return rule_from_dict(data)

    def list_names(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def load_enabled(self) -> list[Rule]:
        return [r for r in (self.load(n) for n in self.list_names()) if r.enabled]
```

(c) 建立 `src/keyboard_executor/storage/templates.py`：

```python
"""模板圖檔（PNG）存取：<root>/templates/<name>.png。OpenCV 讀寫（BGR）。"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from keyboard_executor.core.models import ScriptValidationError


class TemplateStore:
    def __init__(self, root: str | Path):
        self._dir = Path(root) / "templates"

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or not name.strip():
            raise ScriptValidationError(f"模板名稱不合法: {name!r}")
        return self._dir / f"{name}.png"

    def save_template(self, name: str, image: np.ndarray) -> Path:
        path = self.path_for(name)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(path), image):
                raise OSError("cv2.imwrite 失敗")
        except OSError as e:
            raise ScriptValidationError(f"模板 {name!r} 無法儲存: {e}") from e
        return path

    def load_template(self, name: str) -> np.ndarray:
        path = self.path_for(name)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ScriptValidationError(f"找不到模板 {name!r}（{path}）")
        return image
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_models_rule.py tests/storage/test_rule_storage.py tests/storage/test_templates.py -v`
Expected: 23 passed（rule 15 + rule_storage 5 + templates 3）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **307 passed, 1 skipped**（284 + 23）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/models.py src/keyboard_executor/storage/rules.py src/keyboard_executor/storage/templates.py tests/core/test_models_rule.py tests/storage/test_rule_storage.py tests/storage/test_templates.py
git commit -m "feat: Rule 模型與 RuleStorage/TemplateStore（規則與模板儲存）"
```

---

### Task 9: 規則引擎（watcher + 觸發 + cooldown）

`core/rule_engine.py`：`RuleEngine` 對一組啟用規則各自以 `interval_sec` 輪詢——擷取 region、依 `condition.type` 走 OCR 文字搜尋或模板比對，命中且不在冷卻期時觸發 `trigger`（`run_script`→新 `Player.play`、`stop_all`→設共用 stop、`notify`→呼叫 notifier）。可中斷（共用 stop_event）。冷卻以注入 clock 逐規則計時。全部以 fakes 測。

**Files:**
- Create: `src/keyboard_executor/core/rule_engine.py`
- Test: `tests/core/test_rule_engine.py`（新檔，12 個）

**Interfaces:**
- Consumes: `Platform`（screen_capture/ocr_engine/window_manager）、`find_text`/`match_template`（vision）、`Rule`（models）、`Player`（player）、`Rect`/`geometry`
- Produces（Task 10 依賴）:
  - `RuleEngine(platform, storage, notifier=None, templates=None, player_factory=Player, stop_event=None, sleep=None, clock=time.monotonic)` —
    - `evaluate_once(rules: list[Rule]) -> None` — 對到期規則各評估一次（單元測試主入口，確定性）
    - `run(rules: list[Rule]) -> None` — 迴圈直到 stop_event（`run_watch` 用；以 `sleep` 讓步）
    - 觸發語義：`run_script`→`player_factory(platform, storage=storage, templates=...).play(load(script_name))`；`stop_all`→`self.stop_event.set()`；`notify`→`notifier(message)`
    - 冷卻：每規則記 `last_fired[name]`；`clock() - last < cooldown_sec` 則跳過觸發
    - 間隔：每規則記 `next_due[name]`；`clock() < next_due` 則本輪跳過評估
    - 停用規則不評估（呼叫端傳 `load_enabled()`；`evaluate_once` 亦防守跳過 `enabled=False`）
    - 擷取/OCR 例外：記錄並跳過該規則該輪（spec §10「OCR/截圖失敗記錄並跳過該輪」）

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_rule_engine.py`（新檔）：

```python
import threading

import numpy as np

from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window():
    return WindowInfo(handle=object(), title="遊戲", app_name="App",
                      x=0, y=0, width=200, height=100, is_active=False)


def tbox(text):
    return TextBox(text=text, x=0, y=0, width=10, height=10, confidence=0.9)


def make_platform(capture=None, ocr=None):
    return Platform(input_backend=FakeInputBackend(),
                    window_manager=FakeWindowManager([make_window()]),
                    screen_capture=capture, ocr_engine=ocr)


def text_rule(name="斷線", trigger=None, interval=5, cooldown=60):
    return rule_from_dict({
        "name": name,
        "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "interval_sec": interval, "cooldown_sec": cooldown,
        "trigger": trigger or {"type": "notify", "message": "斷線了"},
    })


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePlayer:
    instances = []

    def __init__(self, platform, storage=None, templates=None, **k):
        self.played = []
        FakePlayer.instances.append(self)

    def play(self, script):
        self.played.append(script.name)


class DictStorage:
    def __init__(self, scripts=None):
        self._s = scripts or {}

    def load(self, name):
        return self._s[name]


def test_text_match_fires_notify():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷了")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])
    assert notes == ["斷線了"]


def test_no_match_no_trigger():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("一切正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])
    assert notes == []


def test_image_match_fires():
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[10:20, 20:32] = tpl
    notes = []
    rule = rule_from_dict({
        "name": "圖", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠"},
        "trigger": {"type": "notify", "message": "命中"}})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == ["命中"]


def test_cooldown_blocks_second_trigger():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(cooldown=60, interval=0.001)
    engine.evaluate_once([rule])
    clock.t = 10.0
    engine.evaluate_once([rule])   # 冷卻未過（10 < 60）
    assert notes == ["斷線了"]


def test_cooldown_expires_fires_again():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(cooldown=60, interval=0.001)
    engine.evaluate_once([rule])
    clock.t = 61.0
    engine.evaluate_once([rule])
    assert notes == ["斷線了", "斷線了"]


def test_interval_skips_until_due():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(interval=5, cooldown=0)
    # 用 ocr 呼叫次數觀察是否評估：正常→不觸發，但 recognize 會被呼叫
    ocr = engine._platform.ocr_engine
    engine.evaluate_once([rule])       # t=0 首次到期，評估
    engine.evaluate_once([rule])       # t=0 未到下次到期（0 < 5），跳過
    clock.t = 5.0
    engine.evaluate_once([rule])       # t=5 到期，再評估
    assert len(ocr.calls) == 2


def test_disabled_rule_skipped():
    notes = []
    rule = rule_from_dict({
        "name": "停", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "notify", "message": "x"}, "enabled": False})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == []


def test_run_script_trigger_plays_via_player_factory():
    FakePlayer.instances = []
    from keyboard_executor.core.models import script_from_dict
    sub = script_from_dict({"name": "重連", "target_window": {"title_pattern": "遊戲"},
                            "actions": [{"type": "key_press", "key": "a"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage({"重連": sub}),
                        player_factory=FakePlayer, clock=Clock())
    engine.evaluate_once([text_rule(trigger={"type": "run_script", "script_name": "重連"})])
    assert FakePlayer.instances[-1].played == ["重連"]


def test_stop_all_trigger_sets_stop_event():
    stop = threading.Event()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), stop_event=stop, clock=Clock())
    engine.evaluate_once([text_rule(trigger={"type": "stop_all"})])
    assert stop.is_set()


def test_run_loops_until_stop_event():
    stop = threading.Event()
    clock = Clock()
    calls = []

    def sleeper(_s):
        calls.append(1)
        if len(calls) >= 3:
            stop.set()

    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), stop_event=stop, sleep=sleeper, clock=clock)
    engine.run([text_rule(interval=100)])
    assert stop.is_set()


def test_capture_failure_skips_round_without_crashing():
    notes = []

    class BoomCapture(FakeScreenCapture):
        def capture(self, region):
            raise RuntimeError("截圖失敗")

    engine = RuleEngine(make_platform(BoomCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])   # 不得拋例外
    assert notes == []


def test_region_captured_in_physical_pixels_with_scale():
    from keyboard_executor.core.geometry import Rect

    cap = FakeScreenCapture(scale=2.0)
    engine = RuleEngine(make_platform(cap, FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), clock=Clock())
    rule = rule_from_dict({
        "name": "區", "target_window": {"title_pattern": "遊戲"},
        "region": [5, 6, 30, 40],
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "notify", "message": "y"}})
    engine.evaluate_once([rule])
    assert cap.captures == [Rect(10, 12, 60, 80)]  # (5*2,6*2,30*2,40*2)，win 原點 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_rule_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keyboard_executor.core.rule_engine'`（整檔）

- [ ] **Step 3: 實作 rule_engine.py**

`src/keyboard_executor/core/rule_engine.py`：

```python
"""監看規則引擎：定時擷取畫面、比對規則條件、命中且不在冷卻期時觸發（spec §8）。

各規則以自身 interval_sec 輪詢；命中觸發 run_script / stop_all / notify。
擷取/OCR 例外記錄並跳過該輪（spec §10）。外部依賴全注入，預設真實。
"""
from __future__ import annotations

import threading
import time

from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.models import Rule
from keyboard_executor.core.player import Player
from keyboard_executor.core.vision import find_text, match_template


class RuleEngine:
    def __init__(self, platform, storage, notifier=None, templates=None,
                 player_factory=Player, stop_event=None, sleep=None,
                 clock=time.monotonic):
        self._platform = platform
        self._storage = storage
        self._notifier = notifier
        self._templates = templates
        self._player_factory = player_factory
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep if sleep is not None else self.stop_event.wait
        self._clock = clock
        self._next_due: dict[str, float] = {}
        self._last_fired: dict[str, float] = {}

    def run(self, rules) -> None:
        """輪詢迴圈，直到 stop_event。以 sleep 讓步（預設 stop_event.wait 可中斷）。"""
        while not self.stop_event.is_set():
            self.evaluate_once(rules)
            self._sleep(0.1)

    def evaluate_once(self, rules) -> None:
        now = self._clock()
        for rule in rules:
            if not rule.enabled:
                continue
            if now < self._next_due.get(rule.name, 0.0):
                continue
            self._next_due[rule.name] = now + rule.interval_sec
            try:
                matched = self._matches(rule)
            except Exception:
                matched = False  # 擷取/OCR 失敗：記錄並跳過該輪（spec §10）
            if not matched:
                continue
            last = self._last_fired.get(rule.name)
            if last is not None and now - last < rule.cooldown_sec:
                continue
            self._last_fired[rule.name] = now
            self._fire(rule)

    def _matches(self, rule: Rule) -> bool:
        wm = self._platform.window_manager
        windows = wm.find_windows(title_pattern=rule.target_window.title_pattern,
                                  app_name=rule.target_window.app_name)
        if not windows:
            return False
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
            return find_text(boxes, rule.condition.pattern, rule.condition.mode) is not None
        template = self._templates(rule.condition.template)
        return match_template(image, template, threshold=rule.condition.threshold).found

    def _fire(self, rule: Rule) -> None:
        trig = rule.trigger
        if trig.type == "run_script":
            player = self._player_factory(self._platform, storage=self._storage,
                                          templates=self._templates)
            player.play(self._storage.load(trig.script_name))
        elif trig.type == "stop_all":
            self.stop_event.set()
        elif trig.type == "notify" and self._notifier is not None:
            self._notifier(trig.message)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_rule_engine.py -v`
Expected: 12 passed

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **319 passed, 1 skipped**（307 + 12）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/rule_engine.py tests/core/test_rule_engine.py
git commit -m "feat: RuleEngine 監看引擎（間隔輪詢/冷卻/run_script·stop_all·notify 觸發）"
```

---

### Task 10: CLI watch 子命令 + M3 驗收

`cli.py` 新增 `watch [--dir]`：載入啟用規則、以 `RuleEngine` 監看直到 Ctrl+C。可測 `run_watch` seam（元件注入）。真實 OCR/截圖端到端列人工驗收。

**Files:**
- Modify: `src/keyboard_executor/cli.py`（`build_parser` 加 watch、`run_watch` seam、`main` 分派）
- Test: `tests/test_cli_watch.py`（新檔，5 個）

**Interfaces:**
- Consumes: `RuleStorage`（Task 8）、`RuleEngine`（Task 9）、`TemplateStore`（Task 8）、`get_platform`
- Produces:
  - `run_watch(platform, rule_storage, script_storage, templates, echo=print, engine_factory=RuleEngine, rules=None) -> int` — 載入 `rule_storage.load_enabled()`（或注入 `rules`），無啟用規則→提示回傳 0；否則 `engine_factory(platform, storage=script_storage, templates=templates, notifier=echo).run(rules)`，回傳 0。`script_storage`（`ScriptStorage`）供 `run_script` 觸發載入子腳本
  - `main(... , run_watch_fn=run_watch)` watch 分派（darwin 權限先過）

- [ ] **Step 1: 寫失敗測試**

`tests/test_cli_watch.py`（新檔）：

```python
from keyboard_executor.cli import build_parser, main, run_watch
from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.storage.rules import RuleStorage


def make_rule(name="規則", enabled=True):
    return rule_from_dict({
        "name": name, "target_window": {"title_pattern": "記事本"},
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "notify", "message": "y"}, "enabled": enabled})


def test_watch_parser_dir():
    args = build_parser().parse_args(["watch", "--dir", "/tmp/s"])
    assert args.command == "watch" and args.dir == "/tmp/s"


def test_run_watch_runs_engine_with_enabled_rules(tmp_path):
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("開", enabled=True))
    storage.save(make_rule("關", enabled=False))
    ran = {}

    class FakeEngine:
        def __init__(self, platform, storage=None, templates=None, notifier=None):
            ran["init"] = True

        def run(self, rules):
            ran["names"] = [r.name for r in rules]

    code = run_watch(object(), storage, object(), templates=None,
                     echo=lambda *_: None, engine_factory=FakeEngine)
    assert code == 0
    assert ran["names"] == ["開"]


def test_run_watch_no_enabled_rules_message(tmp_path):
    storage = RuleStorage(tmp_path)
    echoes = []
    code = run_watch(object(), storage, object(), templates=None,
                     echo=echoes.append, engine_factory=None)
    assert code == 0
    assert any("沒有啟用" in line for line in echoes)


def test_main_watch_dispatches(tmp_path):
    seen = {}

    def spy_run_watch(platform, rule_storage, script_storage, templates, **k):
        seen["ok"] = True
        return 0

    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                run_watch_fn=spy_run_watch)
    assert code == 0 and seen == {"ok": True}


def test_main_watch_permission_denied(tmp_path):
    called = []
    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                run_watch_fn=lambda *a, **k: called.append(1) or 0)
    assert code == 1 and called == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_cli_watch.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_watch'`；parser 無 `watch` 子命令；`main` 無 `run_watch_fn` 參數。

- [ ] **Step 3: 修改 cli.py**

(a) import 區塊追加：

```python
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.templates import TemplateStore
```

(b) `build_parser` 於 `record` 定義之後、`return parser` 之前追加：

```python
    watch = sub.add_parser("watch", help="監看規則（Ctrl+C 停止）")
    watch.add_argument("--dir", default=None, help="資料目錄（預設 ~/.keyboard-executor/scripts）")
```

(c) `_start_play_guard` 之後新增 `run_watch`（`rule_storage` 供載入啟用規則、`script_storage` 供 `run_script` 觸發載入子腳本、`templates` 為模板名→影像 loader）：

```python
def run_watch(platform, rule_storage, script_storage, templates, echo=print,
              engine_factory=RuleEngine, rules=None) -> int:
    """監看流程（元件全注入，供單元測試）。回傳 exit code。"""
    rules = rules if rules is not None else rule_storage.load_enabled()
    if not rules:
        echo("沒有啟用中的規則")
        return 0
    echo(f"開始監看 {len(rules)} 條規則（Ctrl+C 停止）")
    engine = engine_factory(platform, storage=script_storage,
                            templates=templates, notifier=echo)
    try:
        engine.run(rules)
    except KeyboardInterrupt:
        echo("\n已停止監看")
    return 0
```

(d) `main` 簽名補 `run_watch_fn=run_watch`，並在 `record` 分派之後、`# play` 之前插入 watch 分派：

```python
    if args.command == "watch":
        if not check_permissions():
            return 1
        platform = get_platform()
        data_dir = args.dir or default_scripts_dir()
        return run_watch_fn(platform, RuleStorage(data_dir), storage,
                            TemplateStore(data_dir).load_template)
```

（`storage` 即 `main` 開頭建立的 `ScriptStorage`，供 run_script 觸發載入腳本；`TemplateStore(data_dir).load_template` 作為 templates loader。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_cli_watch.py tests/test_cli.py tests/test_cli_main.py -v`
Expected: 20 passed（watch 5 + cli 7 + cli_main 8）

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **324 passed, 1 skipped**（319 + 5）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/cli.py tests/test_cli_watch.py
git commit -m "feat: CLI watch 子命令與 run_watch seam（M3 監看入口）"
```

- [ ] **Step 7: 人工總驗收（macOS，由人執行——會實際擷圖/OCR/送輸入）**

  1. **權限**：系統設定授予終端機「輔助使用」＋「螢幕錄製」（截圖需後者；缺螢幕錄製時 mss 可能回黑圖——OCR 全空先查權限再判 bug）＋（規則觸發腳本會送輸入，另需既有「輸入監控」不影響截圖）
  2. **安裝原生 OCR**：`pip install "pyobjc-framework-Vision>=10.0"`（Windows 為 `winsdk`）
  3. **模板擷取（暫以程式）**：對目標視窗某按鈕以 mss 擷一小塊存成 `<scripts_dir>/templates/<名>.png`（M4 GUI 區域框選器接手）
  4. **wait_image / click_image**：手編腳本含 `{"type":"click_image","template":"<名>"}`，`play` → 驗證點到按鈕中心（Retina 機器上驗座標未偏移一半——本計畫 scale 換算的實機證據）
  5. **wait_text / click_text**：對含中文文字的畫面編 `wait_text`/`click_text`，驗證 OCR 命中並點中文字中心
  6. **on_timeout: goto**：編一段 `wait_text`（故意找不到、`on_timeout:goto` 跳到後段）→ 驗證逾時後跳轉
  7. **規則監看**：存一條 `condition.type=text` 規則（`interval_sec=3`、`trigger=notify`）→ `python -m keyboard_executor.cli watch` → 讓目標畫面出現關鍵字 → 驗證觸發（notify 印出），冷卻期內不重觸發
  8. **stop_all 觸發**：另一條規則 `trigger=stop_all` → 命中後 watch 停止
  9. **run_script 觸發**：規則 `trigger=run_script` → 命中後子腳本被回放
  10. **Windows backlog（M5 前必補）**：winsdk OCR 實機、mss 多螢幕/DPI 縮放座標、`WindowsOcrEngine._default_*` 原生路徑

---

## 完成定義（M3）

- [ ] `python -m pytest -q` 全綠：**324 passed, 1 skipped**
- [ ] 視覺/規則邏輯單元覆蓋：模板比對（`test_vision_template` 5）、文字搜尋（`test_vision_text` 5）、動作驗證（`test_models_vision_actions` 20）、輪詢/逾時/goto（`test_player_wait` 10）、分支/點擊/Retina 換算（`test_player_vision` 11）、Rule 模型與儲存（`test_models_rule` 15 + `test_rule_storage` 5 + `test_templates` 3）、規則引擎（`test_rule_engine` 12）、CLI 分派（`test_cli_main` 8 + `test_cli_watch` 5）
- [ ] 所有面向使用者的訊息為繁體中文；嚴格驗證（未知欄位/型別/範圍一律 `ScriptValidationError`）
- [ ] 風險收斂：原生 OCR（winsdk / pyobjc Vision）與 mss 實機擷取為 ABC 後的薄適配器，`# pragma: no cover` 標註、列人工驗收；所有可測邏輯以 fakes 測到底
- [ ] Retina 座標鏈以 scale=2 驗算（`test_player_wait` 擷取實體像素 region、`test_player_vision` 點擊命中中心換回點、`test_rule_engine` 規則擷取 region）
- [ ] `Platform` dataclass 以 None 預設擴充兩欄位（`screen_capture`、`ocr_engine`），既有 13 處 `Platform(...)` 建構點零修改

## 後續計畫（不在本計畫範圍）

- **M4**：GUI（PySide6）——主視窗（腳本/規則清單）、腳本編輯器、規則編輯器、區域框選器（兼模板擷取，接手 Task 10 驗收步驟 3 的手動擷模板）；錄製面板沿用 M2b 的 Recorder/SessionGuard/PynputInputHook；`RuleEngine.run` 移入 QThread；Qt6 DPI awareness 呼叫順序確認
- **M5**：打包（PyInstaller）＋ macOS 權限引導（含「螢幕錄製」與「自動化」）；Windows OCR/DPI 實機 backlog 清償
- **本計畫刻意未做（YAGNI）**：多尺度模板搜尋（spec §8.2 進階選項）、OCR 連續失敗 N 次發通知（spec §10 次要路徑，M4 GUI 日誌面板一併）、規則 trigger `stop_all` 跨 session 廣播到「進行中的 play」（M2b 待辦 #3；M3 的 `stop_all` 設共用 stop_event，M4 GUI 統一 session 管理時串接）
