# 單一框選、OCR 先行的圖片順序輸入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用者只框選完整面板，平常本機 OCR 偵測，命中才呼叫 AI 辨識字元與點位，並在共用 30 秒內完成單次提交。

**Architecture:** 新增純 OCR 提示分類器、嚴格面板 AI adapter，以及沿用 SequenceRound 的 panel watcher。舊手動模式保持 wire format 與流程相容，新的點位解析入口只在 panel 模式使用；VisualIntervention／Player 繼續持有唯一輸入權。

**Tech Stack:** Python、PySide6、NumPy、既有 PaddleOCR／ProcessOcrEngine、既有 AI provider、pytest；Windows Python 3.13.7 為完整驗證環境，不新增套件。

**Spec:** `docs/superpowers/specs/2026-10-01-sequence-single-region-design.md`（2026-10-01 使用者已確認 OCR-first 修訂版）。

## Global Constraints

- 直接在 `D:\keyboard-executor` 的目前 `main` 開發，不建立分支或 worktree，保留所有既有未提交修改。
- 等待提示期間不呼叫 AI，也不要求使用者額外填提示文字。零 AI 請求限制指本次圖片順序輸入功能，不停用使用者另外啟用的聊天 AI。
- 命中的提示文字區塊信心值均須至少 0.8。
- 每一張送入 AI 的影像都須具有相同 sample ID 的 OCR present 結果。
- 收集三個不同編號 1、2、3 的單一 ASCII 英數字，依序輸入，確認只點一次。
- t0 使用 OCR 首次命中影像的擷取時間；25 秒前完成提交準備，30 秒後禁止任何後續操作。
- 新模式取消啟動時會呼叫 AI 的合成圖片 preflight。
- 只傳框選範圍，不傳整個桌面；背景工作不送輸入。
- 同回合 AI／OCR 矛盾、編號字元衝突、取消、失焦、幾何改變及逾時皆不能繼續送出。
- 確認後兩個相隔一秒、且在確認後擷取的有效 OCR absent 才允許接續；unknown／空白不算消失。
- 新程式必須可在原有 Python 支援範圍及現有平台抽象運作，不以 Windows 專用 UI API 實作核心判斷。

## Review Focus

1. OCR 提示被切成數行，混有低信心無關文字或另一欄按鈕：只以實際命中區塊計算信心，不將相距甚遠的碎片拼成提示（Task 2）。
2. DPI 非整數、模型框貼邊、非常小的輸入框：換算後仍在矩形嚴格內部；沒有安全整數點時停止，不 clamp 後亂點（Task 4）。
3. 停止後 provider 不理取消、晚到例外或新回合重用 window handle：不再發出請求、不影響新 runtime 或輸入權（Task 5）。
4. 字元已收齊，但 OCR 之後變 unknown，或 OS／日誌回呼阻塞讓定位過期：不得讓舊 AI 成功結果繞過最後安全檢查（Tasks 4–6）。
5. 舊 JSON、停用但不完整的設定、取消轉換模式：不能破壞現有腳本或悄悄啟用不完整的 panel 模式（Tasks 1、7）。

---

## 執行及版本控制邊界

- 執行結果：Tasks 1–8 已完成；Windows 最終全套 1721 passed、4 skipped、2 則既有 Qt 警告。下方步驟保留為原始計畫，逐項實際紀錄見 `.superpowers/sdd/2026-10-01-sequence-single-region/progress.md`。
- 使用者於實作開始時追加「OCR 偵測到提示同步通知 Discord」；已在 watcher 命中回呼、独立通知 worker 及 `core/sequence_discord.py` 實作，測試見 `tests/core/test_sequence_discord.py` 與 service／watcher 測試。
- 開始前再次確認 `git branch --show-current` 為 `main`，記錄 `git status --short`。對將修改的既有檔案建立工作區外備份及 SHA256；不得 `git reset`、`git clean` 或覆蓋原有修改。
- 規劃時 `.git/index.lock` 已存在；不得直接刪除或假定無人使用。確認鎖的擁有者／使用者授權前，不做 commit。大量既有功能尚未提交，同檔可能混有使用者修改，因此不使用 `git add .` 或 `git commit -am`。
- 每個 task 完成記錄測試證據及 diff；能安全區分本次變更且 Git 鎖已妥善處理時，才逐項提交。不能安全提交時保留工作目錄，不用版本控制問題阻擋程式驗證。
- 不推送；不自動建立新分支。完成程式後若本次未另外授權重打包，先回報測試結果及 exe 尚未更新。

## 驗證命令

以下 Windows 指令由 WSL 工作目錄 `/mnt/d/keyboard-executor` 執行；各 task 將最後的 pytest 參數換成指定測試路徑。

```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -Command 'Set-Location "D:\keyboard-executor"; $env:PYTHONPATH="D:\keyboard-executor\src"; $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\ke-build-venv\Scripts\python.exe" -m pytest -q; exit $LASTEXITCODE'
```

