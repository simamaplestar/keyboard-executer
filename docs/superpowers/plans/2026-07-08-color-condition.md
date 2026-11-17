# 規則「顏色」條件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為監看規則新增 `color` 條件類型，用滴管取色偵測指定區域（如小地圖）內某顏色像素的出現/消失。

**Architecture:** 純幾何（色相環繞）在 `core/color_math.py`；cv2 遮罩計數與取樣在 `core/vision.py`；資料模型/驗證/序列化在 `core/models.py`；引擎判定在 `core/rule_engine.py`；滴管覆蓋層在 `app/color_picker.py`（開啟時擷全螢幕當背景、點擊從截圖陣列取樣）；表單接線在 `app/rule_editor_model.py` 與 `app/rule_editor.py`。各層薄件、依賴注入、可獨立單測。

**Tech Stack:** Python 3.13 / PySide6 / OpenCV(headless) / numpy / pytest。

## Global Constraints

- 所有面向使用者的訊息用**繁體中文**，沿用既有錯誤格式（例：`規則 condition 欄位 …`）。
- OpenCV HSV 範圍：**H ∈ [0,179]、S/V ∈ [0,255]**。影像為 **BGR**（mss/`FakeScreenCapture` 皆是）。
- 純邏輯與 cv2 分層：`color_math.py` **不得** import cv2；cv2 運算放 `vision.py`。
- 依賴注入沿用既有模式（`capture_factory`、`get_platform`）；測試用替身，不碰真實螢幕。
- 檔案行尾一律 **LF**。
- 全程 TDD：先寫失敗測試 → 跑到失敗 → 最小實作 → 跑到通過 → commit。

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/core/color_math.py` | 色相環繞區間（純函式） | Create |
| `src/keyboard_executor/core/vision.py` | `count_color_pixels`、`sample_dominant_hsv` | Modify |
| `src/keyboard_executor/core/models.py` | `RuleCondition` color 欄位 + 驗證 + 序列化 | Modify |
| `src/keyboard_executor/core/rule_engine.py` | `_matches` color 分支 | Modify |
| `src/keyboard_executor/app/color_picker.py` | 滴管取色覆蓋層 | Create |
| `src/keyboard_executor/app/action_fields.py` | `CHOICE_LABELS` 加 "color" | Modify |
| `src/keyboard_executor/app/rule_editor_model.py` | 表單友善 color 欄位 | Modify |
| `src/keyboard_executor/app/rule_editor.py` | 規則編輯器 UI 接線 | Modify |
| 對應 `tests/…` | 各層測試 | Create/Modify |

執行順序即任務順序（下層先，UI 最後）。

---

### Task 1: 色相環繞純函式 `color_math.hue_ranges`

**Files:**
- Create: `src/keyboard_executor/core/color_math.py`
- Test: `tests/core/test_color_math.py`

**Interfaces:**
- Consumes: 無
- Produces: `hue_ranges(hue: int, tol: int) -> list[tuple[int, int]]` — OpenCV 色相 (0–179) 的閉區間清單；跨 0/179 邊界回兩段；`tol >= 90` 回 `[(0, 179)]`。

- [ ] **Step 1: 寫失敗測試**

`tests/core/test_color_math.py`：
```python
from keyboard_executor.core.color_math import hue_ranges


def test_hue_ranges_middle_no_wrap():
    assert hue_ranges(90, 10) == [(80, 100)]


def test_hue_ranges_wraps_below_zero():
    assert hue_ranges(0, 10) == [(170, 179), (0, 10)]


def test_hue_ranges_wraps_above_max():
    assert hue_ranges(175, 10) == [(165, 179), (0, 5)]


def test_hue_ranges_full_circle_when_tol_large():
    assert hue_ranges(0, 90) == [(0, 179)]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_color_math.py -v`
Expected: FAIL（`ModuleNotFoundError: keyboard_executor.core.color_math`）

- [ ] **Step 3: 最小實作**

`src/keyboard_executor/core/color_math.py`：
```python
"""顏色條件的純幾何（無 cv2）：OpenCV 色相環（0–179）的比對區間計算。"""
from __future__ import annotations


