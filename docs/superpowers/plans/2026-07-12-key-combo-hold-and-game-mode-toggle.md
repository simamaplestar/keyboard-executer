# 組合鍵 hold + 遊戲模式預設開 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓組合鍵在遊戲裡有效——`key_combo` 按下後停留 40ms 再放（輪詢式遊戲抓得到），並把「遊戲模式」接到腳本編輯器且預設開啟（一律用 DirectInput scan code，仍可每腳本關閉）。

**Architecture:** 兩個輸入後端的 `key_combo` 在 press-all 與 release-all 之間插入 `_sleep(_COMBO_HOLD)`；`ScriptSettings.game_input_mode` 預設改 `True`；`ScriptEditorModel` 加 `game_input_mode` 存取器且新腳本預設 True；`ScriptEditorDialog` 加「遊戲模式」勾選框、`_on_save` 寫入。

**Tech Stack:** Python 3.13 / PySide6 / pynput / pydirectinput / pytest。

## Global Constraints

- `_COMBO_HOLD = 0.04`（秒）定義於 `input_pynput.py`，`win32/input.py` 引用；兩後端 `key_combo` 都在 press-all 後、release-all 前呼叫 `self._sleep(_COMBO_HOLD)`。
- 「一律都用遊戲模式」：`game_input_mode` 預設 `True`（新腳本、舊腳本檔缺鍵、CLI 皆遊戲模式）；勾選框仍可關特定腳本；明確存 `false` 的腳本尊重其值。
- 面向使用者訊息維持繁中。LF 行尾。全程 TDD。`game_input_mode` 只是換輸入 API，非反偵測。
- 測試指令（`python` 不在 PATH，Qt 需 offscreen）：
  `QT_QPA_PLATFORM=offscreen python.exe -m pytest <paths> -v`

---

## File Structure

| 檔案 | 責任 | 動作 |
|------|------|------|
| `src/keyboard_executor/platforms/common/input_pynput.py` | `_COMBO_HOLD` 常數 + pynput `key_combo` 加 hold | Modify |
| `src/keyboard_executor/platforms/win32/input.py` | game mode `key_combo` 加 hold | Modify |
| `src/keyboard_executor/core/models.py` | `ScriptSettings.game_input_mode` 預設 `True` | Modify |
| `src/keyboard_executor/app/script_editor_model.py` | `game_input_mode` 存取器 + 新腳本預設 True | Modify |
| `src/keyboard_executor/app/script_editor.py` | 「遊戲模式」勾選框 + `_on_save` 寫入 | Modify |
| 對應 `tests/…` | 各層測試 | Modify |

執行順序 **Task 1→5**：Task 4 依賴 Task 3（`game_input_mode` property）；其餘大致獨立。

---

### Task 1: `key_combo` 加 hold（兩後端）

**Files:**
- Modify: `src/keyboard_executor/platforms/common/input_pynput.py`（常數 + `key_combo`）
- Modify: `src/keyboard_executor/platforms/win32/input.py`（import + `key_combo`）
- Test: `tests/platforms/test_input_pynput.py`、`tests/platforms/test_win32_input.py`

**Interfaces:**
- Produces: `_COMBO_HOLD = 0.04`（`input_pynput.py` 模組層）；兩後端 `key_combo` 於 press/keyDown 全部後、release/keyUp 全部前呼叫 `self._sleep(_COMBO_HOLD)`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/platforms/test_input_pynput.py` 末端新增（沿用檔內 `make_backend`，其回傳 `(backend, kb, mouse, sleeps)`，`sleeps` 記錄 `_sleep` 呼叫）：
```python
def test_key_combo_holds_before_release():
    backend, _kb, _mouse, sleeps = make_backend()
    backend.key_combo(["ctrl", "s"])
    assert sleeps == [0.04]        # 按下全部後停留 40ms 再放，讓輪詢式遊戲抓得到
```
在 `tests/platforms/test_win32_input.py` 末端新增（沿用 `make_game_backend`，回傳 `(backend, pdi, kb, mouse, sleeps)`）：
```python
def test_game_mode_key_combo_holds_before_release():
    backend, _pdi, _kb, _mouse, sleeps = make_game_backend()
    backend.key_combo(["ctrl", "c"])
    assert sleeps == [0.04]        # keyDown 全部後停留再 keyUp
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py -k "combo_holds" -v`
Expected: FAIL（目前 `key_combo` 無 sleep → `sleeps == []`）

- [ ] **Step 3: 最小實作**

`input_pynput.py`：在 `_SETTLE = 0.05` 之後加常數：
```python
_SETTLE = 0.05
# 組合鍵按下後停留再放開的時間（秒）：0ms 會被輪詢式讀鍵（DirectInput/GetAsyncKeyState）
# 的遊戲在兩次輪詢間漏掉「修飾鍵＋主鍵同時按下」。40ms 跨得過至少 2 個 frame。
_COMBO_HOLD = 0.04
```
把 `key_combo` 改為：
```python
    def key_combo(self, keys: list[str]) -> None:
        parsed = [parse_key(k) for k in keys]
        for k in parsed:
            self._kb.press(k)
        self._sleep(_COMBO_HOLD)
        for k in reversed(parsed):
            self._kb.release(k)
