# 規則多動作觸發 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓一條監看規則能同時做多件事——`Rule` 改持有 `triggers`（一組動作），編輯器用勾選框（通知/停止/執行腳本任意組合），引擎依序執行。

**Architecture:** `RuleTrigger`（單一動作）不變；`Rule.trigger` 改為 `Rule.triggers: tuple[RuleTrigger, ...]`，並保留 `trigger` 相容 property（回第一個動作）讓過渡期全套件維持綠燈。序列化接受舊單物件 `"trigger"`（遷移）與新 `"triggers"` 清單。引擎 `_fire` 逐一跑每個動作（沿用 per-type 邏輯）。

**Tech Stack:** Python 3.13 / PySide6（QCheckBox）/ pytest。

## Global Constraints

- `RuleTrigger` 不變；`Rule` 以 `triggers: tuple[RuleTrigger, ...]` 取代 `trigger`，並加 `trigger` property（回 `triggers[0]`，相容/單一動作便利）。
- 序列化：讀時 `"triggers"`（清單）優先，否則 `"trigger"`（舊單物件→包成一元素清單，遷移）；寫時一律 `"triggers"`。至少一個動作。
- 執行順序固定 **notify → run_script → stop_all**（清單由編輯器以此序建立）。
- 面向使用者訊息繁中；沿用現有 per-動作行為（notify 走 GUI+Discord 扇出、stop_all 停執行中腳本）。
- LF 行尾。全程 TDD。每個任務結束跑全套件應綠。
- 測試指令（`python` 不在 PATH）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/core/models.py` | `Rule.triggers` + `trigger` property + 序列化/驗證 | Modify |
| `src/keyboard_executor/core/rule_engine.py` | `_fire` 逐一執行 triggers | Modify |
| `src/keyboard_executor/app/rule_editor_model.py` | 觸發旗標 → triggers 清單 | Modify |
| `src/keyboard_executor/app/rule_editor.py` | 三個勾選框取代 trigger_combo | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

---

### Task 1: 資料模型 `Rule.triggers`（含向後相容遷移）

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`Rule`、`rule_from_dict`、`rule_to_dict`、`_check_no_extra` 允許鍵）
- Test: `tests/core/test_models_rule.py`（既有檔，新增測試）

**Interfaces:**
- Produces: `Rule.triggers: tuple[RuleTrigger, ...]`；`Rule.trigger`（property → `triggers[0]`）；`_trigger_to_dict(trig) -> dict`。`rule_from_dict` 接受 `"triggers"` 清單或舊 `"trigger"` 單物件；`rule_to_dict` 輸出 `"triggers"`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_models_rule.py` 末端新增：
```python
def _rule_dict(**kw):
    base = {"name": "r", "target_window": {"title_pattern": "遊戲"},
            "condition": {"type": "text", "pattern": "x"}}
    base.update(kw)
    return base


def test_rule_triggers_list_round_trip():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    r = rule_from_dict(_rule_dict(triggers=[
        {"type": "notify", "message": "m"}, {"type": "stop_all"}]))
    assert [t.type for t in r.triggers] == ["notify", "stop_all"]
    assert rule_from_dict(rule_to_dict(r)).triggers == r.triggers


def test_rule_old_single_trigger_migrates_to_list():
    from keyboard_executor.core.models import rule_from_dict, rule_to_dict
    r = rule_from_dict(_rule_dict(trigger={"type": "stop_all"}))
    assert len(r.triggers) == 1 and r.triggers[0].type == "stop_all"
    assert r.trigger.type == "stop_all"                         # 相容 property
    assert rule_to_dict(r)["triggers"] == [{"type": "stop_all"}]  # 存檔升級為新格式


def test_rule_empty_triggers_rejected():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError):
        rule_from_dict(_rule_dict(triggers=[]))


def test_rule_missing_triggers_rejected():
    import pytest
    from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
    with pytest.raises(ScriptValidationError, match="triggers"):
        rule_from_dict(_rule_dict())     # 既無 trigger 也無 triggers
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py -k "triggers or migrates" -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'triggers'` 或缺 triggers 支援）

- [ ] **Step 3: 最小實作**