def hue_ranges(hue: int, tol: int) -> list[tuple[int, int]]:
    """回傳涵蓋 hue±tol 的 OpenCV 色相 (0–179) 閉區間清單。
    色相是環狀（179 接回 0），故跨邊界時回兩段；tol >= 90 已覆蓋整環。"""
    if tol >= 90:
        return [(0, 179)]
    lo = hue - tol
    hi = hue + tol
    if lo < 0:
        return [(180 + lo, 179), (0, hi)]
    if hi > 179:
        return [(lo, 179), (0, hi - 180)]
    return [(lo, hi)]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_color_math.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/color_math.py tests/core/test_color_math.py
git commit -m "feat(color): 色相環繞區間純函式 hue_ranges"
```

---

### Task 2: cv2 顏色計數與取樣 `vision.count_color_pixels` / `sample_dominant_hsv`

**Files:**
- Modify: `src/keyboard_executor/core/vision.py`
- Test: `tests/core/test_vision.py`（既有檔，新增測試函式）

**Interfaces:**
- Consumes: `color_math.hue_ranges`（Task 1）
- Produces:
  - `count_color_pixels(image_bgr, hue, sat, val, hue_tol=10, sat_tol=80, val_tol=80) -> int` — 回區域內符合目標顏色的像素數。
  - `sample_dominant_hsv(image_bgr) -> tuple[int, int, int]` — 一小塊 BGR patch 取飽和度最高像素的 (h, s, v)。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_vision.py` 末端新增（檔頭已有 `import cv2`、`import numpy as np`；若無則一併加）：
```python
from keyboard_executor.core.vision import count_color_pixels, sample_dominant_hsv


def test_count_color_pixels_counts_red_block():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)                      # BGR 純紅
    assert count_color_pixels(img, 0, 255, 255) == 100


def test_count_color_pixels_ignores_grey():
    img = np.full((10, 10, 3), 128, dtype=np.uint8)   # 灰：飽和度 0
    assert count_color_pixels(img, 0, 255, 255) == 0


def test_count_color_pixels_matches_red_near_upper_hue():
    import cv2
    hsv = np.zeros((4, 4, 3), dtype=np.uint8)
    hsv[:, :] = (178, 255, 255)                  # 接近 179 的紅
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert count_color_pixels(bgr, 0, 255, 255, hue_tol=10) == 16


def test_sample_dominant_hsv_picks_saturated_pixel():
    patch = np.full((5, 5, 3), 128, dtype=np.uint8)   # 灰底
    patch[2, 2] = (0, 0, 255)                          # 一顆紅
    h, s, v = sample_dominant_hsv(patch)
    assert h == 0 and s == 255
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_vision.py -k "color or dominant" -v`
Expected: FAIL（`ImportError: cannot import name 'count_color_pixels'`）

- [ ] **Step 3: 最小實作**

在 `src/keyboard_executor/core/vision.py` 檔頭加 import：
```python
from keyboard_executor.core.color_math import hue_ranges
```
於檔案末端新增：
```python
def count_color_pixels(image_bgr: np.ndarray, hue: int, sat: int, val: int,
                       hue_tol: int = 10, sat_tol: int = 80,
                       val_tol: int = 80) -> int:
    """區域 BGR → HSV，回符合目標顏色的像素數。
    H 落在 hue_ranges(hue, hue_tol)（環繞用多段 OR）、
    S >= clamp(sat - sat_tol)、V >= clamp(val - val_tol)。"""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    sv_ok = (s >= max(0, sat - sat_tol)) & (v >= max(0, val - val_tol))
    hue_ok = np.zeros(h.shape, dtype=bool)
    for lo, hi in hue_ranges(hue, hue_tol):
        hue_ok |= (h >= lo) & (h <= hi)
    return int(np.count_nonzero(hue_ok & sv_ok))


def sample_dominant_hsv(image_bgr: np.ndarray) -> tuple[int, int, int]:
    """一小塊 BGR patch → 代表 HSV：取飽和度最高的像素（避開反鋸齒淡邊）。"""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    flat = hsv.reshape(-1, 3)
    idx = int(flat[:, 1].argmax())
    return int(flat[idx, 0]), int(flat[idx, 1]), int(flat[idx, 2])
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_vision.py -v`
Expected: PASS（含新增 4 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/vision.py tests/core/test_vision.py
git commit -m "feat(color): count_color_pixels 與 sample_dominant_hsv"
```

---

### Task 3: 資料模型 `RuleCondition` color 欄位、驗證、序列化

**Files:**
- Modify: `src/keyboard_executor/core/models.py`
- Test: `tests/core/test_models.py`（既有檔，新增測試函式）

**Interfaces:**
- Consumes: 無（沿用既有 `_err`、`_check_no_extra`）
- Produces:
  - `RuleCondition` 新增欄位：`hue:int=0, sat:int=0, val:int=0, hue_tol:int=10, sat_tol:int=80, val_tol:int=80, min_pixels:int=3, absent:bool=False`。
  - `rule_from_dict` / `rule_to_dict` 支援 `type=="color"`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_models.py` 末端新增：
