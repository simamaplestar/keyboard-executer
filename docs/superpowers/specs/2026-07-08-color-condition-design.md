# 規則「顏色」條件 — 設計文件

- **日期**：2026-07-08
- **狀態**：已與需求方確認設計方向，待審閱
- **相關**：延伸自 `2026-07-06-keyboard-executor-design.md` 的監看規則引擎（§8）

## 1. 動機

現有規則條件只有 `text`（OCR）與 `image`（模板比對）。使用者想偵測小地圖上「有沒有紅點」——判斷是否有其他玩家/實體進入。模板比對不適用，因為：

1. `match_template` 預設轉灰階（`vision.py`，抗亮度變化），**丟掉顏色資訊**——分不出紅點/黃點/藍點。
2. 小地圖上的點只有數像素，模板太小、比對不穩，點一移動或地圖捲動就失準。

「有沒有某顏色」本質是**顏色偵測**：把區域轉 HSV、數落在目標顏色範圍內的像素，不受位置與移動影響。本文件為此新增 `color` 條件類型。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 顏色指定方式 | **滴管取色**：從螢幕截圖點選目標像素取樣，自動在該色相周圍建容差範圍 |
| 觸發語意 | 支援**出現/消失**切換（`absent` 旗標）；「消失時」= 符合像素 < 門檻才命中 |
| 套用範圍 | 只加在**監看規則**；不加腳本動作（`if_color` 等，YAGNI） |
| 偵測區域 | 沿用現有規則層的「框選區域」欄位（框小地圖）；滴管只決定「顏色」 |
| 容差調整 | UI 露「容差」（色相）與「最少像素」；S/V 用內建寬鬆下限，不露 |

## 3. 資料模型

`core/models.py` 的 `RuleCondition`（frozen dataclass）新增欄位，僅在 `type=="color"` 使用；沿用現有「扁平欄位 + 預設值」風格：

```python
type = "color"
hue: int          # 取樣 HSV（OpenCV：H 0–179, S/V 0–255）
sat: int
val: int
hue_tol: int = 10     # 色相容差（UI「容差」；紅色 0/179 環繞自動處理）
sat_tol: int = 80     # 飽和容差 → 下限 = sat - sat_tol（內建，不露 UI）
val_tol: int = 80     # 明度容差 → 下限 = val - val_tol（內建，不露 UI）
min_pixels: int = 3   # 區域內符合像素 ≥ 此值才算「有」
absent: bool = False  # True = 「消失時」觸發
```

驗證與序列化三處各加 `color` 分支：

- `_validate_rule_condition`：接受 `type=="color"`，`_check_no_extra` 允許 `{type, hue, sat, val, hue_tol, sat_tol, val_tol, min_pixels, absent}`。範圍檢查：H ∈ [0,179]、S/V ∈ [0,255]、各 tol ≥ 0、`min_pixels ≥ 1`、`absent` 為 bool。非法值拋繁中 `ScriptValidationError`。
- `rule_to_dict`：`color` 分支輸出上述欄位。
- `rule_from_dict`：經上述驗證還原。

## 4. 偵測演算法

### 4.1 純函式（`core/color_math.py`，新檔，無 cv2）

```python
def hue_ranges(hue: int, tol: int) -> list[tuple[int, int]]:
    """回傳 OpenCV 色相 (0–179) 的比對區間；跨 0/179 邊界時回兩段。
    例：hue=0, tol=10 → [(0,10),(170,179)]；hue=90,tol=10 → [(80,100)]。"""
```

抽出純邏輯便於單測色相環繞。

### 4.2 cv2 運算（`core/vision.py`）

```python
def count_color_pixels(image_bgr, hue, sat, val,
                       hue_tol=10, sat_tol=80, val_tol=80) -> int:
    """區域 BGR → HSV，建遮罩後回符合像素數。
    遮罩：H ∈ hue_ranges(hue, hue_tol)（環繞用兩段 OR）
          S ≥ clamp(sat - sat_tol, 0, 255)
          V ≥ clamp(val - val_tol, 0, 255)
    回 cv2.countNonZero(mask)。"""

def sample_dominant_hsv(image_bgr) -> tuple[int, int, int]:
    """一小塊 BGR patch → 代表 HSV：轉 HSV 後取飽和度最高的像素
    （避免取到反鋸齒邊緣的淡色）。供滴管取樣。"""
```

