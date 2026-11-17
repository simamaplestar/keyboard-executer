# 「出現時／消失時」泛化到所有條件類型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓「文字」「圖像」條件也能選「出現時／消失時」（沿用既有共用旗標 `RuleCondition.absent`），不再是顏色專屬。

**Architecture:** `RuleCondition.absent` 已是共用欄位；只需在文字／圖像也驗證＋序列化，引擎以 `matched = present != absent` 統一判定，編輯器把 `color_absent` 泛化為 `absent` 且「偵測」下拉三種條件都顯示。顏色條件行為完全不變。

**Tech Stack:** Python 3.13 / PySide6 / OpenCV / PaddleOCR / pytest。

## Global Constraints

- 沿用既有共用欄位 `RuleCondition.absent`（**不新增欄位**）。
- `absent` 缺鍵預設 `False`（出現時），向後相容；非布林 → `_get_bool` 既有繁中訊息拒絕。
- 判定統一為 `matched = present != condition.absent`（`present` = 找到文字／模板命中／顏色像素 ≥ 最少像素）。
- **顏色條件的行為與序列化維持現況不變。**
- 「出現時／消失時」UI 文案沿用（對三種條件皆通順）。
- 面向使用者訊息維持繁中。LF 行尾。全程 TDD。
- 測試指令（`python` 不在 PATH，Qt 需 offscreen）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/core/models.py` | 文字／圖像 condition 驗證＋序列化 `absent` | Modify |
| `src/keyboard_executor/core/rule_engine.py` | 文字／圖像 `present != absent` | Modify |
| `src/keyboard_executor/app/rule_editor_model.py` | `color_absent` 泛化為 `absent`（所有類型） | Modify |
| `src/keyboard_executor/app/rule_editor.py` | 「偵測」下拉三種條件都顯示、讀寫 `model.absent` | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

執行順序 **Task 1 → 3**：Task 3（編輯器 to_dict 會對文字／圖像輸出 `absent`）依賴 Task 1（`rule_from_dict` 接受該鍵）。Task 3 把 `rule_editor_model.py` 與 `rule_editor.py` 一起改（`color_absent`→`absent` 更名跨這兩檔，合併為一個任務以維持每個任務可獨立通過測試）。

---

### Task 1: models.py — 文字／圖像 condition 驗證＋序列化 `absent`

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`_validate_rule_condition` 文字 551-554、圖像 555-558；`rule_to_dict` 文字 637-639、圖像 640-642）
- Test: `tests/core/test_models_rule.py`

**Interfaces:**
- Produces: 文字／圖像 condition dict 接受並輸出 `"absent": bool`（缺鍵預設 `False`）。`RuleCondition.absent` 欄位已存在，不改資料類別。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_models_rule.py` 末端新增：
```python
def test_text_condition_absent_defaults_false():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains"},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is False


def test_text_condition_absent_round_trips():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains", "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is True
    assert rule_to_dict(rule)["condition"]["absent"] is True
    assert rule_from_dict(rule_to_dict(rule)).condition.absent is True


def test_image_condition_absent_round_trips():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "image", "template": "t", "threshold": 0.9, "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert rule.condition.absent is True
    assert rule_to_dict(rule)["condition"]["absent"] is True
    assert rule_from_dict(rule_to_dict(rule)).condition.absent is True


def test_text_condition_rejects_non_bool_absent():
    with pytest.raises(ScriptValidationError):
        rule_from_dict({
            "name": "r", "target_window": {"title_pattern": "x"},
            "condition": {"type": "text", "pattern": "p", "absent": "yes"},
            "triggers": [{"type": "notify", "message": "m"}]})
```
（`pytest`、`rule_from_dict`、`rule_to_dict`、`ScriptValidationError` 皆已於檔頭 import。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py -k "condition_absent or non_bool_absent" -v`
Expected: FAIL（文字／圖像的 `_check_no_extra` 目前不允許 `absent` → 拒絕多餘鍵；且 `rule_to_dict` 未輸出）

- [ ] **Step 3: 最小實作**

`models.py` 的 `_validate_rule_condition`，把文字與圖像分支改為（加入 `"absent"` 允許鍵與 `_get_bool` 讀取）：
```python
    if ctype == "text":
        _check_no_extra(data, "規則 condition", {"type", "pattern", "mode", "absent"})
        return RuleCondition(type="text", pattern=_get_str(data, "規則 condition", "pattern"),
                             mode=_get_mode(data, "規則 condition"),
                             absent=_get_bool(data, "規則 condition", "absent"))
    if ctype == "image":
        _check_no_extra(data, "規則 condition", {"type", "template", "threshold", "absent"})
        return RuleCondition(type="image", template=_get_str(data, "規則 condition", "template"),
                             threshold=_get_threshold(data, "規則 condition"),
                             absent=_get_bool(data, "規則 condition", "absent"))