```python
def _color_rule_dict(**cond):
    base = {"type": "color", "hue": 0, "sat": 255, "val": 255}
    base.update(cond)
    return {"name": "紅點", "target_window": {"title_pattern": "遊戲"},
            "condition": base, "trigger": {"type": "notify", "message": "有紅點"}}


def test_color_condition_roundtrip_preserves_fields():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    rule = rule_from_dict(_color_rule_dict(hue_tol=15, min_pixels=5, absent=True))
    assert rule.condition.type == "color"
    assert rule.condition.hue == 0 and rule.condition.min_pixels == 5
    assert rule.condition.absent is True
    again = rule_from_dict(rule_to_dict(rule))
    assert again.condition == rule.condition


def test_color_condition_applies_defaults():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict(_color_rule_dict())
    assert rule.condition.hue_tol == 10 and rule.condition.sat_tol == 80
    assert rule.condition.min_pixels == 3 and rule.condition.absent is False


def test_color_condition_rejects_hue_out_of_range():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(hue=200))


def test_color_condition_rejects_min_pixels_zero():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(min_pixels=0))


def test_color_condition_rejects_non_bool_absent():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_color_rule_dict(absent="yes"))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_models.py -k color -v`
Expected: FAIL（`規則 condition.type 必須是 text 或 image` — color 未支援）

- [ ] **Step 3: 最小實作**

3a. `RuleCondition`（約 `models.py:476`）加欄位：
```python
@dataclass(frozen=True)
class RuleCondition:
    type: str                       # "text" | "image" | "color"
    pattern: str | None = None
    mode: str = "contains"
    template: str | None = None
    threshold: float = 0.85
    hue: int = 0
    sat: int = 0
    val: int = 0
    hue_tol: int = 10
    sat_tol: int = 80
    val_tol: int = 80
    min_pixels: int = 3
    absent: bool = False
```

3b. 在 `_get_threshold`（約 `models.py:222`）後新增兩個共用驗證器：
```python
def _get_int_in(params: dict, label: str, name: str, lo: int, hi: int,
                default: int | None = None) -> int:
    if name not in params:
        if default is None:
            _err(f"{label} 缺少欄位 {name}")
        return default
    v = params[name]
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        _err(f"{label} 欄位 {name} 必須是 {lo}–{hi} 的整數")
    return v


def _get_bool(params: dict, label: str, name: str, default: bool = False) -> bool:
    v = params.get(name, default)
    if not isinstance(v, bool):
        _err(f"{label} 欄位 {name} 必須是布林值")
    return v
```

3c. `_validate_rule_condition`（約 `models.py:523`）在 `image` 分支後、最終 `_err` 前插入 color 分支，並更新錯誤訊息：
```python
    if ctype == "color":
        _check_no_extra(data, "規則 condition",
                        {"type", "hue", "sat", "val", "hue_tol", "sat_tol",
                         "val_tol", "min_pixels", "absent"})
        return RuleCondition(
            type="color",
            hue=_get_int_in(data, "規則 condition", "hue", 0, 179),
            sat=_get_int_in(data, "規則 condition", "sat", 0, 255),
            val=_get_int_in(data, "規則 condition", "val", 0, 255),
            hue_tol=_get_int_in(data, "規則 condition", "hue_tol", 0, 90, default=10),
            sat_tol=_get_int_in(data, "規則 condition", "sat_tol", 0, 255, default=80),
            val_tol=_get_int_in(data, "規則 condition", "val_tol", 0, 255, default=80),
            min_pixels=_get_int_in(data, "規則 condition", "min_pixels", 1, 10_000_000, default=3),
            absent=_get_bool(data, "規則 condition", "absent"))
    _err(f"規則 condition.type 必須是 text、image 或 color: {ctype!r}")
```