命中判定（在 `rule_engine`）：`count = count_color_pixels(...)`；`found = count < min_pixels if absent else count >= min_pixels`。

## 5. 滴管取色覆蓋層（`app/color_picker.py`，新檔）

**關鍵限制**：覆蓋層是半透明遮罩，無法讀自己的像素；直接對實螢幕擷取又會被遮罩色汙染。

**做法**：開啟時先用注入的 `capture_factory`（`MssScreenCapture`）抓一張全螢幕截圖，畫成覆蓋層背景（所見即所取）→ 十字準心 → 點擊時**從那張截圖的 numpy 陣列**取樣（點擊處 5×5 交 `sample_dominant_hsv`，容忍手抖 1px）→ 發 `color_picked(h, s, v)`。Esc 取消。

與 `RegionPickerOverlay` 一致：以 modal 對話框為 parent、開啟時 `raise_/activateWindow` 取焦點（沿用既有 modal-input 修正）。取樣座標邏輯→實體像素沿用 `region_picker.drag_scale(devicePixelRatio())`。可測 seam：`_begin/_finish` 對應改為 `_pick(x, y)`；取樣純運算在 `sample_dominant_hsv` 可獨立單測。

> 放大鏡/多螢幕為既有限制範圍外，v1 不做（沿用 region picker 只用 primaryScreen 的現況）。

## 6. 規則編輯器 UI（`app/rule_editor.py` + `app/rule_editor_model.py`）

條件類型下拉加「顏色」。顏色欄位（僅 color 型別相關）：

```
條件類型：  [顏色 ▼]
[滴管取色…]   已取樣：■ H=0 S=200 V=230     ← 色塊 + 數值標籤
容差：      [10]
最少像素：  [3]
偵測：      (●) 出現時   ( ) 消失時
```

- `RuleEditorModel` 加表單友善欄位：`hue/sat/val/hue_tol/min_pixels`（字串）、`absent`（bool），`from_rule`/`to_dict` 加 color 分支（`sat_tol/val_tol` 用預設，不進表單）。
- Dialog 沿用 `capture_factory` 注入；滴管按鈕開 `ColorPickerOverlay(self)`，`color_picked` 回填欄位與色塊。
- 「偵測」用兩顆 radio（出現/消失）對應 `absent`。

## 7. 引擎接線（`core/rule_engine.py`）

`_matches` 加分支：

```python
elif rule.condition.type == "color":
    count = count_color_pixels(image, c.hue, c.sat, c.val,
                               c.hue_tol, c.sat_tol, c.val_tol)
    return count < c.min_pixels if c.absent else count >= c.min_pixels
```

與 text/image 同一擷取路徑；per-rule 例外隔離、冷卻、觸發皆不變。

## 8. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| `color_math` | `hue_ranges` 一般段、跨 0 邊界、跨 179 邊界、tol 覆蓋全色相 |
| `vision` | 合成紅塊 → count > 0；純灰/異色 → 0；`sample_dominant_hsv` 取到飽和像素 |
| `models` | color 條件 round-trip；擋 H/S/V 越界、min_pixels<1、absent 非 bool |
| `rule_editor_model` | `to_dict`/`from_rule` color 分支 |
| `rule_editor_widget` | 下拉含「顏色」；取色流程回填欄位；overlay parent 到 dialog；存檔持久化 color 規則 |
| `rule_engine` | 注入假擷取回紅圖 → 出現模式命中；消失模式反轉 |
| `color_picker` | `sample_dominant_hsv` seam、overlay parent、Esc 取消 |

## 9. 非目標（YAGNI）

- 腳本動作的顏色版（`if_color`/`wait_color`/`click_color`）
- 多顏色/顏色組合條件
- 滴管放大鏡、多螢幕取色
- 每通道容差全露 UI（S/V 容差內建）
