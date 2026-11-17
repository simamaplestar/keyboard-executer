# 組合鍵可設定按住時間（hold_ms）— 設計文件

- **日期**：2026-07-13
- **狀態**：已與需求方確認設計方向，待審閱

## 1. 動機

`key_combo`（組合鍵）動作目前固定按住 40ms（`_COMBO_HOLD`）就放開——足夠讓輪詢式遊戲偵測「同時按下」，但無法「按住一段時間」（例如按住 `shift+a+right` 幾秒）。使用者要能設定組合鍵按住多久。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 單位 | **毫秒（ms）**，與 `key_press` 的 `hold_ms` 一致（同一編輯器不混用單位；長按 2 秒填 2000） |
| 預設值 | `hold_ms` 預設 **0**＝維持現有固定 40ms 路徑（遊戲偵測同時按下不變）；`>0`＝按住這麼久 |
| 中斷性 | 長按走 **Player 託管、可被緊急停止中斷**（比照 `key_press` 的 hold）——按下→可中斷 sleep→`finally` 保證放鍵 |
| 兩後端 | pynput 與 win32 game mode 都要支援 |
| 定位 | 純執行時長設定，非反偵測 |

## 3. 架構總覽

比照既有 `key_press` 的 `hold_ms` 設計。關鍵觀察：`InputBackend` 已有抽象 `key_down`/`key_up`，且 `Win32InputBackend` 的 `key_down`/`key_up` 在 game mode 已走 pdi——因此把「依序按下/反序放開」做成 **base 的具體方法**（呼叫 `self.key_down`/`key_up`），兩後端靠多型自動正確，win32 不必再各寫一份。五個改動點：

1. **動作模型（models.py）** — `key_combo` 動作新增 `hold_ms: int`（驗證＋標籤）。
2. **後端基底（base.py）** — `InputBackend` 新增**具體**方法 `key_combo_down`/`key_combo_up`（以 `self.key_down`/`key_up` 實作）。
3. **pynput 後端** — 既有 `key_combo`(40ms) 改用 `self.key_combo_down`/`key_combo_up`（DRY，行為不變）。
4. **win32 game 後端** — **刪除** `key_combo` 覆寫（改繼承 pynput 版，靠 `key_down`/`key_up` 多型走 pdi，行為不變）；移除不再使用的 `_COMBO_HOLD` import。
5. **執行（player.py）** — `KEY_COMBO` 分支比照 `KEY_PRESS`：`hold_ms>0` 走 down/可中斷 sleep/up，`==0` 走 `key_combo`。
6. **UI（action_fields.py＋script_editor.py）** — key_combo 表單加 `hold_ms` 欄、chip 顯示按住。

測試假件 `FakeInputBackend` 已實作 `key_down`/`key_up`/`key_combo` 的記錄，**無需修改**——它繼承 base 的 `key_combo_down`/`key_combo_up`，會逐一記錄 `key_down`/`key_up`，Player 測試據此即可區分兩條路徑。

## 4. 單元一：動作模型（`core/models.py`）

### 4.1 驗證（`_validate_key_combo`）
- `_check_no_extra(p, "動作 key_combo", {"keys", "hold_ms"})`（加入 `hold_ms`）。
- 回傳 dict 加：`"hold_ms": _get_int(p, "動作 key_combo", "hold_ms", minimum=0, default=0, required=False)`（與 `_validate_key_press` 相同用法）。
- `keys` 驗證維持不變。

### 4.2 標籤（`action_label`，KEY_COMBO 分支）
```python
if t is ActionType.KEY_COMBO:
    combo = "組合鍵 " + "+".join(p["keys"])
    return f"{combo}（按住 {p['hold_ms']}ms）" if p["hold_ms"] else combo
```

### 4.3 序列化與相容
`action_to_dict` 以 `action.params` 通用輸出，`hold_ms` 自動含入。舊腳本 `key_combo` 無 `hold_ms` → 驗證帶入預設 0 → 走現有 40ms 路徑，行為不變。

## 5. 單元二：後端基底（`platforms/base.py`）

`InputBackend` 新增兩個**具體**方法（緊接 `key_combo` 抽象宣告後；以既有抽象 `key_down`/`key_up` 實作，子類靠多型自動正確）：
```python
def key_combo_down(self, keys: list[str]) -> None:
    """依序按下全部鍵（不放開）。"""
    for k in keys:
        self.key_down(k)

def key_combo_up(self, keys: list[str]) -> None:
    """反序放開全部鍵。"""
    for k in reversed(keys):
        self.key_up(k)
```
按住多久由呼叫端（Player）掌控。這兩個方法**不是** `@abstractmethod`，故所有既有子類（Pynput/Win32/FakeInputBackend）自動繼承、無需各自實作。

## 6. 單元三：pynput 後端（`platforms/common/input_pynput.py`）

既有 `key_combo`(固定 40ms) 改用繼承來的 down/up（DRY，行為不變）：
```python
def key_combo(self, keys: list[str]) -> None:
    self.key_combo_down(keys)
    self._sleep(_COMBO_HOLD)          # 預設 40ms：讓輪詢式遊戲抓得到同時按下
    self.key_combo_up(keys)
```
（`key_combo_down`/`key_combo_up` 由 base 提供，透過 `self.key_down`/`key_up`＝`self._kb.press`/`release`。pynput 不需自寫 down/up。）