3d. `rule_to_dict`（約 `models.py:574`）把 text/image 的 `if/else` 改為三分支：
```python
    if rule.condition.type == "text":
        cond = {"type": "text", "pattern": rule.condition.pattern,
                "mode": rule.condition.mode}
    elif rule.condition.type == "image":
        cond = {"type": "image", "template": rule.condition.template,
                "threshold": rule.condition.threshold}
    else:  # color
        c = rule.condition
        cond = {"type": "color", "hue": c.hue, "sat": c.sat, "val": c.val,
                "hue_tol": c.hue_tol, "sat_tol": c.sat_tol, "val_tol": c.val_tol,
                "min_pixels": c.min_pixels, "absent": c.absent}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_models.py -v`
Expected: PASS（新增 5 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models.py
git commit -m "feat(color): RuleCondition 支援 color 型別（驗證與序列化）"
```

---

### Task 4: 引擎判定 `rule_engine._matches` color 分支

**Files:**
- Modify: `src/keyboard_executor/core/rule_engine.py`
- Test: `tests/core/test_rule_engine.py`（既有檔，新增測試函式）

**Interfaces:**
- Consumes: `vision.count_color_pixels`（Task 2）、`RuleCondition` color 欄位（Task 3）、既有 `RuleEngine`
- Produces: `_matches` 對 `type=="color"` 回 `count >= min_pixels`（`absent=False`）或 `count < min_pixels`（`absent=True`）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_rule_engine.py` 末端新增（沿用檔內既有 `make_platform`、`FakeScreenCapture` from `tests.fakes`、`rule_from_dict`）：
```python
def _color_rule(absent=False, min_pixels=3):
    return rule_from_dict({
        "name": "紅點", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "color", "hue": 0, "sat": 255, "val": 255,
                      "min_pixels": min_pixels, "absent": absent},
        "trigger": {"type": "notify", "message": "有紅點"},
    })


def _red_image():
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)      # BGR 紅
    return img


def test_color_condition_matches_when_red_present():
    from tests.fakes import FakeScreenCapture
    engine = RuleEngine(make_platform(capture=FakeScreenCapture(image=_red_image())),
                        storage=None)
    assert engine._matches(_color_rule()) is True


def test_color_condition_absent_mode_matches_when_no_red():
    from tests.fakes import FakeScreenCapture
    grey = np.full((20, 20, 3), 128, dtype=np.uint8)
    engine = RuleEngine(make_platform(capture=FakeScreenCapture(image=grey)),
                        storage=None)
    assert engine._matches(_color_rule(absent=True)) is True
    # 出現模式在同一灰圖應為 False
    assert engine._matches(_color_rule(absent=False)) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/core/test_rule_engine.py -k color -v`
Expected: FAIL（color 落到 image 分支 → `self._templates(None)` 觸發 `TypeError`／AttributeError）

- [ ] **Step 3: 最小實作**

`rule_engine.py` 檔頭 import 補上 `count_color_pixels`：
```python
from keyboard_executor.core.vision import count_color_pixels, find_text, match_template
```
`_matches`（約 `rule_engine.py:121-125`）在 text 分支後、image（fall-through）前插入 color 分支：
```python
        if rule.condition.type == "text":
            boxes = self._platform.ocr_engine.recognize(image)
            return find_text(boxes, rule.condition.pattern, rule.condition.mode) is not None
        if rule.condition.type == "color":
            c = rule.condition
            count = count_color_pixels(image, c.hue, c.sat, c.val,
                                       c.hue_tol, c.sat_tol, c.val_tol)
            return count < c.min_pixels if c.absent else count >= c.min_pixels
        template = self._templates(rule.condition.template)
        return match_template(image, template, threshold=rule.condition.threshold).found
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/core/test_rule_engine.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/rule_engine.py tests/core/test_rule_engine.py
git commit -m "feat(color): 規則引擎 _matches 支援 color 條件（出現/消失）"
```

---

### Task 5: 滴管取色覆蓋層 `app/color_picker.py`

**Files:**
- Create: `src/keyboard_executor/app/color_picker.py`
- Test: `tests/app/test_color_picker_widget.py`