3a. `Rule` dataclass（約 `models.py:519-528`）改 `trigger` 欄位為 `triggers` 並加相容 property：
```python
@dataclass(frozen=True)
class Rule:
    name: str
    target_window: TargetWindow
    condition: RuleCondition
    triggers: tuple[RuleTrigger, ...]
    region: list[int] | None = None
    interval_sec: float = 5.0
    cooldown_sec: float = 60.0
    enabled: bool = True

    @property
    def trigger(self) -> RuleTrigger:
        """相容便利：回第一個觸發動作（單一動作規則等同舊 trigger）。"""
        return self.triggers[0]
```

3b. 在 `_validate_rule_trigger`（約 `models.py:585`）之後新增序列化 helper：
```python
def _trigger_to_dict(trig: RuleTrigger) -> dict:
    d: dict[str, Any] = {"type": trig.type}
    if trig.type == "run_script":
        d["script_name"] = trig.script_name
    elif trig.type == "notify":
        d["message"] = trig.message
    return d
```

3c. `rule_from_dict`：`_check_no_extra` 允許鍵加入 `"triggers"`；把單一 trigger 解析改為清單/遷移：
```python
    _check_no_extra(data, "規則", {"name", "target_window", "region", "condition",
                                   "interval_sec", "cooldown_sec", "trigger",
                                   "triggers", "enabled"})
```
把原本
```python
    if "trigger" not in data:
        _err("規則缺少欄位 trigger")
    trigger = _validate_rule_trigger(data["trigger"])
```
改為
```python
    if "triggers" in data:
        raw = data["triggers"]
        if not isinstance(raw, list) or not raw:
            _err("規則欄位 triggers 必須是至少一個動作的清單")
        triggers = tuple(_validate_rule_trigger(t) for t in raw)
    elif "trigger" in data:
        triggers = (_validate_rule_trigger(data["trigger"]),)   # 舊格式遷移
    else:
        _err("規則缺少欄位 triggers")
```
並把最後的 `return Rule(... trigger=trigger ...)` 改為 `return Rule(... triggers=triggers ...)`。

3d. `rule_to_dict`：把原本組 `trig` 的區塊（約 `models.py:627-631`）刪掉，回傳字典裡改用 `"triggers"`：
```python
        "condition": cond,
        "triggers": [_trigger_to_dict(t) for t in rule.triggers],
        "interval_sec": rule.interval_sec,
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_rule.py tests/core/test_rule_engine.py tests/app/test_rule_editor_model.py -v`
Expected: PASS（新增 4 項與既有全數——既有 `r.trigger.type`、`rule_engine`、`rule_editor_model` 皆經 `trigger` property／舊 `"trigger"` 遷移續過）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_rule.py
git commit -m "feat(rule): Rule 改持有 triggers 清單（舊 trigger 自動遷移，含相容 property）"
```

---

### Task 2: 引擎 `_fire` 逐一執行 triggers

**Files:**
- Modify: `src/keyboard_executor/core/rule_engine.py`（`_fire`）
- Test: `tests/core/test_rule_engine.py`（既有檔，新增測試）

**Interfaces:**
- Consumes: `Rule.triggers`（Task 1）
- Produces: `_fire(rule)` 依序對每個動作呼叫 `_fire_one(rule, trig)`；`on_fire` 傳 `"+".join(t.type for t in rule.triggers)`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/core/test_rule_engine.py` 末端新增（沿用檔內 `make_platform`、`FakeScreenCapture`、`FakeOcrEngine`、`tbox`、`rule_from_dict`、`Clock`、`DictStorage`）：
```python
def test_multi_trigger_fires_notify_and_stop_all():
    import threading
    stop = threading.Event()
    notified = []
    called = []
    engine = RuleEngine(
        make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), stop_event=stop, clock=Clock(),
        notifier=notified.append, on_stop_all=lambda: called.append(True))
    rule = rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "有事"}, {"type": "stop_all"}]})
    engine.evaluate_once([rule])
    assert notified == ["有事"]        # 通知動作有跑
    assert stop.is_set()               # 停止動作有跑
    assert called == [True]            # 連執行中腳本一併停（on_stop_all）
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py -k multi_trigger -v`
Expected: FAIL（現況 `_fire` 只跑第一個動作：只有 notify 或只有 stop，斷言不全成立）

- [ ] **Step 3: 最小實作**