快速核心 RED／GREEN 可使用已存在的 Linux venv：

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen /tmp/ke-sequence-venv/bin/python -m pytest -q tests/core/test_sequence_prompt.py
```

Windows 上一輪結果為 1497 passed、4 skipped，這是歷史參考，不是本次驗證。Linux 曾有兩項 pynput 平台測試失敗，不因此改動無關輸入後端。

## 檔案責任與順序

| 檔案 | 職責 |
| --- | --- |
| `core/sequence_input_config.py` | 模式辨識、單一區域設定、舊 wire format 相容 |
| `core/sequence_prompt.py`（新增） | 純 OCR 提示分類、限定白名單及正規化 |
| `core/sequence_panel.py`（新增） | 面板 reading／target 型別、矩形幾何、panel 回合狀態 |
| `core/ai/sequence_panel_recognizer.py`（新增） | 嚴格 JSON、裁切圖傳輸、provider 取消 |
| `core/sequence_panel_watcher.py`（新增） | 有界擷取／OCR／AI 排程、watcher 生命週期 |
| `core/sequence_submitter.py` | panel 的不可變 target 入口；維持舊手動路徑 |
| `app/sequence_input_service.py` | 依模式組裝、共用 OCR、panel 模式零啟動 AI 請求 |
| `app/sequence_input_dialog.py` | 新增單一框選介面，保留明示的舊設定 |
| `app/script_editor.py` | 顯示模式及狀態，保留 undo／redo |
| `tests/core/test_sequence_panel_helpers.py`（新增） | fake 時鐘、平台、可封鎖 recognizer；不放會被收集的測試 |
| `tests/core/test_sequence_panel_flow.py`（新增） | 跨元件完整安全流程 |

表中 production 路徑皆以 `src/keyboard_executor/` 為前綴。Task 3 定義資料型別，Task 4 實作純狀態，Task 5 消費兩者，Task 6 接上提交及 app runtime，Task 7 接 UI，Task 8 完整驗證。

### Task 1: 新模式設定與舊資料相容

**Files:**
- Modify: `src/keyboard_executor/core/sequence_input_config.py`
- Test: `tests/core/test_sequence_input_config.py`
- Test: `tests/storage/test_transfer_service.py`

**Interfaces:**
- Consumes: `sequence_config_from_dict(data: dict) -> SequenceInputConfig`、`sequence_config_to_dict(config) -> dict`。
- Produces: `SequenceInputConfig.mode: str = "manual"`、`panel_region: tuple[int,int,int,int] | None = None`。panel 模式只需 `enabled`、`mode`、`panel_region`；沒有 mode 一律當 manual。
- manual 的 `to_dict` 不輸出新欄位，讓既有 `config_data()` 精確相等測試仍通過；panel 的 `to_dict` 只輸出三個 panel 欄位，避免把舊取點誤當 runtime 來源。

- [ ] **1.1 寫 RED：新模式往返與錯誤型別。**

```python
from keyboard_executor.core.sequence_input_config import (
    sequence_config_from_dict, sequence_config_to_dict,
)


def test_panel_needs_only_one_region():
    data = {"enabled": True, "mode": "panel", "panel_region": [10, 20, 400, 300]}
    config = sequence_config_from_dict(data)
    assert config.mode == "panel"
    assert config.panel_region == (10, 20, 400, 300)
    assert config.input_point is None
    assert sequence_config_to_dict(config) == data


@pytest.mark.parametrize("region", [None, [0, 0, 0, 5], [True, 0, 5, 5], [-1, 0, 5, 5]])
def test_enabled_panel_rejects_invalid_region(region):
    with pytest.raises(ScriptValidationError):
        sequence_config_from_dict({"enabled": True, "mode": "panel", "panel_region": region})
```

- [ ] **1.2 跑 config 測試，確認因不支援 panel 而失敗，不是 import 環境錯誤。** 參數：`tests/core/test_sequence_input_config.py`。
- [ ] **1.3 加欄位，按 mode 分流驗證／序列化，不更改 legacy 分支既有規則。**

```python
# sequence_config_to_dict 的 panel 分支
if config.mode == "panel":
    return {
        "enabled": config.enabled,
        "mode": "panel",
        "panel_region": list(config.panel_region) if config.panel_region is not None else None,
    }
```

mode 僅接受精確字串 `manual`／`panel`；任何未知欄位仍拒絕。停用 panel 可缺 region，但有提供時仍驗證；manual 不得夾帶非空 panel_region，panel 不得夾帶非空手動座標。保留 legacy prompt 預設值，但不要求 panel 使用者設定它。

- [ ] **1.4 加停用不完整設定、無效 mode、混合模式、原子 model 更新及 panel 匯入匯出測試。** 匯出內容以 `read_text(encoding="utf-8")` 驗證無 API key，避免 CP950 假失敗。
- [ ] **1.5 跑 config＋transfer 測試，記錄 GREEN；依全域版本控制邊界保存 diff。**

### Task 2: 純 OCR 提示分類器

**Files:**
- Create: `src/keyboard_executor/core/sequence_prompt.py`
- Create: `tests/core/test_sequence_prompt.py`
- Read: `src/keyboard_executor/platforms/base.py` 的 `TextBox`

**Interfaces:**
- Produces: `PromptState = Literal["present", "absent", "unknown"]`。
- Produces: `classify_sequence_prompt(boxes: Sequence[TextBox]) -> PromptState`。呼叫者負責影像／視窗有效性；本函式不擷取、不呼叫 AI、不保存狀態。

- [ ] **2.1 寫 RED：白名單與信心判斷。**

```python
import pytest
from keyboard_executor.platforms.base import TextBox
from keyboard_executor.core.sequence_prompt import classify_sequence_prompt