## 7. 單元四：win32 game 後端（`platforms/win32/input.py`）

**刪除** `Win32InputBackend.key_combo` 覆寫——改繼承 pynput 版。當 `key_combo` 在 Win32 實例上執行時，`self.key_combo_down`→`self.key_down`（Win32 覆寫，game mode 走 `pdi.keyDown`）；`self._sleep(_COMBO_HOLD)`；`self.key_combo_up`→`self.key_up`（`pdi.keyUp`）——與原本的 pdi 順序完全一致。同時移除因此不再使用的 `_COMBO_HOLD` import（`from ... import _COMBO_HOLD, _SETTLE, PynputInputBackend` → 去掉 `_COMBO_HOLD`；`_SETTLE` 仍用）。既有 `test_game_mode_key_combo_releases_in_reverse` 斷言的 pdi 順序不變、續過。

## 8. 單元五：執行（`core/player.py`，`_run_one` 的 KEY_COMBO 分支）

比照 KEY_PRESS 的 hold 處理（見同檔既有 291–302 行）：
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
`self._sleep` 未注入時為 `stop_event.wait` 式（緊急停止途中提早醒來），故長按可被中斷。

## 9. 單元六：UI（`app/action_fields.py`＋`app/script_editor.py`）

### 9.1 `action_fields.py`
`FIELD_SPECS["key_combo"]` 由 `[("keys", "keys")]` 改為 `[("keys", "keys"), ("hold_ms", "int")]`。`hold_ms` 的 `FIELD_LABELS` 標籤、`"int"` coerce（`to_action_dict`：空欄省略→驗證帶預設 0）皆已通用，無需再改。共用標籤「按住時間（毫秒；0＝按一下就放開，>0＝按住這麼久再放開）」對組合鍵亦適用（0＝快速按放）。

### 9.2 `script_editor.py`（`_chip_spec` KEY_COMBO 分支）
```python
if t == "key_combo":
    hold = d.get("hold_ms", 0)
    keys = "+".join(str(k).upper() for k in d.get("keys", []))
    return keys, (f"組合鍵，按住 {hold}ms" if hold else "組合鍵"), "key"
```

## 10. 資料流

```
編輯器 key_combo 表單（keys ＋ hold_ms 欄）→ to_action_dict（空 hold_ms 省略）
  → action_from_dict 驗證（hold_ms 預設 0）→ 存檔

執行：Player._run_one KEY_COMBO
  → hold_ms>0：backend.key_combo_down(keys) → 可中斷 _sleep(hold_ms/1000) → finally key_combo_up(keys)
  → hold_ms==0：backend.key_combo(keys)（key_combo_down + 40ms + key_combo_up）
```

## 11. 錯誤處理

- 長按途中緊急停止：`_sleep` 提早醒、`finally` 保證 `key_combo_up` 放鍵，下一個 `_check_stop` 中止；不卡鍵。
- `hold_ms` 為純整數設定，驗證同 `key_press`（minimum=0）。

## 12. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `models` | `key_combo` 預設 `hold_ms==0`；`_get_int` 驗證（負值拒、非整數拒）；`hold_ms` 進 `_check_no_extra` allowed；round-trip 保值；`action_label` 有 hold 時顯示「按住 Xms」 |
| `input_pynput` | `key_combo_down` 依序 press、`key_combo_up` 反序 release（注入 fake keyboard 記錄 ops）；`key_combo` = down + `_sleep(0.04)` + up（順序正確、含一次 sleep） |
| `win32/input`（game mode） | 既有 `test_game_mode_key_combo_releases_in_reverse` 續過（pdi keyDown 全部→keyUp 反序）；`key_combo_down`/`key_combo_up` 於 game mode 走 pdi.keyDown/keyUp（順序） |
| `player` | KEY_COMBO `hold_ms>0` → 記錄序為 `key_down` 全部→`_sleep(hold_ms/1000)`→`key_up` 反序（fake calls）；`hold_ms==0` → 記錄 `("key_combo", keys)`；長按途中設 stop_event → `_sleep` 提早醒且 `key_up`（放鍵）仍被呼叫（不卡鍵） |
| `action_fields` | `to_action_dict("key_combo", {"keys":"ctrl+s","hold_ms":"2000"})` → `{"type":"key_combo","keys":["ctrl","s"],"hold_ms":2000}`；空 hold_ms → 省略 |
| `script_editor`（chip） | `_chip_spec` key_combo 有 hold → 副行「組合鍵，按住 Xms」；無 hold → 「組合鍵」 |

既有 `key_combo` 相關測試（斷言 press/release 順序或含一次 `_sleep(0.04)`）續過——`key_combo` 行為不變（改用 down/up 但仍 40ms）。既有走 `hold_ms==0` 分支的 KEY_COMBO player 測試續過（`("key_combo", keys)` 記錄不變）。

## 13. 非目標（YAGNI）

- per-key 個別按住時間（整組共用一個 hold_ms）。
- `hold_ms` 上限（沿用 `key_press` 無上限）。
- 秒為單位的欄位（採 ms，與 `key_press` 一致）。
- 錄製組合鍵時擷取按住時長（錄製只擷取鍵，時長於編輯器手動設定）。