```
（顏色分支不動。）

`rule_to_dict`，把文字與圖像的 cond dict 各加一鍵 `"absent"`：
```python
    if rule.condition.type == "text":
        cond = {"type": "text", "pattern": rule.condition.pattern,
                "mode": rule.condition.mode, "absent": rule.condition.absent}
    elif rule.condition.type == "image":
        cond = {"type": "image", "template": rule.condition.template,
                "threshold": rule.condition.threshold, "absent": rule.condition.absent}
```
（顏色分支不動。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py -v`
Expected: PASS（新增 4 項與既有全數；既有文字／圖像 round-trip 測試因兩側都 `absent=False` 仍相等）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_rule.py
git commit -m "feat(rule): 文字/圖像 condition 也讀寫 absent（缺鍵預設 False）"
```

---

### Task 2: rule_engine.py — 文字／圖像 `present != absent`

**Files:**
- Modify: `src/keyboard_executor/core/rule_engine.py`（`_matches` 文字分支 126-129、圖像分支 136-138）
- Test: `tests/core/test_rule_engine.py`（helper `make_platform`/`tbox`/`Clock`/`DictStorage`/`FakeScreenCapture`/`FakeOcrEngine`；`import numpy as np`、`rule_from_dict` 已在檔頭）

**Interfaces:**
- Consumes: `RuleCondition.absent`（Task 1 已可由 dict 帶入；欄位本就存在）。
- Produces: 文字／圖像分支回 `(present != rule.condition.absent, image)`。顏色分支不變。

**注意**：`_matches` 目前回傳 `(matched, image)`（前一個功能已改）。本任務只改文字與圖像分支的布林運算，仍回 tuple。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_rule_engine.py` 末端新增：
```python
def test_text_absent_fires_when_text_missing():
    # 消失時（absent=True）：畫面找不到符合文字才觸發
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("一切正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    rule = rule_from_dict({
        "name": "文字消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷", "absent": True},
        "triggers": [{"type": "notify", "message": "沒斷線"}]})
    engine.evaluate_once([rule])
    assert notes == ["沒斷線"]


def test_text_absent_does_not_fire_when_text_present():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    rule = rule_from_dict({
        "name": "文字消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷", "absent": True},
        "triggers": [{"type": "notify", "message": "沒斷線"}]})
    engine.evaluate_once([rule])
    assert notes == []


def _img_scene(with_template):
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    tpl[2:6, 3:9] = (0, 0, 255)     # 內含紅色方塊，具辨識特徵
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    if with_template:
        scene[10:20, 20:32] = tpl   # 命中
    return tpl, scene


def test_image_absent_fires_when_template_missing():
    # 消失時（absent=True）：模板未命中才觸發
    tpl, scene = _img_scene(with_template=False)
    notes = []
    rule = rule_from_dict({
        "name": "圖消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠", "absent": True},
        "triggers": [{"type": "notify", "message": "圖不見了"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == ["圖不見了"]


def test_image_absent_does_not_fire_when_template_present():
    tpl, scene = _img_scene(with_template=True)
    notes = []
    rule = rule_from_dict({
        "name": "圖消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠", "absent": True},
        "triggers": [{"type": "notify", "message": "圖不見了"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py -k "absent_fires or absent_does_not_fire" -v`
Expected: FAIL（目前文字／圖像分支忽略 `absent`：文字恆用「找到才 matched」、圖像恆用 `.found`，故 `absent=True` 的消失時測試不觸發／出現時測試誤觸發）

- [ ] **Step 3: 最小實作**

`rule_engine.py` 的 `_matches`，文字分支改為：
```python
        if rule.condition.type == "text":
            boxes = self._platform.ocr_engine.recognize(image)
            present = find_text(boxes, rule.condition.pattern,
                                rule.condition.mode) is not None
            return present != rule.condition.absent, image
```
圖像分支（方法末端）改為：
```python
        template = self._templates(rule.condition.template)
        present = match_template(image, template,
                                 threshold=rule.condition.threshold).found
        return present != rule.condition.absent, image
```
（顏色分支不動——其 `count < min if absent else count >= min` 語意等同 `present != absent`。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py -v`
Expected: PASS（新增 4 項與既有全數；既有文字／圖像測試 `absent=False`，`present != False == present`，行為不變）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/rule_engine.py tests/core/test_rule_engine.py
git commit -m "feat(rule-engine): 文字/圖像條件依 absent 反轉（出現時/消失時）"
```

---