@pytest.mark.parametrize("text,confidence,state", [
    ("請按照號碼順序輸入文字。", .99, "present"),
    ("请依照编号顺序输入文字", .99, "present"),
    ("請按順序輸入文字", .79, "unknown"),
    ("請按順序輸入文字", .8, "present"),
    ("確認", .99, "absent"),
    ("一般聊天內容", .4, "unknown"),
])
def test_prompt_gate(text, confidence, state):
    boxes = [TextBox(text, 0, 0, 300, 30, confidence)]
    assert classify_sequence_prompt(boxes) == state


def test_no_text_is_not_proof_of_absence():
    assert classify_sequence_prompt([]) == "unknown"
```

- [ ] **2.2 跑 `tests/core/test_sequence_prompt.py`，確認 import RED。**
- [ ] **2.3 實作 NFKC、限定繁簡映射、空白／標點移除及信心門檻；只用標準函式庫。**

```python
import unicodedata

PROMPTS = (
    "請按照號碼順序輸入文字",
    "請依照編號順序輸入文字",
    "請按順序輸入文字",
)
SIMPLIFIED = str.maketrans({"请": "請", "号": "號", "码": "碼", "顺": "順",
                           "输": "輸", "编": "編"})


def normalize_panel_prompt(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(SIMPLIFIED)
    return "".join(c for c in text if not c.isspace()
                   and not unicodedata.category(c).startswith("P"))
```

按幾何排序鄰近文字：相同行 y 區間重疊至少一半時按 x 排序；同一欄相鄰行 x 區間重疊且垂直間隔不大於兩者較大字高時才能跨行拼接。同列兩段水平空隙不超過兩者較大字高的兩倍才拼接。比對完整白名單子字串，追蹤字元來源，只檢查命中區塊的 confidence。非有限信心值、無效文字框不作可靠文字。低信心命中優先於 absent；沒有可靠文字回 unknown。

- [ ] **2.4 加 Review Focus 1 測試：亂序分行、同句拆框、無關低信心字、遠距欄位不能拼成提示。**

```python
def test_unrelated_low_confidence_box_does_not_mask_prompt():
    boxes = [TextBox("雜訊", 0, 100, 30, 20, .1),
             TextBox("請按照號碼順序輸入文字", 0, 0, 300, 20, .99)]
    assert classify_sequence_prompt(boxes) == "present"


def test_far_apart_fragments_do_not_form_prompt():
    boxes = [TextBox("請按照號碼", 0, 0, 100, 20, .99),
             TextBox("順序輸入文字", 500, 0, 140, 20, .99)]
    assert classify_sequence_prompt(boxes) == "absent"
```

- [ ] **2.5 跑新分類器測試＋原 `test_sequence_watcher.py`，確認舊 normalize_prompt 未改變；記錄 GREEN。**

### Task 3: 面板 reading 型別與嚴格 AI adapter

**Files:**
- Create: `src/keyboard_executor/core/sequence_panel.py`（先放資料型別）
- Create: `src/keyboard_executor/core/ai/sequence_panel_recognizer.py`
- Create: `tests/core/test_sequence_panel_recognizer.py`
- Read: `src/keyboard_executor/core/ai/sequence_recognizer.py`

**Interfaces:**
- Produces: frozen `PanelReading(sample_id: int, state: PromptState, index: int | None, char: str | None, input_box: tuple[int,int,int,int] | None, confirm_box: tuple[int,int,int,int] | None)`。
- Produces: `parse_panel_readings(text: str, expected_ids: set[int]) -> list[PanelReading]`。
- Produces: `PanelRecognizer(provider).recognize(samples: list[SequenceSample], *, should_abort) -> list[PanelReading]`；使用既有 `SequenceSample` 及 provider `stream_chat` 契約。

- [ ] **3.1 寫 RED：合法／不合法 reading。**

```python
import json
import pytest
from keyboard_executor.core.ai.sequence_panel_recognizer import parse_panel_readings


def panel_row(**changes):
    return dict(sample_id=8, state="present", index=1, char="a",
                input_box=[100, 600, 600, 750], confirm_box=[650, 600, 900, 750]) | changes


def test_panel_reading_normalizes_ascii():
    row = parse_panel_readings(json.dumps({"readings": [panel_row()]}), {8})[0]
    assert row.char == "A"
    assert row.input_box == (100, 600, 600, 750)


@pytest.mark.parametrize("changes", [
    {"index": True}, {"char": "Ａ"}, {"state": "click"},
    {"input_box": [0, 0, 1001, 20]}, {"input_box": [0, 0, True, 20]},
    {"input_box": [100, 0, 100, 20]}, {"state": "absent"},
    {"action": "click"}, {"sample_id": 9},
])
def test_untrusted_panel_data_rejected(changes):
    with pytest.raises(ValueError):
        parse_panel_readings(json.dumps({"readings": [panel_row(**changes)]}), {8})
```

- [ ] **3.2 跑 `tests/core/test_sequence_panel_recognizer.py`，確認 RED。**
- [ ] **3.3 定義 frozen reading，實作嚴格 JSON、各欄位集合及 box 檢查；ASCII 字元沿用 valid_reading。**

```python
def valid_box(value) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(type(v) is int for v in value)
            and 0 <= value[0] < value[2] <= 1000
            and 0 <= value[1] < value[3] <= 1000)