`rule_engine.py` 的 `_fire`（約 `:134`）改為迴圈，並把原本 per-type 主體抽成 `_fire_one`：
```python
    def _fire(self, rule: Rule) -> None:
        if self._on_fire is not None:
            self._on_fire(rule.name, "+".join(t.type for t in rule.triggers))
        for trig in rule.triggers:
            self._fire_one(rule, trig)

    def _fire_one(self, rule, trig) -> None:
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
            self._notifier(trig.message)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_rule_engine.py tests/app/test_watch_controller.py -v`
Expected: PASS（新增 1 項與既有全數——單一動作規則 `"+".join` 為單一字串如 `"notify"`，既有 on_fire/progress 測試不變）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/rule_engine.py tests/core/test_rule_engine.py
git commit -m "feat(rule): 引擎逐一執行 triggers，支援多動作觸發"
```

---

### Task 3: 編輯模型 `rule_editor_model` 觸發旗標

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor_model.py`
- Test: `tests/app/test_rule_editor_model.py`（既有檔，改既有觸發測試 + 新增）

**Interfaces:**
- Consumes: `Rule.triggers`（Task 1）
- Produces: `RuleEditorModel` 以 `notify_enabled`/`stop_all_enabled`/`run_script_enabled`（bool）+ 既有 `message`/`script_name` 表示觸發；`to_dict` 產生 `"triggers"` 清單（順序 notify、run_script、stop_all）；`from_rule` 由 `rule.triggers` 還原旗標。

- [ ] **Step 1: 改既有測試 + 寫新測試**

在 `tests/app/test_rule_editor_model.py`：把用到 `model.trigger_type` 的既有測試改用旗標（例：`model.trigger_type = "notify"` → `model.notify_enabled = True`；`= "stop_all"` → `model.stop_all_enabled = True`、`model.notify_enabled = False`；`= "run_script"` → `model.run_script_enabled = True`、`model.notify_enabled = False`）。第 24 行 `assert model.trigger_type == "run_script"` 改為 `assert model.run_script_enabled and model.script_name == "重連流程"`。
並在末端新增：
```python
def test_to_dict_builds_triggers_in_fixed_order():
    m = RuleEditorModel()
    m.notify_enabled = True
    m.message = "有事"
    m.stop_all_enabled = True
    m.run_script_enabled = False
    assert m.to_dict()["triggers"] == [
        {"type": "notify", "message": "有事"}, {"type": "stop_all"}]


def test_from_rule_reads_multiple_triggers():
    from keyboard_executor.core.models import rule_from_dict
    rule = rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "x"},
        "triggers": [{"type": "notify", "message": "m"}, {"type": "stop_all"}]})
    model = RuleEditorModel.from_rule(rule)
    assert model.notify_enabled and model.stop_all_enabled
    assert not model.run_script_enabled and model.message == "m"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py -v`
Expected: FAIL（`AttributeError: 'RuleEditorModel' object has no attribute 'notify_enabled'`）

- [ ] **Step 3: 最小實作**

3a. `__init__`（約 `rule_editor_model.py:47`）把 `self.trigger_type = "notify"` 換成旗標：
```python
        self.notify_enabled = True       # 新規則預設「顯示通知」
        self.stop_all_enabled = False
        self.run_script_enabled = False
        self.script_name = ""
        self.message = ""
```

3b. `from_rule`（約 `:75-77`）把 `model.trigger_type = ...` 三行換成：
```python
        model.notify_enabled = any(t.type == "notify" for t in rule.triggers)
        model.stop_all_enabled = any(t.type == "stop_all" for t in rule.triggers)
        model.run_script_enabled = any(t.type == "run_script" for t in rule.triggers)
        for t in rule.triggers:
            if t.type == "notify":
                model.message = t.message or ""
            elif t.type == "run_script":
                model.script_name = t.script_name or ""
```

