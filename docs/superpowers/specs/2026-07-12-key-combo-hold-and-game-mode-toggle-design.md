# 組合鍵 hold + 腳本編輯器遊戲模式開關 — 設計文件

- **日期**：2026-07-12
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

使用者的「組合鍵（key_combo）」動作在遊戲裡沒效果。系統性除錯查出兩個根因：

- **A：`key_combo` 停留 0ms。** 兩個輸入後端（pynput、win32 game mode）都是「按下全部鍵 → 立刻放開全部」，中間無延遲（`pdi.PAUSE=0`、無 sleep）。輪詢式讀鍵的遊戲（DirectInput / GetAsyncKeyState）在兩次輪詢之間就被按下又放開，抓不到「修飾鍵＋主鍵同時按下」那一瞬間。使用者實測：一般模式(pynput)下單鍵有效、組合鍵無效——代表 pynput 輸入有進遊戲，差在 hold 太短。
- **B：GUI 沒有遊戲模式開關。** `ScriptSettings.game_input_mode`（改走 pydirectinput/DirectInput scan code）只存在於資料模型與 CLI，**腳本編輯器 GUI 沒有接**，所以 GUI 建的腳本一律是一般模式(pynput)，讀 DirectInput 的遊戲常收不到。

兩者一起解，讓組合鍵在遊戲裡能用。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| A. hold 時間 | `key_combo` 按下全部鍵後停留 **40ms**（`_COMBO_HOLD = 0.04`）再反序放開；固定值不做可設定 |
| A. 兩後端 | pynput 與 win32 game mode 的 `key_combo` 都加此 hold（都用既有可注入的 `self._sleep`） |
| B. 開關位置 | 腳本編輯器「循環執行」勾選框旁加「遊戲模式」勾選框 |
| B. 儲存 | 勾選狀態於 `_on_save` 寫進 `settings.game_input_mode` |
| B. 預設 | **一律都用遊戲模式**：`game_input_mode` 預設值改為 `True`——新腳本、舊腳本檔缺鍵、CLI 全預設遊戲模式；勾選框預設勾起。開關保留，讓特定腳本可關（如一般 app 打中文）。 |
| 定位 | `game_input_mode` 只是換輸入 API 送 scan code，**非反偵測** |

## 3. Part 1 — `key_combo` 加 hold

### 3.1 `platforms/common/input_pynput.py`
- 新增模組常數 `_COMBO_HOLD = 0.04`（秒）。
- `key_combo` 改為：
  ```python
  def key_combo(self, keys: list[str]) -> None:
      parsed = [parse_key(k) for k in keys]
      for k in parsed:
          self._kb.press(k)
      self._sleep(_COMBO_HOLD)          # 停留讓輪詢式遊戲抓得到同時按下
      for k in reversed(parsed):
          self._kb.release(k)
  ```

### 3.2 `platforms/win32/input.py`（game mode）
- 從 `input_pynput` 引用 `_COMBO_HOLD`（同 `_SETTLE` 的引用方式）。
- `key_combo`（game mode 分支）改為：
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

### 3.3 為什麼 40ms
一個遊戲 frame 約 16ms；40ms 跨得過至少 2 次輪詢，足以被抓到，又夠短不明顯拖慢腳本（每個組合鍵動作多 40ms）。

## 4. Part 2 — 腳本編輯器「遊戲模式」勾選框（預設開）

### 4.0 `core/models.py`（`ScriptSettings` 預設）
- `game_input_mode` 預設值 `False` → **`True`**（`class ScriptSettings: ... game_input_mode: bool = True`）。
- `script_from_dict`／settings 驗證讀 `data.get("game_input_mode", defaults.game_input_mode)`，因此舊腳本檔缺此鍵時帶入 `True`（一律遊戲模式）。既有斷言預設 `False` 的測試須更新為 `True`。

### 4.1 `app/script_editor_model.py`（`ScriptEditorModel`）
- 新腳本 `_new` 的 `_settings` 預設把 `"game_input_mode": False` → `"game_input_mode": True`（與模型預設一致）。
- 鏡射既有 `loop_forever`/`set_loop_forever`：
```python
@property
def game_input_mode(self) -> bool:
    return bool(self._settings.get("game_input_mode", False))

def set_game_input_mode(self, on: bool) -> None:
    self._settings["game_input_mode"] = on
```

### 4.2 `app/script_editor.py`（`ScriptEditorDialog`）
- 在 `self.loop_check` 那段之後加：
  ```python
  self.game_mode_check = QCheckBox(
      "遊戲模式（改用 DirectInput scan code，適合會擋一般輸入的遊戲）")
  self.game_mode_check.setChecked(model.game_input_mode)
  layout.addWidget(self.game_mode_check)
  ```
- `_on_save` 在既有 `self._model.set_loop_forever(self.loop_check.isChecked())` 之後加：
  ```python
  self._model.set_game_input_mode(self.game_mode_check.isChecked())
  ```

### 4.3 儲存與相容
`game_input_mode` 已是 `ScriptSettings` 欄位；`script_to_dict`/`script_from_dict` 與 settings 驗證已支援。存檔即寫入；**舊腳本檔無此鍵時 `script_from_dict` 以新預設 `True` 帶入**（一律遊戲模式；這是刻意的行為改變）。已存明確 `game_input_mode: false` 的腳本仍尊重其值（可關）。

## 5. 資料流

- 組合鍵：`key_combo(keys)` → press 全部 → `_sleep(0.04)` → release 全部（反序）→ OS。
- 遊戲模式：勾選框 → `_on_save` → `model.set_game_input_mode` → `settings.game_input_mode` → 存檔 → 執行時 `get_platform(game_input_mode=...)` 決定走 pdi 或 pynput（既有接線不變）。

## 6. 錯誤處理

- `key_combo` 的 hold 用既有 `self._sleep`；停止途中不特別處理（組合鍵為單一動作、極短）。
- 遊戲模式為純設定旗標，無額外錯誤路徑。

## 7. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `input_pynput` | `key_combo` 於「press 全部」與「release 前」之間呼叫 `self._sleep(0.04)`（注入 fake keyboard 記錄 ops 順序 + 注入 sleep 記錄呼叫）；press/release 順序與鍵維持正確 |
| `win32/input`（game mode） | game mode `key_combo` 於 `pdi.keyDown` 全部之後、`keyUp` 之前呼叫 `_sleep(0.04)`；非 game mode 走父類別（pynput）不變 |
| `models`（ScriptSettings） | `ScriptSettings().game_input_mode` 預設 `True`；`script_from_dict` 缺 `game_input_mode` → `True`；明確 `false` → `False`（可關） |
| `script_editor_model` | 新腳本 `game_input_mode` 預設 True；`set_game_input_mode(False)` → property False 且 `to_dict()` 的 `settings.game_input_mode` 為 False；`from_...` 載入既有腳本還原其值 |
| `script_editor`（widget） | 勾選框存在、初值反映 model（新腳本預設勾起）；取消勾選後存檔 → 存下的腳本 `settings.game_input_mode == False` |

既有 `key_combo` 測試（若斷言 press/release 順序）續過；若有斷言「無 sleep」者改為含一次 `_sleep(0.04)`。既有斷言 `game_input_mode` 預設 `False` 的測試須更新為 `True`。

## 8. 非目標（YAGNI）

- hold 時間可設定（固定 40ms）。
- 單一 `key_press`（hold_ms=0）的 0ms 行為（使用者已可設 hold_ms；本次只動組合鍵）。
- 設定頁的全域遊戲模式（維持「每腳本」設定）。
- 任何反偵測/反作弊繞過。