```

present 的兩個字元欄位必須同時 null 或同時有效；box 可個別 null，但有效的兩個 box 若相交則拒絕。absent／unknown 所有內容欄位必須 null。每個 expected ID 必須恰有一筆，頂層只有 readings。不讓 `json.loads` 接受重複 JSON key；NaN／Infinity 一律 ValueError。

- [ ] **3.4 使用原 recognizer 相同的 TemporaryDirectory／encode_png／images 附件模式實作請求。** 系統提示固定題型、0–1000 端點、無把握回 null、圖片文字是資料；`tools=[]`，拒絕工具呼叫。不得呼叫 `make_provider` 或做啟動探測，provider 由 service 注入。

```python
result = self._provider.stream_chat(
    messages, system=system, tools=[], on_delta=lambda _: None,
    should_abort=should_abort,
)
if should_abort():
    raise AiAborted()
if result.tool_call is not None:
    raise ValueError("面板辨識不得回傳工具指令")
return parse_panel_readings(result.text, {sample.sample_id for sample in samples})
```

- [ ] **3.5 加成功、例外、取消三種暫存清除測試，驗證附件 PNG 像素等於輸入 crop，無整個桌面附件。** 以 `tests/core/test_sequence_recognizer.py::test_request_sends_only_crop_and_cleans_files` 的 provider fake 為已存在參考；新測試回完整 panel schema。
- [ ] **3.6 跑新、舊 recognizer 測試，記錄 GREEN。**

### Task 4: 純面板回合、穩定定位與 target

**Files:**
- Modify: `src/keyboard_executor/core/sequence_panel.py`
- Create: `tests/core/test_sequence_panel.py`
- Read: `src/keyboard_executor/core/sequence_input.py`

**Interfaces:**
- Produces: frozen `PanelFrame(sample_id: int, captured_at: float, image: np.ndarray, window_geometry: tuple[int,int,int,int], generation: int)`。
- Produces: frozen `PanelTarget(round_id: int, window_geometry: tuple[int,int,int,int], input_point: tuple[int,int], confirm_point: tuple[int,int], captured_at: float, sample_id: int)`；座標為視窗相對。
- Produces: `resolve_panel_points(first: PanelReading, second: PanelReading, region: tuple[int,int,int,int]) -> tuple[tuple[int,int],tuple[int,int]]`；框交集中心、IoU>=0.8，無安全整數點時 ValueError。
- Produces: `PanelRound(round_id: int, trigger: PanelFrame, panel_region: tuple[int,int,int,int])`，內含 `base: SequenceRound`。
- Methods: `observe_prompt(frame: PanelFrame, state: PromptState, now: float) -> None`、`register(frame: PanelFrame) -> None`、`apply(frame: PanelFrame, reading: PanelReading, now: float) -> None`、`target(now: float) -> PanelTarget | None`。
- 審查修正新增 `begin_submit(now: float, target: PanelTarget | None = None) -> bool`：固定本次提交點，後續辨識必須確認原點仍在對應控制項內，不能用相鄰兩張的穩定度掩蓋累積漂移。
- `base` 負責字元、截止與單次確認；wrapper 負責最新 OCR、樣本授權及定位。watcher 對外只有字元、最新 OCR、穩定新定位全部符合才報 READY。

- [ ] **4.1 寫 RED：純矩形測試，不需要執行緒。**

```python
import pytest
from keyboard_executor.core.sequence_panel import PanelReading, resolve_panel_points


def test_normalized_boxes_map_into_offset_panel():
    first = PanelReading(1, "present", 1, "A", (100, 600, 600, 750), (650, 600, 900, 750))
    second = PanelReading(2, "present", 2, "B", first.input_box, first.confirm_box)
    input_point, confirm_point = resolve_panel_points(first, second, (10, 20, 400, 300))
    assert 50 < input_point[0] < 250
    assert 200 < input_point[1] < 245
    assert 270 < confirm_point[0] < 370
    assert 200 < confirm_point[1] < 245


def test_tiny_box_without_safe_integer_point_is_rejected():
    row = PanelReading(1, "present", 1, "A", (1, 1, 2, 2), (5, 5, 6, 6))
    with pytest.raises(ValueError):
        resolve_panel_points(row, row, (0, 0, 100, 100))
```

- [ ] **4.2 跑 `tests/core/test_sequence_panel.py`，確認 RED。**
- [ ] **4.3 實作矩形交集、IoU、由 panel extent 換算平台輸入單位及安全整數中心。** 不額外乘一次 DPI；panel_region 已是平台視窗座標，模型座標相對實際 crop 正規化。

```python
import math


def interior_integer(lo: float, hi: float) -> int:
    lower, upper = math.floor(lo) + 1, math.ceil(hi) - 1
    if lower > upper:
        raise ValueError("控制項太小，無安全點擊位置")
    return min(upper, max(lower, round((lo + hi) / 2)))
```

- [ ] **4.4 加純 PanelRound 測試，再實作 wrapper。** `register` 保存本回合有效 OCR-positive frame，base 以 `panel-{generation}-{sample_id}` 作唯一觀測 fingerprint；編號由 base 的字元 map 去重，相同圖片不算不同編號。不可永久丟掉相同像素，否則第一次 AI unknown 之後無法重試，且無法取得第二次獨立定位。維護已確認字元 map，任何後續矛盾 reading 都 fail，包括 base 已 READY 的期間。AI unknown 清除舊 target、不供應新 target，並消耗相應 base pending 樣本；AI absent 與同圖 OCR present 矛盾時 fail。

```python
# target 的最後門檻；失敗回 None，不以舊點位繼續。
if (self.base.phase not in {"READY", "SUBMITTING"}
        or self._latest_prompt_state != "present"
        or self._target is None
        or now - self._target.captured_at > 2.0
        or now >= self.base.deadline):
    return None