### Task 3: 編輯器 — `color_absent` 泛化為 `absent`、偵測下拉三種條件都顯示

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor_model.py`（`__init__` 44、`from_rule` 75、`to_dict` 97-114）
- Modify: `src/keyboard_executor/app/rule_editor.py`（`detect_combo` 初始化 118、`_update_condition_fields` 191-193、`_apply_to_model` 244）
- Test: `tests/app/test_rule_editor_model.py`、`tests/app/test_rule_editor_widget.py`

**Interfaces:**
- Consumes: `RuleCondition.absent`（Task 1）；`rule_from_dict` 接受文字／圖像 `absent`（Task 1）。
- Produces: `RuleEditorModel.absent`（取代 `color_absent`）；`to_dict` 三種條件都帶 `absent`；`RuleEditorDialog.detect_combo` 於所有條件類型可見、讀寫 `model.absent`。

**注意（更名跨兩檔，須同一任務完成以維持測試綠燈）**：`color_absent` 更名為 `absent` 會同時影響 `rule_editor_model.py` 與 `rule_editor.py`（後者 118、244 行引用）。務必兩檔一起改。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_rule_editor_model.py` 末端新增：
```python
def test_text_absent_serializes_to_condition():
    model = RuleEditorModel()
    model.name = "r"
    model.title_pattern = "x"
    model.condition_type = "text"
    model.pattern = "p"
    model.notify_enabled = True
    model.message = "m"
    model.absent = True
    assert model.to_dict()["condition"]["absent"] is True


def test_from_rule_restores_absent_for_text():
    rule = rule_from_dict({
        "name": "r", "target_window": {"title_pattern": "x"},
        "condition": {"type": "text", "pattern": "p", "mode": "contains", "absent": True},
        "triggers": [{"type": "notify", "message": "m"}]})
    assert RuleEditorModel.from_rule(rule).absent is True
```

在 `tests/app/test_rule_editor_widget.py` 末端新增：
```python
def test_detect_combo_visible_for_text_condition(qapp, tmp_path):
    model = RuleEditorModel()
    model.condition_type = "text"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path))
    assert dialog.detect_combo.isVisibleTo(dialog)   # 文字條件也顯示「偵測」


def test_detect_combo_saves_absent_for_text_rule(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    model = RuleEditorModel()
    model.condition_type = "text"
    dialog = RuleEditorDialog(model, storage)
    dialog.name_edit.setText("文字消失規則")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("沒斷線")
    di = dialog.detect_combo.findData(True)          # 選「消失時」
    dialog.detect_combo.setCurrentIndex(di)
    dialog.save_button.click()
    assert storage.load("文字消失規則").condition.absent is True
```
（`RuleEditorDialog`、`RuleEditorModel`、`RuleStorage`、`rule_from_dict` 依各測試檔既有 import；`test_rule_editor_model.py` 已 import `rule_from_dict`。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py -k "absent or detect_combo" -v`
Expected: FAIL（`RuleEditorModel` 無 `absent` 屬性；文字 `to_dict` 未帶 `absent`；`detect_combo` 於文字條件被隱藏）

- [ ] **Step 3: 最小實作**

3a. `rule_editor_model.py` 的 `__init__`，把 `self.color_absent = False`（44 行）改為：
```python
        self.absent = False
```

3b. `from_rule`，把顏色區塊內的 `model.color_absent = rule.condition.absent`（75 行）**移出** `if rule.condition.type == "color":` 區塊，改為對所有類型設定——放在 `model.enabled = rule.enabled` 之前：
```python
        model.absent = rule.condition.absent
        model.enabled = rule.enabled
```
（原本顏色區塊內那行刪除。）

3c. `to_dict`：
- 文字分支（97-99 行）改為帶 `absent`：
```python
        if self.condition_type == "text":
            data["condition"] = {"type": "text", "pattern": self.pattern,
                                 "mode": self.mode, "absent": self.absent}
```
- 圖像分支（100-103 行）改為帶 `absent`：
```python
        elif self.condition_type == "image":
            data["condition"] = {"type": "image", "template": self.template,
                                 "threshold": _parse_number("threshold", self.threshold),
                                 "absent": self.absent}
```
- 顏色分支的 `"absent": self.color_absent`（114 行）改為 `"absent": self.absent`。

3d. `rule_editor.py` 的 `detect_combo` 初始化（118 行）`findData(model.color_absent)` 改為：
```python
        di = self.detect_combo.findData(model.absent)
```

3e. `rule_editor.py` 的 `_update_condition_fields`（191-193 行），把 `self.detect_combo` 從顏色專屬群組移除——改為：
```python
        for w in (self._color_container, self.hue_tol_edit, self.min_pixels_edit):
            self._form.setRowVisible(w, ctype == "color")
        self._form.setRowVisible(self.detect_combo, True)   # 三種條件都顯示「偵測」
```

3f. `rule_editor.py` 的 `_apply_to_model`（244 行）`m.color_absent = ...` 改為：
```python
        m.absent = self.detect_combo.currentData()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py -v`
Expected: PASS（新增 4 項與既有全數；既有顏色規則測試因 `color_absent`→`absent` 更名一致而續過）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor_model.py src/keyboard_executor/app/rule_editor.py tests/app/test_rule_editor_model.py tests/app/test_rule_editor_widget.py
git commit -m "feat(rule-editor): 出現時/消失時泛化到文字/圖像（color_absent 更名 absent）"
```

---

### Task 4: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 646 + 新增約 10 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~3); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後連同先前累積的改動一起重新打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留程序，避免 cv2.pyd 鎖檔）。實機驗收：建一條文字規則、把「偵測」選「消失時」，當畫面上該文字不存在時應觸發通知；圖像條件同理。此步驟在計畫外，由使用者驅動。