```

`win32/input.py`：檔頭 import 加入 `_COMBO_HOLD`：
```python
from keyboard_executor.platforms.common.input_pynput import _COMBO_HOLD, _SETTLE, PynputInputBackend
```
把 game mode `key_combo` 改為：
```python
    def key_combo(self, keys: list[str]) -> None:
        if self._pdi is None:
            return super().key_combo(keys)
        for k in keys:
            self._pdi.keyDown(k)
        self._sleep(_COMBO_HOLD)
        for k in reversed(keys):
            self._pdi.keyUp(k)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py -v`
Expected: PASS（新增 2 項與既有全數；既有 `test_key_combo_releases_in_reverse_order` / `test_game_mode_key_combo_releases_in_reverse` 只斷言 press/release ops、不含 sleep，故續過）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/common/input_pynput.py src/keyboard_executor/platforms/win32/input.py tests/platforms/test_input_pynput.py tests/platforms/test_win32_input.py
git commit -m "fix(input): key_combo 按下後停留 40ms 再放，輪詢式遊戲抓得到組合鍵"
```

---

### Task 2: `ScriptSettings.game_input_mode` 預設改 `True`

**Files:**
- Modify: `src/keyboard_executor/core/models.py`（`ScriptSettings` 欄位預設）
- Test: `tests/core/test_models_script.py`

**Interfaces:**
- Produces: `ScriptSettings().game_input_mode == True`；`script_from_dict` 缺 `game_input_mode` → `True`；明確 `false` → `False`。

- [ ] **Step 1: 寫失敗測試**

改 `tests/core/test_models_script.py` 既有斷言（約 29 行）：`assert s.settings.game_input_mode is False` → `assert s.settings.game_input_mode is True`。並在檔末新增明確關閉仍尊重的測試：
```python
def test_game_input_mode_explicit_false_respected():
    data = minimal()
    data["settings"] = {"game_input_mode": False}
    assert script_from_dict(data).settings.game_input_mode is False
```
（`minimal()`、`script_from_dict` 為檔內既有 helper／import。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/core/test_models_script.py -k "defaults or explicit_false" -v`
Expected: FAIL（預設仍 False：`test_minimal_script_with_defaults` 斷言 True 失敗）

- [ ] **Step 3: 最小實作**

`models.py` 的 `ScriptSettings`（約 394 行）：
```python
    game_input_mode: bool = True
```
（`script_from_dict` 讀 `data.get("game_input_mode", defaults.game_input_mode)`，`defaults` 為 `ScriptSettings()`，故缺鍵帶入 `True`；明確 `False` 尊重——不需改 `script_from_dict`。）

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全套件 PASS。若有其他測試斷言 `game_input_mode` 預設 `False`（非明確設定者），一併更新為 `True`（`test_run_controller.py` 用的是明確 `{"game_input_mode": True}`，不受影響）。

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/core/models.py tests/core/test_models_script.py
git commit -m "feat(models): game_input_mode 預設改 True（一律遊戲模式，可每腳本關閉）"
```

---

### Task 3: `ScriptEditorModel` 加 `game_input_mode` 存取器 + 新腳本預設 True

**Files:**
- Modify: `src/keyboard_executor/app/script_editor_model.py`（`new` 的 `_settings` 預設、property/setter）
- Test: `tests/app/test_script_editor_model.py`

**Interfaces:**
- Produces: `ScriptEditorModel.game_input_mode -> bool`（property）；`set_game_input_mode(on: bool)`；`ScriptEditorModel.new(...)` 的 `game_input_mode` 預設 `True`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_script_editor_model.py` 末端新增（沿用檔內 `ScriptEditorModel` import）：
```python
def test_new_script_defaults_to_game_input_mode():
    assert ScriptEditorModel.new("g").game_input_mode is True