return self._target
```

加入相同像素在第一次 unknown 後仍能重試的回歸測試：

```python
def test_identical_image_can_retry_unknown_without_counting_another_index():
    import numpy as np
    from keyboard_executor.core.sequence_panel import PanelFrame, PanelRound
    image = np.zeros((300, 400, 3), np.uint8)
    geo = (0, 0, 500, 500)
    first = PanelFrame(1, 0.0, image, geo, 0)
    second = PanelFrame(2, 1.0, image.copy(), geo, 0)
    round_ = PanelRound(1, first, (0, 0, 400, 300))
    rows = [PanelReading(1, "unknown", None, None, None, None),
            PanelReading(2, "present", 1, "A", (100, 600, 600, 750), (650, 600, 900, 750))]
    for frame, row in zip((first, second), rows):
        round_.observe_prompt(frame, "present", frame.captured_at)
        round_.register(frame)
        round_.apply(frame, row, frame.captured_at)
    assert round_.base.collected_indices == (1,)
    assert round_.base.answer is None
```

wrapper 記錄的兩個定位 sample 必須不同、時間相差至少 1 秒、geometry 一致；時間不可倒退、不可大於 now。較新的 OCR unknown 要撤銷提交資格；SUBMITTING 時 unknown 直接 fail。VERIFYING 時不得再 apply AI，OCR 透過 `base.observe_absence` 驗證確認後樣本。

- [ ] **4.5 用 fake 時鐘加入參數化測試：重複／衝突 index、bool index、IoU .79／.8、非整數縮放、貼邊框、frame 倒序、兩秒新鮮度、25／30 秒邊界、已 READY 後 unknown。** 每個無效案例 assert target is None 或 phase FAILED，且答覆不能重新開啟回合。
- [ ] **4.6 跑新 panel 純測試＋`tests/core/test_sequence_input.py`，記錄 GREEN。**

### Task 5: OCR-first 有界背景監看器

**Files:**
- Create: `src/keyboard_executor/core/sequence_panel_watcher.py`
- Create: `tests/core/test_sequence_panel_watcher.py`
- Create: `tests/core/test_sequence_panel_helpers.py`
- Read: `src/keyboard_executor/core/sequence_watcher.py`

**Interfaces:**
- Produces: `PanelWatcher(platform, config, recognizer, stop_event, on_progress=None, *, clock=time.monotonic, on_detected=None)`。
- 與原 watcher 一致：`requested: threading.Event`；`start(win)`、`close()`、`tick()`、`snapshot() -> SequenceSnapshot`、`fail(reason)`、`wait_ready()`、`validate_prompt(round_id) -> bool`、`begin_submit(round_id) -> str | None`、`mark_clicked(round_id)`、`wait_complete(round_id) -> bool`、`rearm(round_id)`。
- 新增 `submission_target(round_id: int) -> PanelTarget`，限最後驗證通過的同回合 target，無有效資料時 ValueError。
- Consumes: Task 2 classifier、Task 3 recognizer、Task 4 PanelRound，既有 `capture_region`／`geometry`／`SequenceSnapshot`。

- [ ] **5.1 建立 helpers 與第一個 RED，重用現有 fakes。**

```python
# tests/core/test_sequence_panel_helpers.py
import threading
from types import SimpleNamespace
import numpy as np
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from tests.fakes import FakeScreenCapture, FakeWindowManager, FakeOcrEngine


def make_panel_watcher(boxes=(), recognizer=None):
    from keyboard_executor.core.sequence_panel_watcher import PanelWatcher
    now, calls = [0.0], []
    win = WindowInfo(1, "panel-test", "app", 0, 0, 500, 500, True)
    platform = SimpleNamespace(
        screen_capture=FakeScreenCapture(np.zeros((300, 400, 3), np.uint8)),
        window_manager=FakeWindowManager([win]), ocr_engine=FakeOcrEngine(list(boxes)),
    )
    def recognize(samples, **kwargs):
        calls.extend(samples)
        return []
    config = sequence_config_from_dict(
        {"enabled": True, "mode": "panel", "panel_region": [0, 0, 400, 300]})
    stop = threading.Event()
    watcher = PanelWatcher(platform, config,
        recognizer or SimpleNamespace(recognize=recognize), stop, clock=lambda: now[0])
    return watcher, platform, win, now, stop, calls
```

```python
# tests/core/test_sequence_panel_watcher.py
from tests.core.test_sequence_panel_helpers import make_panel_watcher
from tests.core.test_sequence_watcher import eventually


def test_idle_empty_ocr_never_calls_ai():
    watcher, platform, win, now, stop, calls = make_panel_watcher()
    try:
        watcher.start(win)
        eventually(lambda: bool(platform.screen_capture.captures))
        for value in (1.0, 2.0, 3.0):
            count = len(platform.screen_capture.captures)
            now[0] = value
            watcher.tick()
            eventually(lambda: len(platform.screen_capture.captures) > count)
        assert calls == []
        assert not watcher.requested.is_set()
        assert not stop.is_set()
    finally:
        watcher.close()
```

- [ ] **5.2 跑新 watcher 測試確認 RED；另用 entered／release Event 測試 slow OCR，不以固定 sleep 判斷 worker 已完成。**
- [ ] **5.3 實作 capture／OCR／AI 三個 job 與獨立 supervisor。** 鎖內只更新狀態及工作擁有權，鎖外才 capture／recognize／progress。idle 只有 latest OCR pending；命中將同一張 PanelFrame 註冊回合及 AI queue。active OCR／AI queue 合計最多 30 張；每批 AI 最多 3 張。

```python
# OCR 結果到達時的必要授權流程，須在有效 generation／geometry 檢查之後。
state = classify_sequence_prompt(boxes)
if self._round is None and state == "present":
    self._round_serial += 1
    self._round = PanelRound(self._round_serial, frame, self._config.panel_region)
    self._round.base.check_time(self._clock())
    self.requested.set()