**Interfaces:**
- Consumes: `region_picker.drag_scale`、`vision.sample_dominant_hsv`（Task 2）
- Produces:
  - `ColorPickerOverlay(capture_factory, parent=None)`，signals `color_picked(int,int,int)`、`cancelled()`。
  - `open_fullscreen()`：擷全螢幕存 `self._shot`（BGR）並顯示。
  - 可測 seam `_pick(x, y)`：從 `self._shot` 取樣並 emit。
  - module 級純函式 `_patch_around(image_bgr, x, y, radius) -> np.ndarray`。

- [ ] **Step 1: 寫失敗測試**

`tests/app/test_color_picker_widget.py`：
```python
import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from keyboard_executor.app.color_picker import ColorPickerOverlay, _patch_around


class FakeCap:
    def __init__(self, image):
        self.image = image

    def capture(self, rect):
        return self.image


def test_patch_around_center_shape():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _patch_around(img, 5, 5, 2).shape == (5, 5, 3)


def test_patch_around_clamps_at_edge():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _patch_around(img, 0, 0, 2).shape == (3, 3, 3)


def test_pick_emits_sampled_hsv(qapp):
    shot = np.full((20, 20, 3), 128, dtype=np.uint8)
    shot[10, 10] = (0, 0, 255)                  # BGR 紅
    overlay = ColorPickerOverlay(lambda: FakeCap(shot))
    overlay._shot = shot                        # 跳過 open_fullscreen 的螢幕依賴
    seen = []
    overlay.color_picked.connect(lambda h, s, v: seen.append((h, s, v)))
    overlay._pick(10, 10)
    assert seen and seen[0][0] == 0 and seen[0][1] == 255


def test_escape_emits_cancelled(qapp):
    overlay = ColorPickerOverlay(lambda: FakeCap(None))
    seen = []
    overlay.cancelled.connect(lambda: seen.append(True))
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(ev)
    assert seen == [True]


def test_overlay_parented(qapp):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    overlay = ColorPickerOverlay(lambda: FakeCap(None), parent)
    assert overlay.parent() is parent
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/app/test_color_picker_widget.py -v`
Expected: FAIL（`ModuleNotFoundError: keyboard_executor.app.color_picker`）

- [ ] **Step 3: 最小實作**

`src/keyboard_executor/app/color_picker.py`：
```python
"""滴管取色覆蓋層：開啟時擷全螢幕當背景，點擊處從截圖陣列取樣目標顏色 HSV。

覆蓋層是頂層視窗、無法讀自身像素；直接對實螢幕擷取又會被遮罩色汙染，故開啟時
先擷一張全螢幕截圖畫為背景（所見即所取），點擊時從那張截圖的 numpy 陣列取樣。
座標邏輯→實體像素沿用 region_picker.drag_scale。以 modal 對話框為 parent 才不被
modal 擋輸入（同 RegionPickerOverlay）。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from keyboard_executor.app.region_picker import drag_scale
from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.vision import sample_dominant_hsv


def _patch_around(image_bgr: np.ndarray, x: int, y: int, radius: int) -> np.ndarray:
    """截圖中 (x, y) 周圍 (2r+1)² patch，超出邊界自動夾住。"""
    h, w = image_bgr.shape[:2]
    cx = max(0, min(x, w - 1))
    cy = max(0, min(y, h - 1))
    return image_bgr[max(0, cy - radius):min(h, cy + radius + 1),
                     max(0, cx - radius):min(w, cx + radius + 1)]


def _bgr_to_qimage(image_bgr: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ColorPickerOverlay(QWidget):
    color_picked = Signal(int, int, int)     # HSV（OpenCV 範圍）
    cancelled = Signal()

    def __init__(self, capture_factory, parent=None):
        super().__init__(parent, Qt.WindowType.Window
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._capture_factory = capture_factory
        self._shot: np.ndarray | None = None
        self._qimage: QImage | None = None

    def open_fullscreen(self) -> None:
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        scale = drag_scale(self.devicePixelRatio())
        rect = Rect(round(geo.x() * scale), round(geo.y() * scale),
                    round(geo.width() * scale), round(geo.height() * scale))
        self._shot = self._capture_factory().capture(rect)
        self._qimage = _bgr_to_qimage(self._shot)
        self.show()
        self.raise_()
        self.activateWindow()

    def _pick(self, x: int, y: int) -> None:
        if self._shot is None:
            return
        scale = drag_scale(self.devicePixelRatio())
        patch = _patch_around(self._shot, round(x * scale), round(y * scale), 2)
        h, s, v = sample_dominant_hsv(patch)
        self.close()
        self.color_picked.emit(h, s, v)

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._pick(int(pos.x()), int(pos.y()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, event) -> None:
        if self._qimage is not None:
            QPainter(self).drawImage(self.rect(), self._qimage)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/app/test_color_picker_widget.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/color_picker.py tests/app/test_color_picker_widget.py
git commit -m "feat(color): 滴管取色覆蓋層 ColorPickerOverlay"
```