3c. `to_dict`（約 `:108-113`）把 `if self.trigger_type == ...` 區塊換成依旗標建清單：
```python
        triggers = []
        if self.notify_enabled:
            triggers.append({"type": "notify", "message": self.message})
        if self.run_script_enabled:
            triggers.append({"type": "run_script", "script_name": self.script_name})
        if self.stop_all_enabled:
            triggers.append({"type": "stop_all"})
        data["triggers"] = triggers      # 空清單 → rule_from_dict 拒絕（存檔會顯示錯誤）
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_model.py -v`
Expected: PASS（改過的既有 + 新增 2 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor_model.py tests/app/test_rule_editor_model.py
git commit -m "feat(rule-editor): 編輯模型改用觸發旗標，to_dict 產生 triggers 清單"
```

---

### Task 4: 規則編輯器 UI 三個勾選框

**Files:**
- Modify: `src/keyboard_executor/app/rule_editor.py`
- Test: `tests/app/test_rule_editor_widget.py`（既有檔，改既有 trigger_combo 用法 + 新增）

**Interfaces:**
- Consumes: `RuleEditorModel` 旗標（Task 3）
- Produces: `RuleEditorDialog.notify_check`/`stop_all_check`/`run_script_check`（QCheckBox）取代 `trigger_combo`；`_apply_to_model` 由勾選框設旗標。

- [ ] **Step 1: 改既有測試 + 寫新測試**

在 `tests/app/test_rule_editor_widget.py`：把用到 `dialog.trigger_combo.setCurrentIndex(dialog.trigger_combo.findData("notify"))` 的 5 處（行 24, 60, 174, 283, 296）改為對應勾選框：`"notify"` → `dialog.notify_check.setChecked(True)`；`"run_script"` → `dialog.run_script_check.setChecked(True)`（並視需要 `dialog.notify_check.setChecked(False)`）。
並在末端新增：
```python
def test_rule_editor_saves_multiple_trigger_actions(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("多")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("有事")
    dialog.stop_all_check.setChecked(True)
    dialog.save_button.click()
    rule = storage.load("多")
    assert [t.type for t in rule.triggers] == ["notify", "stop_all"]


def test_rule_editor_loads_existing_multi_trigger_checked(qapp, tmp_path):
    from keyboard_executor.core.models import rule_from_dict
    storage = RuleStorage(tmp_path)
    storage.save(rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "m"}, {"type": "stop_all"}]}))
    dialog = RuleEditorDialog(RuleEditorModel.from_rule(storage.load("多")), storage)
    assert dialog.notify_check.isChecked() and dialog.stop_all_check.isChecked()
    assert not dialog.run_script_check.isChecked()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_widget.py -k "multiple_trigger or multi_trigger" -v`
Expected: FAIL（`AttributeError: … has no attribute 'notify_check'`）

- [ ] **Step 3: 最小實作**

3a. `rule_editor.py` 匯入區確認有 `QCheckBox`（若無則於既有 `from PySide6.QtWidgets import (...)` 加入）。

3b. 把 `trigger_combo` 那三行（約 `:127-130`）換成三個勾選框：
```python
        from PySide6.QtWidgets import QVBoxLayout
        self.notify_check = QCheckBox("顯示通知")
        self.notify_check.setChecked(model.notify_enabled)
        self.stop_all_check = QCheckBox("全部停止")
        self.stop_all_check.setChecked(model.stop_all_enabled)
        self.run_script_check = QCheckBox("執行腳本")
        self.run_script_check.setChecked(model.run_script_enabled)
        trig_box = QVBoxLayout()
        trig_box.addWidget(self.notify_check)
        trig_box.addWidget(self.stop_all_check)
        trig_box.addWidget(self.run_script_check)
        trig_container = QWidget()
        trig_container.setLayout(trig_box)
        layout.addRow("觸發動作", trig_container)
```
（`message_edit`／`script_edit` 的建立與列維持不變，仍在其後。）

3c. `_apply_to_model`（約 `:234`）把 `m.trigger_type = self.trigger_combo.currentData()` 換成：
```python
        m.notify_enabled = self.notify_check.isChecked()
        m.stop_all_enabled = self.stop_all_check.isChecked()
        m.run_script_enabled = self.run_script_check.isChecked()
```
（`m.script_name`／`m.message` 兩行維持不變。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_rule_editor_widget.py -v`
Expected: PASS（改過的既有 + 新增 2 項）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/rule_editor.py tests/app/test_rule_editor_widget.py
git commit -m "feat(rule-editor): 觸發動作改用三個勾選框（通知/停止/執行腳本可組合）"
```

---

### Task 5: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 + 新增約 9 項；容許既有 4 skipped）。既有以 `"trigger": {…}` 建規則的測試經遷移續過；讀 `rule.trigger` 者經 property 續過。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~4); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重新打包 exe（重打包前先 `taskkill /IM KeyboardExecutor.exe /F /T`）。實機驗收：規則編輯器勾「顯示通知 + 全部停止」→ 觸發時應同時收到通知並停掉所有自動化；載入既有舊規則應正常顯示對應勾選。此步驟在計畫外，由使用者驅動。