if self._round is not None:
    self._round.observe_prompt(frame, state, self._clock())
    if state == "present" and self._round.base.phase in {"COLLECTING", "READY", "SUBMITTING"}:
        self._round.register(frame)
        self._ai_pending.append(frame)
```

實作時每次 append 前檢查 total queue capacity，取得 deadline 後禁止啟動過期 job；不能只依此片段而省略 supervisor 的 fail／stop。每個 job token 綁 generation；AI token 另綁 round ID 與請求 deadline=min(now+10,round deadline)。supervisor 不等待 provider 配合就能 stop；timeout 後不再 spawn 另一個 AI 取代被卡住的 worker。

- [ ] **5.4 加完整時間／佇列安全測試再完成生命週期。**

| 測試情境 | 應觀察的結果 |
| --- | --- |
| OCR 擋住，時鐘到 26 秒才回 present | deadline=30、已過提交 cutoff，stop，AI calls=0 |
| 第一張圖包含 index 1，OCR 下一秒才完成 | AI 第一個 sample 是原圖及原 ID，不是新截圖 |
| OCR absent／unknown | 該 sample 不送 AI；idle 不設 requested |
| AI 卡住，時鐘依序增加 1／2／3 秒 | 每秒仍有新的 capture，最多一個 AI worker |
| AI 不理取消，超過請求 10 秒 | stop 設定、晚到不 apply、不開第二個 worker |
| progress callback 擋住且跨過 cutoff | supervisor 仍停止，不被 callback 鎖住 |
| queue overflow | fail，沒有舊圖丟棄後繼續送出 |
| 確認時已有在途 AI | token 作廢，晚到 ValueError 不污染 VERIFYING |
| 舊 runtime 關閉後同 handle 新 runtime 啟動 | 舊回呼不能設定新 stop／requested |

- [ ] **5.5 validate_prompt 強制擷取新樣本，等待同回合 OCR＋AI 的有效穩定定位；不要回傳僅有字元的 READY。** while loop 必須檢查 stop、deadline 及 phase。對外 snapshot 的 READY 是聯合門檻，base READY 但 target 缺失時仍顯示 COLLECTING。mark_clicked 取消 AI，僅用之後的 OCR absent 做確認。
- [ ] **5.6 rearm 清除本回合 queue、target、OCR／字元快取；close 可重複呼叫，screen capture thread-local 資源在 finally 關閉。**
- [ ] **5.7 跑 panel watcher＋原 watcher＋`tests/core/test_sequence_safety.py`，記錄 GREEN。**

### Task 6: 安全點位提交、runtime 分流與 OCR 擁有權

**Files:**
- Modify: `src/keyboard_executor/core/sequence_submitter.py`
- Modify: `src/keyboard_executor/app/sequence_input_service.py`
- Test: `tests/core/test_sequence_submitter.py`
- Test: `tests/app/test_sequence_input_service.py`
- Test: `tests/core/test_visual_intervention.py`

**Interfaces:**
- Extend: `SequenceSubmitter(platform, config, watcher, stop_event, *, clock=time.monotonic, target_provider=None)`；`target_provider: Callable[[int], PanelTarget] | None`。
- Preserve: 舊 manual 沒有 target_provider 時沿用 config 點位，不更改既有測試 fake 必須實作的方法。
- Service panel 分支：`PanelRecognizer`＋`PanelWatcher`＋`SequenceSubmitter(target_provider=watcher.submission_target)`。

- [ ] **6.1 寫 RED：panel runtime 建立時不發出任何 provider request，仍共用 OCR。**

```python
def test_panel_runtime_has_no_ai_preflight():
    from keyboard_executor.app.sequence_input_service import build_sequence_runtime
    platform, backend = make_platform()
    engine = FakeOcrEngine()
    platform = replace(platform, ocr_engine=engine, screen_capture=FakeScreenCapture())
    data = script_data()
    data["settings"]["sequence_input"] = {
        "enabled": True, "mode": "panel", "panel_region": [0, 0, 400, 300]}
    calls = []
    class Provider:
        def stream_chat(self, *args, **kwargs):
            calls.append(args)
            raise AssertionError("panel startup must not call AI")
    runtime = build_sequence_runtime(
        Settings(ai_provider="openai", ai_model="custom", ai_api_key="key"), None,
        script_from_dict(data), platform, threading.Event(), None,
        provider_factory=lambda *args, **kwargs: Provider())
    try:
        assert calls == []
        assert backend.calls == []
        assert runtime.watcher._platform.ocr_engine is engine
    finally:
        runtime.close()
```

- [ ] **6.2 跑上述單測，確認是 panel 分流／零呼叫行為 RED。**
- [ ] **6.3 提交器於 validate_prompt 後取得不可變 target，檢查 round ID、geometry、兩秒新鮮度及點位範圍。** 在第一個原生 click 的 checked callback 再檢查 target age；OS 查詢或滑鼠移動拖延超過兩秒也不能點。之後仍維持每個字元／confirm 的 stop、phase、deadline／geometry 檢查。

```python
if self._target_provider is not None:
    target = self._target_provider(rid)
    if (target.round_id != rid or target.window_geometry != expected_geometry
            or not 0 <= self._clock() - target.captured_at <= 2.0):
        raise RuntimeError("面板定位已失效，未輸入")
    input_point, confirm_point = target.input_point, target.confirm_point