---

### Task 6: 表單模型 `rule_editor_model.py` color 欄位

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor_model.py`
- Test: `tests/app/test_rule_editor_model.py`（既有檔，新增測試函式）

**Interfaces:**
- Consumes: `RuleCondition` color（Task 3）
- Produces: `RuleEditorModel` 新增字串欄位 `hue,sat,val,hue_tol,min_pixels` 與 bool `color_absent`；`from_rule`/`to_dict` 支援 color；`condition_type` 可為 `"color"`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_rule_editor_model.py` 末端新增：
```python
from keyboard_executor.app.rule_editor_model import RuleEditorModel


def test_to_dict_builds_color_condition():
    m = RuleEditorModel()
    m.condition_type = "color"
    m.hue, m.sat, m.val = "0", "255", "255"
    m.hue_tol = "15"
    m.min_pixels = "5"
    m.color_absent = True
    cond = m.to_dict()["condition"]
    assert cond == {"type": "color", "hue": 0, "sat": 255, "val": 255,
                    "hue_tol": 15, "min_pixels": 5, "absent": True}


def test_from_rule_reads_color_condition():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict({
        "name": "紅點", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "color", "hue": 3, "sat": 200, "val": 230,
                      "hue_tol": 12, "min_pixels": 4, "absent": True},
        "trigger": {"type": "notify", "message": "有紅點"}})
    m = RuleEditorModel.from_rule(rule)
    assert m.condition_type == "color"
    assert m.hue == "3" and m.min_pixels == "4" and m.color_absent is True


def test_color_model_to_rule_validates():
    m = RuleEditorModel()
    m.name = "紅點"
    m.title_pattern = "遊戲"
    m.condition_type = "color"
    m.hue, m.sat, m.val = "0", "255", "255"
    rule = m.to_rule()                       # 不應拋例外
    assert rule.condition.type == "color"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/app/test_rule_editor_model.py -k color -v`
Expected: FAIL（`AttributeError`／KeyError：color 欄位與分支不存在）

- [ ] **Step 3: 最小實作**

3a. `__init__`（約 `rule_editor_model.py:19`）在 `self.threshold = "0.85"` 後加：
```python
        self.hue = "0"
        self.sat = "0"
        self.val = "0"
        self.hue_tol = "10"
        self.min_pixels = "3"
        self.color_absent = False
```

3b. `from_rule`（約 `rule_editor_model.py:44-48`）在 `model.threshold = ...` 後加：
```python
        if rule.condition.type == "color":
            model.hue = str(rule.condition.hue)
            model.sat = str(rule.condition.sat)
            model.val = str(rule.condition.val)
            model.hue_tol = str(rule.condition.hue_tol)
            model.min_pixels = str(rule.condition.min_pixels)
            model.color_absent = rule.condition.absent
```

3c. 檔頭 `_parse_number` 後新增整數解析器：
```python
def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ScriptValidationError(f"規則欄位 {name} 必須是整數: {raw!r}") from None
```

3d. `to_dict`（約 `rule_editor_model.py:66-72`）把 text/image 的 `if/else` 改為三分支：
```python
        if self.condition_type == "text":
            data["condition"] = {"type": "text", "pattern": self.pattern,
                                 "mode": self.mode}
        elif self.condition_type == "image":
            data["condition"] = {"type": "image", "template": self.template,
                                 "threshold": _parse_number("threshold",
                                                            self.threshold)}
        else:  # color
            data["condition"] = {
                "type": "color",
                "hue": _parse_int("hue", self.hue),
                "sat": _parse_int("sat", self.sat),
                "val": _parse_int("val", self.val),
                "hue_tol": _parse_int("hue_tol", self.hue_tol),
                "min_pixels": _parse_int("min_pixels", self.min_pixels),
                "absent": self.color_absent}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/app/test_rule_editor_model.py -v`