def test_set_game_input_mode_writes_settings():
    model = ScriptEditorModel.new("g")
    model.set_game_input_mode(False)
    assert model.game_input_mode is False
    assert model.to_script().settings.game_input_mode is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_model.py -k "game_input_mode" -v`
Expected: FAIL（`ScriptEditorModel` 無 `game_input_mode`；新腳本 `_settings` 仍 False）

- [ ] **Step 3: 最小實作**

`script_editor_model.py`：`new` 內 `_settings` 的 `"game_input_mode": False`（約 57 行）改為 `"game_input_mode": True`：
```python
        obj._settings = {"speed": 1.0, "repeat": 1, "humanize_jitter_pct": 0,
                         "game_input_mode": True, "window_retry": 0,
                         "window_retry_interval_ms": 1000}
```
在 `set_loop_forever` 之後新增存取器：
```python
    @property
    def game_input_mode(self) -> bool:
        return bool(self._settings.get("game_input_mode", False))

    def set_game_input_mode(self, on: bool) -> None:
        self._settings["game_input_mode"] = on
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_model.py -v`
Expected: PASS（新增 2 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/script_editor_model.py tests/app/test_script_editor_model.py
git commit -m "feat(script-editor-model): game_input_mode 存取器，新腳本預設 True"
```

---

### Task 4: 腳本編輯器「遊戲模式」勾選框

**Files:**
- Modify: `src/keyboard_executor/app/script_editor.py`（`loop_check` 後加勾選框、`_on_save` 寫入）
- Test: `tests/app/test_script_editor_widget.py`

**Interfaces:**
- Consumes: `ScriptEditorModel.game_input_mode` / `set_game_input_mode`（Task 3）。
- Produces: `ScriptEditorDialog.game_mode_check`（`QCheckBox`）；`_on_save` 依勾選寫入 `game_input_mode`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/app/test_script_editor_widget.py` 末端新增（沿用檔內 `ScriptEditorModel`、`ScriptEditorDialog`、`ScriptStorage`）：
```python
def test_game_mode_checkbox_default_checked_and_saves(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("遊戲腳本")
    model.insert(len(model), {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage)
    assert dialog.game_mode_check.isChecked() is True        # 新腳本預設勾起（一律遊戲模式）
    dialog.name_edit.setText("遊戲腳本")
    dialog.title_edit.setText("記事本")
    dialog.game_mode_check.setChecked(False)                 # 這條關掉遊戲模式
    dialog._on_save()
    assert storage.load("遊戲腳本").settings.game_input_mode is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_widget.py -k "game_mode_checkbox" -v`
Expected: FAIL（`ScriptEditorDialog` 無 `game_mode_check`）

- [ ] **Step 3: 最小實作**

`script_editor.py`：在 `self.loop_check ... layout.addWidget(self.loop_check)`（約 528-530 行）之後加：
```python
        self.game_mode_check = QCheckBox(
            "遊戲模式（改用 DirectInput scan code，適合會擋一般輸入的遊戲）")
        self.game_mode_check.setChecked(model.game_input_mode)
        layout.addWidget(self.game_mode_check)
```
`_on_save` 在 `self._model.set_loop_forever(self.loop_check.isChecked())`（約 1070 行）之後加：
```python
        self._model.set_game_input_mode(self.game_mode_check.isChecked())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest tests/app/test_script_editor_widget.py -v`
Expected: PASS（新增 1 項與既有全數）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/app/script_editor.py tests/app/test_script_editor_widget.py
git commit -m "feat(script-editor): 加「遊戲模式」勾選框（預設勾起，存入 settings）"
```

---

### Task 5: 全套件回歸

**Files:** 無（僅驗證）

- [ ] **Step 1: 跑全套件**

Run: `QT_QPA_PLATFORM=offscreen python.exe -m pytest -q`
Expected: 全數 PASS（既有 689 + 新增約 6 項；容許既有 4 skipped）。若有失敗，回對應任務修正。

- [ ] **Step 2: 確認行尾 LF**

Run: `for f in $(git diff --name-only HEAD~4); do [ -f "$f" ] && echo "$(grep -c $'\r' "$f")  $f"; done`
Expected: 全部 0。

無新增 commit（純驗證）。

---

## 附註：打包與人工驗收（非本計畫 commit 範圍）

實作完成後重打包 exe（先 `taskkill /IM KeyboardExecutor.exe /F /T` 殺殘留）。實機驗收：新腳本的「遊戲模式」預設勾起；加一個組合鍵動作（如 Ctrl+Shift+S 或遊戲快捷鍵）→ 執行 → 遊戲應收得到（因走 scan code＋40ms hold）。若某條腳本要在一般 app 打中文，取消該腳本的遊戲模式。此步驟在計畫外，由使用者驅動。