else:
    input_point, confirm_point = self._config.input_point, self._config.confirm_point
```

- [ ] **6.4 修改 service 分支；manual 的既有 preflight 保持不動，panel 沒有任何自動 preflight。** OCR 包裝及 chat 組裝沿用同一個 ProcessOcrEngine／owned_ocr，任何 constructor 失敗都 close 已建立資源。AI provider 驗證維持 API key／subscription 兩種路徑，不在新 watcher 實作第二份 auth。

```python
if config.mode == "panel":
    recognizer = PanelRecognizer(provider)
    watcher = PanelWatcher(shared_platform, config, recognizer, stop_event, on_progress)
    submitter = SequenceSubmitter(shared_platform, config, watcher, stop_event,
                                 target_provider=watcher.submission_target)
else:
    recognizer = SequenceRecognizer(provider)
    preflight(recognizer, stop_event)
    watcher = SequenceWatcher(shared_platform, config, recognizer, stop_event, on_progress)
    submitter = SequenceSubmitter(shared_platform, config, watcher, stop_event)
```

將分支放在既有 try／cleanup 覆蓋範圍；不把 OCR 資源移到清理保護之外。上述為組裝分支，原有 auth／capability／chat／VisualIntervention 邏輯保留。

- [ ] **6.5 加 stale target、假 target round ID、callback 阻塞、兩種模式共用 OCR 一次 close、首次真實請求 schema 失敗、chat 草稿中斷及取消測試。** panel 沒有 OCR 或 screen_capture 時執行前清楚報錯，backend calls=[]。
- [ ] **6.6 跑 submitter、service、visual_intervention 與原 safety 測試，記錄 GREEN。**

### Task 7: 單一框選介面與舊設定轉換

**Files:**
- Modify: `src/keyboard_executor/app/sequence_input_dialog.py`
- Modify: `src/keyboard_executor/app/script_editor.py`
- Test: `tests/app/test_sequence_input_dialog.py`
- Test: `tests/app/test_script_editor_widget.py`
- Read: `src/keyboard_executor/app/region_picker.py`

**Interfaces:**
- Preserve: dialog constructor、`config()`、`set_region(kind, region)`、`set_point(kind, point)`。
- New dialog 沒有既有 config 時明確用 `SequenceInputConfig(mode="panel")`，不是改 dataclass 的 legacy 預設。
- panel 的 `coordinate_edits` 只有 panel_region；舊模式仍保有四個手動欄位。`set_region("panel", ...)` 可供測試及 picker 共用。
- 新增「改用單一框選」按鈕；只有成功框選才將完整的新 panel 設定替換舊設定，Esc／失敗不得改模式或值。

- [ ] **7.1 寫 RED：新對話框只需一個 region，文案明示 OCR-first。**

```python
def test_new_dialog_uses_one_panel_region(qapp):
    from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
    dialog = SequenceInputDialog()
    assert dialog.config().mode == "panel"
    dialog.enabled_check.setChecked(True)
    dialog.set_region("panel", (10, 20, 400, 300))
    config = dialog.config()
    assert config.enabled
    assert config.panel_region == (10, 20, 400, 300)
    assert set(dialog.coordinate_edits) == {"panel_region"}
    assert "OCR" in dialog.policy_label.text()
    assert "30 秒" in dialog.policy_label.text()
```

- [ ] **7.2 跑新測試確認 RED；既有預設 dialog 的手動測試改為傳入明確 legacy config，測試舊行為而不是硬保留舊 UI 預設。**
- [ ] **7.3 在現有 `_pick` 接上 panel_region，同一套視窗定位、DPI、越界和取消處理；不要另做一份 picker。** 重建欄位前先完整驗證新設定，框選中不發 AI 請求。

```python
# 新模式 config() 的資料來源
if self._mode == "panel":
    text = self.coordinate_edits["panel_region"].text().strip()
    return sequence_config_from_dict({
        "enabled": self.enabled_check.isChecked(), "mode": "panel",
        "panel_region": parse_int_list("panel_region", text, 4) if text else None,
    })
```

- [ ] **7.4 文案及 editor status：panel 顯示「OCR 偵測 → AI 辨識／總時限 30 秒」，legacy 明示舊版手動。** AI 用量提示只描述 OCR 命中之後；移除新模式「啟動先做 AI 測試」文案。
- [ ] **7.5 加 Review Focus 5：既有設定打開／取消原樣、轉換時 Esc 原樣、成功框選才切換、undo／redo 可回到原模式、停用缺 region 可保存。** 無目標、移動視窗、無效範圍及非整數 DPI 仍需有測試。
- [ ] **7.6 跑 dialog、editor、transfer 相關測試，記錄 GREEN。**

### Task 8: 全流程回歸、說明及交付證據

**Files:**
- Create: `tests/core/test_sequence_panel_flow.py`
- Modify: `tests/core/test_sequence_panel_helpers.py`
- Modify: `README.md`
- Modify: `docs/sequence-input-manual-checklist.md`
- Modify: `docs/sequence-input-implementation-report.md`
- Test: `tests/core/test_rule_engine.py`
- Test: `tests/test_cli_main.py`

**Interfaces:**
- Consumes: Task 1–7 的正式 runtime／watcher／submitter，不以另一份模擬實作代替。
- Test helper 新增 `run_panel_flow(*, readings, prompt_states, fault=None) -> dict`：以 fake clock／backend、Event 協調真實 watcher／submitter。返回 `typed: str`、`confirm_clicks: int`、`completed: bool`、`ai_calls_before_trigger: int`、`ai_calls_after_confirm: int`、`stopped: bool`；fault 支援 `cancel`、`focus`、`geometry`、`timeout`、`conflict`、`unknown_after_ready`。helper 必須 finally 釋放所有 Event 並 close runtime。

- [ ] **8.1 先寫真正跨元件的成功案例與安全 fault 參數化案例。**

```python
import pytest
from tests.core.test_sequence_panel_helpers import run_panel_flow