Expected: PASS（新增 3 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor_model.py tests/app/test_rule_editor_model.py
git commit -m "feat(color): RuleEditorModel 支援 color 條件欄位"
```

---

### Task 7: 規則編輯器 UI 接線 `rule_editor.py`

**Files:**
- Modify: `src/keyboard_executor/app/action_fields.py`（`CHOICE_LABELS` 加 "color"）
- Modify: `src/keyboard_executor/app/rule_editor.py`
- Test: `tests/app/test_rule_editor_widget.py`（既有檔，新增測試函式）

**Interfaces:**
- Consumes: `ColorPickerOverlay`（Task 5）、`RuleEditorModel` color 欄位（Task 6）、既有 `self._capture_factory`
- Produces: 條件類型下拉含「顏色」；`_on_pick_color`/`_on_color_picked`；`self._picked_hsv:(int,int,int)`；`detect_combo`（出現/消失）、`hue_tol_edit`、`min_pixels_edit`、`pick_color_button`、`color_value_label`、`color_swatch`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_rule_editor_widget.py` 末端新增：
```python
def test_condition_combo_includes_color(qapp, tmp_path):
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    labels = [dialog.condition_combo.itemText(i)
              for i in range(dialog.condition_combo.count())]
    assert "顏色" in labels


def test_color_pick_updates_swatch_and_state(qapp, tmp_path):
    import numpy as np

    class FakeCap:
        def capture(self, rect):
            img = np.full((10, 10, 3), 128, dtype=np.uint8)
            img[5, 5] = (0, 0, 255)              # BGR 紅
            return img

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              capture_factory=lambda: FakeCap())
    dialog._on_pick_color()
    dialog._overlay._pick(5, 5)
    assert dialog._picked_hsv[0] == 0 and dialog._picked_hsv[1] == 255
    assert "H=0" in dialog.color_value_label.text()


def test_color_condition_saves_via_storage(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage,
                              capture_factory=lambda: None)
    dialog.name_edit.setText("紅點")
    dialog.title_edit.setText("遊戲")
    dialog.condition_combo.setCurrentIndex(
        dialog.condition_combo.findData("color"))
    dialog._picked_hsv = (0, 255, 255)
    dialog.min_pixels_edit.setText("3")
    dialog.detect_combo.setCurrentIndex(dialog.detect_combo.findData(False))
    dialog.trigger_combo.setCurrentIndex(dialog.trigger_combo.findData("notify"))
    dialog.message_edit.setText("有紅點")
    dialog.save_button.click()
    assert "已儲存" in dialog.status_label.text()
    rule = storage.load("紅點")
    assert rule.condition.type == "color"
    assert rule.condition.hue == 0 and rule.condition.min_pixels == 3
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/app/test_rule_editor_widget.py -k color -v`
Expected: FAIL（`AttributeError: 'RuleEditorDialog' object has no attribute '_on_pick_color'` 等）

- [ ] **Step 3: 最小實作**

3a. `action_fields.py` 的 `CHOICE_LABELS`（約 `action_fields.py:87`）在 `"text": "文字", "image": "圖像",` 那行改為：
```python
    "text": "文字", "image": "圖像", "color": "顏色",
```

3b. `rule_editor.py` 匯入區加：
```python
import colorsys
```
並在 `QLabel` 等 import 已足夠（沿用既有 `QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget`）。

3c. `rule_editor.py` 檔案末端（module 級）加色塊 QSS 小工具：
```python
def _swatch_qss(h: int, s: int, v: int) -> str:
    """OpenCV HSV（H 0–179）→ QSS 背景色。"""
    r, g, b = colorsys.hsv_to_rgb(h / 179.0, s / 255.0, v / 255.0)
    return (f"background:rgb({int(r * 255)},{int(g * 255)},{int(b * 255)});"
            " border:1px solid #888;")


def _safe_int(text: str) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0
```

3d. 條件類型下拉（約 `rule_editor.py:82`）加 "color"：
```python
        _fill_choice(self.condition_combo, ["text", "image", "color"],
                     model.condition_type)
```