def test_single_region_ocr_then_ai_full_flow():
    result = run_panel_flow(readings=[(3, "C"), (1, "A"), (2, "B")],
                            prompt_states=["absent", "unknown", "present", "present",
                                           "present", "present", "absent", "absent"])
    assert result["typed"] == "ABC"
    assert result["confirm_clicks"] == 1
    assert result["completed"]
    assert result["ai_calls_before_trigger"] == 0
    assert result["ai_calls_after_confirm"] == 0


@pytest.mark.parametrize("fault", ["cancel", "focus", "geometry", "timeout",
                                   "conflict", "unknown_after_ready"])
def test_unsafe_round_never_confirms(fault):
    result = run_panel_flow(readings=[(1, "A"), (2, "B"), (3, "C")],
                            prompt_states=["present"] * 6, fault=fault)
    assert result["confirm_clicks"] == 0
    assert not result["completed"]
    assert result["stopped"]
```

helpers 用 frame marker 與 Event 決定 OCR／AI 回覆，不把測試變成 wall-clock sleep；成功案例需先讓兩次穩定 AI 定位滿足一秒及兩秒時效條件，再進入提交，最後兩張 absent 必須在 click 記錄之後拍攝。

- [ ] **8.2 跑 flow 測試，修正任何跨元件時序問題前先保留 RED 證據，必要時新增較小回歸案例。** 另外跑 panel 模式 CLI／rule-engine 無 runtime 時應拒絕的測試，不只 legacy 模式。
- [ ] **8.3 更新 README／手動驗收清單／實作報告。** 明確寫：只框一次、本機 OCR 白名單、0.8 門檻、漏讀不會轉 AI、OCR 命中才有 AI 用量、30 秒是停止上限、舊手動模式可繼續用、實機尚未驗收的部分。不要把 fake 測試當實際成功率。
- [ ] **8.4 在 Windows 跑完整 pytest，保存 log 及 exit code。**

```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -Command 'Set-Location "D:\keyboard-executor"; $env:PYTHONPATH="D:\keyboard-executor\src"; $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\ke-build-venv\Scripts\python.exe" -m pytest -q; exit $LASTEXITCODE' > /tmp/ke-sequence-panel-windows-tests.log 2>&1
```

完整套件必須 exit 0 才宣稱通過；skips 與 warnings 如實報告。不得用上一次 1497 passed 代替本次輸出。

- [ ] **8.5 跑 `git diff --check`，並對新增未追蹤檔案另做 whitespace 檢查；核對工作區始終為 main，沒有覆蓋原有變更。**
- [ ] **8.6 依使用者選擇的執行方式完成一次獨立唯讀審查，修正前重現問題，修正後重跑受影響及完整測試。** 此工作區含既有未提交修改，review base 必須是本次開工備份／差異，不可把 main HEAD 當本次功能基線。
- [ ] **8.7 回報程式完成範圍、Windows 實測數字、尚未驗收的實機辨識與 exe 是否更新。** 只有另外獲授權打包時才沿用既有 spec 建置、備份舊 exe、檢查新模組收錄與 GUI 啟動，不默默覆蓋成品。

## 計畫自我檢查

- Spec §1–3：Tasks 1、7；同分支、舊設定保留與版本控制限制已列於全域邊界。
- Spec §4：Tasks 2、3；無文字不是 absent、白名單、不確定不猜、嚴格型別與 crop-only 傳輸均有測試。
- Spec §5：Tasks 4、5；trigger frame 時間、獨立取樣、有界 queue、OCR gate、AI 10 秒、25／30 秒及晚到結果隔離。
- Spec §6：Tasks 4、6、8；IoU、safe interior、兩秒新鮮度、單次確認、取消與 OCR-only 消失驗證。
- Spec §7：Tasks 6、8；原聊天優先權、OCR ownership、零 preflight、CLI 防呆。
- Spec §8–9：Task 8；實機與模型限制如實記錄。
- 五個 Review Focus 已指定對應測試；所有跨 task 型別／方法在前述 Interfaces 定義，未增加第三方依賴。

## 執行方式建議

建議 **Native：同一對話由目前 agent 依序實作，最後一次獨立唯讀審查**。理由：OCR、回合、定位與取消介面的相依性高，同一實作者較容易保持時序契約一致，也避免多個 agent 同時改動這個已有大量未提交內容的主工作目錄。

若使用者選擇 subagent-driven，也只能在同一工作目錄依序執行任務、嚴禁建立新分支或 worktree；不可同時寫同一批共享檔案。本次使用者已選擇 Native，依序實作及獨立審查已完成。其後使用者另行授權打包，exe 已於 2026-10-02 更新並通過啟動檢查，詳見 `docs/sequence-input-implementation-report.md`。