3e. 在 `threshold_edit` 那一列（約 `rule_editor.py:91-92`）之後、`interval_edit` 之前插入 color 欄位：
```python
        color_row = QHBoxLayout()
        self.pick_color_button = QPushButton("滴管取色…")
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(18, 18)
        self.color_value_label = QLabel("尚未取樣")
        color_row.addWidget(self.pick_color_button)
        color_row.addWidget(self.color_swatch)
        color_row.addWidget(self.color_value_label, 1)
        color_container = QWidget()
        color_container.setLayout(color_row)
        layout.addRow("顏色（滴管）", color_container)
        self.hue_tol_edit = QLineEdit(model.hue_tol)
        layout.addRow("容差（色相）", self.hue_tol_edit)
        self.min_pixels_edit = QLineEdit(model.min_pixels)
        layout.addRow("最少像素", self.min_pixels_edit)
        self.detect_combo = QComboBox()
        self.detect_combo.addItem("出現時", False)
        self.detect_combo.addItem("消失時", True)
        di = self.detect_combo.findData(model.color_absent)
        if di >= 0:
            self.detect_combo.setCurrentIndex(di)
        layout.addRow("偵測", self.detect_combo)
```

3f. 在 `__init__` 尾端（既有 `self._refresh_windows()` 之前或之後）初始化取樣狀態並反映既有值：
```python
        self._picked_hsv = (_safe_int(model.hue), _safe_int(model.sat),
                            _safe_int(model.val))
        if model.condition_type == "color":
            h, s, v = self._picked_hsv
            self.color_value_label.setText(f"H={h} S={s} V={v}")
            self.color_swatch.setStyleSheet(_swatch_qss(h, s, v))
        self.pick_color_button.clicked.connect(self._on_pick_color)
```

3g. `_apply_to_model`（約 `rule_editor.py:159-175`）在設定 condition 相關欄位處補 color：
```python
        h, s, v = self._picked_hsv
        m.hue, m.sat, m.val = str(h), str(s), str(v)
        m.hue_tol = self.hue_tol_edit.text()
        m.min_pixels = self.min_pixels_edit.text()
        m.color_absent = self.detect_combo.currentData()
```

3h. 新增兩個 handler（放在 `_on_capture_template` 附近）：
```python
    def _on_pick_color(self) -> None:
        """開滴管覆蓋層取樣目標顏色。"""
        from keyboard_executor.app.color_picker import ColorPickerOverlay

        overlay = ColorPickerOverlay(self._capture_factory, self)  # 以對話框為 parent
        self._overlay = overlay
        overlay.color_picked.connect(self._on_color_picked)
        overlay.open_fullscreen()

    def _on_color_picked(self, h: int, s: int, v: int) -> None:
        self._picked_hsv = (h, s, v)
        self.color_value_label.setText(f"H={h} S={s} V={v}")
        self.color_swatch.setStyleSheet(_swatch_qss(h, s, v))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/app/test_rule_editor_widget.py -v`
Expected: PASS（新增 3 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/action_fields.py src/keyboard_executor/app/rule_editor.py tests/app/test_rule_editor_widget.py
git commit -m "feat(color): 規則編輯器加顏色條件（滴管取色、容差、出現/消失）"
```

---

### Task 8: 全套件回歸與收尾

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `python -m pytest -q`
Expected: 全數 PASS（既有 547 + 新增約 22 項；容許既有 4 skipped）。若有失敗，回到對應任務修正。

- [ ] **Step 2: Lint（若專案有設定）**

Run: `ruff check src/keyboard_executor/core/color_math.py src/keyboard_executor/core/vision.py src/keyboard_executor/app/color_picker.py src/keyboard_executor/app/rule_editor.py`
Expected: 無錯誤（無 ruff 設定則略過）。

- [ ] **Step 3: 確認行尾為 LF**

Run: `git diff --stat HEAD~7 && file src/keyboard_executor/app/color_picker.py`
Expected: 新檔皆 LF；如有 CRLF 用 `sed -i 's/\r$//' <file>` 正規化後 `git add` 修補。

無新增 commit（純驗證）；如需修正則併入對應任務的 commit 或補一個 `test:`/`fix:` commit。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後，依 `MEMORY.md` 的 Windows build 流程重新打包 exe，於實機做人工驗收：對遊戲視窗設一條 color 規則、框選小地圖區域、滴管點紅點、選「出現時」→ 觸發 notify；再測「消失時」。此步驟在計畫外，由使用者驅動。
