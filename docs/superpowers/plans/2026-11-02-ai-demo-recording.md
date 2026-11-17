# AI 示範錄製 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用者手動示範一圈練功，AI 看「按鍵時間軸＋500ms 截圖」產生練功腳本與回起點腳本，並自動試跑、比對、修正最多 N 輪。

**Architecture:** 純邏輯放 `core/ai_demo/`（時間軸、關鍵幀挑選、提案解析、提示詞、試跑循環狀態機），以注入的 ports 介面和外界溝通，便於單元測試。`app/` 層負責截圖執行緒、Qt 對話框、AI 面板入口，以及把 ports 接到既有 `RunController`、`ChatProvider`、`ScriptStorage`、`TemplateStore`。整個試跑循環在單一 `Worker` 背景執行緒內以阻塞方式執行。

**Tech Stack:** Python 3.13、PySide6、numpy、cv2、pytest（offscreen Qt）。

**Spec:** `docs/superpowers/specs/2026-11-02-ai-demo-recording-design.md`

## Global Constraints

- UI 與訊息一律繁體中文。
- 模組名稱不可用 `demo`：`keyboard_executor.demo` 已存在（CLI demo）。一律用 `ai_demo` 前綴。
- 截圖間隔 500ms；送 AI 的關鍵幀預設上限 30 張（設定 `ai_demo_max_frames`，範圍 4–100）；長邊縮到 1280px 以內。
- 試跑輪數預設 3（設定 `ai_demo_max_rounds`，範圍 1–10）；每輪主腳本最多跑「示範時間 × 2」。
- 回起點容許半徑 8px（小地圖視窗相對座標）。
- 同一原因中斷連續 2 次就結束循環。
- 不可覆蓋使用者既有腳本：名稱衝突用 `ai_panel._numbered_name`（搬到共用位置，見 Task 6）。
- Player 只能**新增** `on_step` 事件種類，不可改動既有的 `step` / `timed_key` 內容。
- 測試指令（從 WSL 執行）：`cd /mnt/d/keyboard-executor && QT_QPA_PLATFORM=offscreen python.exe -m pytest -q <路徑>`

## Review Focus

1. **示範中途角色沒被偵測到黃點**（小地圖被遮住、`find_player_dot` 回 None）：起點為 None 時不可開始錄製，要提示框選範圍不對；中途 None 只記成 `dot: null`，不中斷錄製。→ Task 5、Task 7 測試。
2. **AI 回了文字但沒呼叫工具、或 JSON 不合法**：重試一次（附錯誤訊息），第二次仍失敗就結束循環並顯示原因，不可卡在「AI 分析中」。→ Task 6 測試。
3. **使用者在試跑中按 F10 / 面板停止**：主腳本立即停、整個循環結束、不再呼叫 AI。→ Task 6、Task 8 測試。
4. **示範只有 3 秒、或只有滑鼠沒有鍵盤**：關鍵幀與時間軸仍要能產生（至少第一張與最後一張），不可除以零或送空清單。→ Task 3 測試。
5. **AI 給的模板裁切範圍超出截圖或小於 8×8**：整份提案退回 AI 重試，不可存出空白模板。→ Task 4 測試。

---

### Task 1: Player 回報等待與分支結果

**Files:**
- Modify: `src/keyboard_executor/core/player.py`（`_run_wait`、`_run_if`）
- Modify: `src/keyboard_executor/app/logview.py`
- Test: `tests/core/test_player_events.py`（新檔）、`tests/app/test_logview.py`

**Interfaces:**
- Produces: 新 `on_step` 事件
  - `{"kind": "wait_result", "index": int, "type": str, "matched": bool, "elapsed_ms": int, "on_timeout": str | None}`（`matched=True` 時 `on_timeout` 為 None）
  - `{"kind": "branch", "index": int, "type": str, "taken": "then" | "else"}`
  - `index` 為該動作在其所在清單的序號；Player 需記住目前 step 的 index（在 `_run_actions` 發 `step` 時存到 `self._current_index`）。

- [ ] **Step 1: 寫失敗測試** `test_wait_timeout_emits_wait_result`：腳本 `[wait_text(pattern="X", timeout_ms=0, on_timeout="continue")]`，FakeOcr 不回任何字 → 事件中有 `{"kind": "wait_result", "index": 0, "matched": False, "on_timeout": "continue"}`。`test_wait_hit_emits_matched_true`。`test_if_text_emits_branch_else`：if_text 未命中 → `{"kind": "branch", "index": 0, "taken": "else"}`。`test_existing_step_events_unchanged`：`step` 事件的 key 集合仍是 `{"kind","index","total","type","label"}`。
- [ ] **Step 2: 執行確認失敗**：`... -m pytest -q tests/core/test_player_events.py` → FAIL（沒有 wait_result）。
- [ ] **Step 3: 實作**：`_run_wait` 在 `hit` 判定後、處理 on_timeout 前發事件；`_run_if` 在選定 branch 後發事件（序列暫停重試迴圈內每次判定都發）。`elapsed_ms` 用 `self._action_time()` 前後差。
- [ ] **Step 4: logview**：`format_progress` 為兩個新 kind 加中文格式（`等待 #3 逾時（continue）`、`判斷 #2 走 else`）；`_KIND_LEVEL` 兩者設為 `"DEBUG"`，預設 INFO 日誌不會多出雜訊。測試 `test_new_kinds_are_debug_level`。
- [ ] **Step 5: 跑 Player 與 logview 全部測試**：`... -m pytest -q tests/core tests/app/test_logview.py tests/app/test_run_controller.py tests/app/test_watch_controller.py` → 全 PASS。
- [ ] **Step 6: Commit** `feat(player): report wait and branch outcomes as progress events`

### Task 2: 示範事件時間軸

**Files:**
- Create: `src/keyboard_executor/core/ai_demo/__init__.py`、`src/keyboard_executor/core/ai_demo/timeline.py`
- Test: `tests/core/test_ai_demo_timeline.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class KeyHold:   key: str; start_ms: int; end_ms: int
  @dataclass(frozen=True)
  class MouseAct:  kind: str  # "click" | "drag" | "scroll"
                   t_ms: int; x: int; y: int; button: str = ""; to: tuple[int, int] | None = None; dy: int = 0
  class DemoEventLog:   # RecorderSession 的 recorder_factory；簽名 (origin, mode="simplified")
      def feed(self, event: InputEvent) -> None
      def finish(self) -> tuple[list[KeyHold], list[MouseAct]]
      def event_times_ms(self) -> list[int]   # 所有按下/點擊時間，給關鍵幀挑選
  def format_timeline(holds, mouse, dots: list[tuple[int, tuple[float, float] | None]],
                      frame_ids: list[tuple[int, str]]) -> str
  ```
- 時間一律是「相對第一個被 feed 的事件或 `start(t0_ms)` 呼叫」的毫秒。`DemoEventLog.start(t0_ms: int)` 由 controller 在開始錄製時呼叫，與截圖執行緒共用同一個 t0（`time.monotonic()` 的毫秒，和 `InputEvent.timestamp_ms` 同一時鐘——實作前確認 `hook_pynput` 的 timestamp 來源，若不同時鐘則改在 feed 時用 `time.monotonic()` 重新蓋時間戳）。

- [ ] **Step 1: 寫失敗測試**
  - `test_hold_interval_from_down_up`：down right@1200、up right@3850 → `KeyHold("right", 1200, 3850)`。
  - `test_autorepeat_down_ignored`：down right 連續三次再 up → 只有一個 KeyHold。
  - `test_unreleased_key_closed_at_finish`：只有 down → `end_ms` 等於最後事件時間。
  - `test_mouse_click_vs_drag`：down/up 位移 ≤5px 為 click，否則 drag（`to` 為放開點），座標轉視窗相對（減 origin）。
  - `test_format_timeline_lines`：輸出含 `1.20s–3.85s 按住 right（2.65s）`，事件行附最近的截圖編號（`[D3]`）與黃點座標 `黃點(112,48)`；黃點 None 印 `黃點(?)`。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**；`format_timeline` 依時間排序合併按鍵與滑鼠行。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): record key hold intervals and mouse acts for demos`

### Task 3: 關鍵幀挑選與圖片附件

**Files:**
- Create: `src/keyboard_executor/core/ai_demo/frames.py`
- Test: `tests/core/test_ai_demo_frames.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Frame:
      id: str              # "D1".."Dn"（示範）或 "R{輪}-{n}"（試跑）
      t_ms: int
      path: Path           # 原尺寸 PNG
      size: tuple[int, int]  # 原尺寸 (w, h)，實體像素
      dot: tuple[float, float] | None
      thumb: np.ndarray    # 64×36 灰階，只存在記憶體
  def make_thumb(image: np.ndarray) -> np.ndarray
  def select_keyframes(frames: list[Frame], event_times_ms: list[int], limit: int) -> list[Frame]
  def frame_attachment(frame: Frame, out_dir: Path, max_edge: int = 1280) -> dict
      # 回傳 messages.py 的內部附件 dict：{"name","media_type":"image/jpeg","data","path"}，
      # 另加 "sent_scale": 原寬/送出寬（float），供模板裁切換算
  ```
- 挑選規則（spec §7.1）：必選第一張與最後一張；每個事件時間取「之前最近一張」與「之後最近一張」為候選；再加入與前一張已選幀 thumb 平均絕對差 > `DIFF_THRESHOLD = 12.0` 的幀。超過 `limit` 時，保留首尾，其餘依「與前一張的差異量」由大到小取，最後依時間排序回傳。`limit < 2` 視為 2。

- [ ] **Step 1: 寫失敗測試**：`test_always_keeps_first_and_last`；`test_respects_limit`（100 幀、limit 30 → 30 張且首尾在內、依時間排序）；`test_static_screen_without_events_only_first_last`；`test_single_frame`（1 幀 → 1 張）；`test_attachment_downscales_to_1280`（2560×1440 → 送出 1280×720、`sent_scale == 2.0`、path 檔案存在且 jpeg 可解）。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**（cv2.resize INTER_AREA、cv2.imencode `.jpg` 品質 85、base64）。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): select keyframes and build image attachments`

### Task 4: 示範工具 schema 與提案解析

**Files:**
- Modify: `src/keyboard_executor/core/ai/tools.py`
- Create: `src/keyboard_executor/core/ai_demo/proposal.py`
- Test: `tests/core/test_ai_demo_proposal.py`

**Interfaces:**
- Produces:
  ```python
  # tools.py
  TOOL_DEMO = "propose_demo_scripts"
  def demo_tools_anthropic() -> list[dict]; def demo_tools_openai() -> list[dict]   # 只含 TOOL_DEMO
  # TOOL_DEMO 不加入 TOOL_NAMES / _TOOLS（一般聊天不提供）
  # proposal.py
  class DemoProposalError(ScriptValidationError)
  @dataclass(frozen=True)
  class TemplateCrop: name: str; frame_id: str; rect: tuple[int, int, int, int]   # 送出圖片座標
  @dataclass(frozen=True)
  class DemoProposal:
      goal: str; verdict: str | None; changes: str
      main_script: Script | None; return_script: Script | None; templates: tuple[TemplateCrop, ...]
  def parse_demo_proposal(args: dict, *, sent_sizes: dict[str, tuple[int, int]],
                          require_main: bool, require_return: bool) -> DemoProposal
  ```
- schema 欄位照 spec §7.3：`goal`(string, required)、`verdict`(enum success/needs_fix)、`changes`(string)、`main_script`(=`_SCRIPT_SCHEMA`)、`return_script`(=`_SCRIPT_SCHEMA`)、`templates`(array of `{name, frame, rect:[x,y,w,h]}`)。
- 驗證：腳本走 `script_from_dict`；`verdict == "success"` 時 `main_script` 可省略；模板 `frame` 必須在 `sent_sizes`、rect 完全落在該圖內、w/h ≥ 8、名稱不含 `/ \`、不可重複。任何錯誤丟 `DemoProposalError`（繁中訊息，會原文回給 AI）。

- [ ] **Step 1: 寫失敗測試**：`test_valid_first_proposal`；`test_missing_return_on_first_raises`；`test_success_verdict_without_main_ok`；`test_template_out_of_bounds_raises`；`test_template_too_small_raises`；`test_unknown_frame_raises`；`test_invalid_action_type_raises`；`test_demo_tool_not_in_general_tools`（`TOOL_DEMO not in [t["name"] for t in as_anthropic()]`）。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 執行確認通過**（含既有 `tests/core/test_ai_manual_tools.py`）。
- [ ] **Step 5: Commit** `feat(ai-demo): add demo proposal tool and validation`

### Task 5: 提示詞與訊息組裝

**Files:**
- Modify: `src/keyboard_executor/core/ai/manual.py`
- Create: `src/keyboard_executor/core/ai_demo/prompt.py`
- Create: `src/keyboard_executor/core/ai_demo/outcome.py`（只放 `RunOutcome`）
- Test: `tests/core/test_ai_demo_prompt.py`

**Interfaces:**
- Consumes: Task 2 `format_timeline`、Task 3 `Frame` / `frame_attachment`
- Produces:
  ```python
  # manual.py
  DEMO_GUIDE: str
  def build_demo_system_prompt() -> str      # APP_MANUAL + BOUNDARY + DEMO_GUIDE（不含「沒有選中腳本」那行）
  # outcome.py
  @dataclass
  class RunOutcome:
      ended: str   # "time_up" | "finished" | "aborted" | "stopped" | "interrupted"
      reason: str = ""; frames: list[Frame] = field(default_factory=list)
      events: list[dict] = field(default_factory=list); dot_trace: list = field(default_factory=list)
  # prompt.py
  @dataclass
  class DemoRecording:
      frames: list[Frame]; holds: list[KeyHold]; mouse: list[MouseAct]
      event_times_ms: list[int]; duration_ms: int
      start_dot: tuple[float, float]; minimap_region: tuple[int, int, int, int]
      window_title: str; goal_text: str
  def initial_message(rec: DemoRecording, limit: int, out_dir: Path) -> tuple[dict, dict[str, float], dict[str, tuple[int, int]]]
  def fix_message(rec, run: RunOutcome, previous_script: dict, limit: int, out_dir: Path) -> tuple[dict, dict[str, float], dict[str, tuple[int, int]]]
  def return_fix_message(rec, return_script: dict, end_dot, dot_trace: list, out_dir: Path) -> tuple[dict, dict[str, float], dict[str, tuple[int, int]]]
  # 回傳 (user message, frame_id→sent_scale, frame_id→送出尺寸)
  ```
- `DEMO_GUIDE` 必須涵蓋：這是練功循環、主腳本要無限重複（外層 loop -1 或 goto 0）；偏好 wait_image/wait_text/if_* 取代寫死的 delay；長按用 `hold_ms`；回起點腳本用 `minimap_move`，`region` 用給定的小地圖範圍；`success` 判定標準照 spec §7.2 固定說明；圖片座標與視窗座標換算說明（每張圖標 `[ID] 送出尺寸 w×h，1px = s 視窗像素`）；只能呼叫 `propose_demo_scripts`。
- 修正訊息的文字包含：本輪 `RunOutcome.ended`、`error`、Player 事件摘要（`step` 只列序號序列並壓縮重複，`wait_result`/`branch` 全列，總長截到 4000 字）、上一版主腳本 JSON。圖片配額：示範與本輪各 `limit // 2`。

- [ ] **Step 1: 寫失敗測試**：`test_initial_message_has_images_and_timeline`（images 數 ≤ limit，文字含 `D1` 與目的說明）；`test_fix_message_splits_quota`（limit 30 → 示範 ≤15、本輪 ≤15）；`test_fix_message_truncates_long_event_log`；`test_system_prompt_has_demo_guide_without_no_selection_line`。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): build demo and fix prompts`

### Task 6: 試跑循環狀態機

**Files:**
- Create: `src/keyboard_executor/core/ai_demo/loop.py`
- Create: `src/keyboard_executor/core/naming.py`（把 `ai_panel._numbered_name` 搬來成 `numbered_name`，`ai_panel` 改 import；行為不變）
- Test: `tests/core/test_ai_demo_loop.py`

**Interfaces:**
- Consumes: Task 4 `DemoProposal`、`DemoProposalError`；Task 5 `DemoRecording`、`RunOutcome`
- Produces:
  ```python
  class DemoPorts(Protocol):
      def ask_ai(self, kind: str, payload: dict) -> DemoProposal   # kind: "initial"|"fix"|"return_fix"；錯誤丟 DemoProposalError 或 AiProviderError
      def save_version(self, proposal: DemoProposal, version: int) -> None   # 存 session 版本檔＋模板
      def apply_version(self, version: int) -> str        # 寫進腳本庫，回傳主腳本名稱
      def run_main(self, max_seconds: float) -> RunOutcome
      def run_return(self) -> RunOutcome
      def read_dot(self) -> tuple[float, float] | None
      def wait_user_reset(self, message: str) -> bool     # True=繼續、False=結束
      def report(self, event: dict) -> None               # {"stage": ..., "round": n, ...} 給 UI
      def stopped(self) -> bool
  @dataclass
  class RoundRecord: round: int; version: int; ended: str; verdict: str | None; changes: str
  @dataclass
  class DemoLoopResult:
      status: str   # "success" | "max_rounds" | "stopped" | "interrupted" | "user_ended" | "ai_failed"
      message: str; rounds: list[RoundRecord]; library_version: int | None; untested_version: int | None
  def run_demo_loop(rec: DemoRecording, ports: DemoPorts, *, max_rounds: int,
                    start_radius: float = 8.0, demo_time_factor: float = 2.0) -> DemoLoopResult
  ```
- 流程（spec §5，照順序實作）：
  1. `ask_ai("initial")`；`DemoProposalError` 時把錯誤放進 payload `{"error": msg}` 再問一次；仍錯 → `ai_failed`。`AiProviderError` 不重試，直接 `ai_failed`。
  2. `save_version(p, 1)`、`apply_version(1)`。
  3. 每輪：`_ensure_start()` → `run_main(duration_s * factor)` → 依 `ended`：`stopped` → 結束 `stopped`；`interrupted` → 同 reason 計數 +1，達 2 → `interrupted`，否則不計輪重跑本輪；其他（`time_up`/`finished`/`aborted`）→ 這版標記為已試跑（`library_version = 目前版本`）→ `ask_ai("fix", {...})`（同樣錯誤重試一次）→ `success` 結束；不是最後一輪 → `save_version`、`apply_version`、下一輪；最後一輪 → 只 `save_version`，記 `untested_version`，結束 `max_rounds`。
  4. `_ensure_start()`：`run_return()` → `read_dot()` 距起點 ≤ radius 即成功；否則 `ask_ai("return_fix")` → 存新版本（僅更新回起點腳本）→ `apply_version` → 再試一次；仍失敗 → `wait_user_reset(訊息)`，False → `user_ended`。`run_return` 的 `stopped` 同樣立即結束。
  5. 每個階段開始前檢查 `ports.stopped()`，為 True 立刻回 `stopped`，之後不再呼叫任何 port。

- [ ] **Step 1: 寫失敗測試**（用 FakePorts 記錄呼叫順序）：`test_success_on_first_fix`；`test_runs_max_rounds_and_keeps_last_tested`（3 輪皆 needs_fix → `library_version == 3`、`untested_version == 4`、apply 只被呼叫 3 次）；`test_stop_during_run_ends_without_ai_call`；`test_interrupted_twice_same_reason_ends`；`test_interrupted_once_reruns_without_counting`；`test_invalid_proposal_retried_once`；`test_return_fix_then_user_reset`；`test_user_ends_on_reset_prompt`；`test_provider_error_not_retried`。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**＋搬 `numbered_name`（`tests/app/test_ai_panel.py` 須仍通過）。
- [ ] **Step 4: 執行確認通過**：`... tests/core/test_ai_demo_loop.py tests/app/test_ai_panel.py`。
- [ ] **Step 5: Commit** `feat(ai-demo): add auto test-and-fix loop`

### Task 7: 截圖取樣與 session 存檔

**Files:**
- Create: `src/keyboard_executor/app/ai_demo_capture.py`
- Create: `src/keyboard_executor/storage/ai_demo_sessions.py`
- Test: `tests/app/test_ai_demo_capture.py`、`tests/storage/test_ai_demo_sessions.py`

**Interfaces:**
- Consumes: Task 3 `Frame`、`make_thumb`；`route_recorder.MinimapSampler.read_once` 的讀點邏輯（抽成模組函式 `read_dot(capture, wm, win, region)` 共用，MinimapSampler 改呼叫它）
- Produces:
  ```python
  class FrameSampler:
      def __init__(self, capture_factory, window_manager, win, minimap_region, out_dir: Path,
                   prefix: str, *, t0_ms: int, interval: float = 0.5, clock=time.monotonic)
      def start(self) -> None
      def stop(self) -> list[Frame]
  def read_dot(capture, window_manager, win, region) -> tuple[float, float] | None
  class AiDemoSessionStore:
      def __init__(self, root: Path, keep: int = 10)
      def create(self) -> Path                         # root/ai_demos/<YYYYmmdd-HHMMSS>/，並清理只留最新 keep 個
      def save_timeline(self, session: Path, data: dict) -> None   # timeline.json
      def save_version(self, session: Path, version: int, data: dict) -> None   # round_{version}.json：{main, return, changes, verdict}
      def load_version(self, session: Path, version: int) -> dict
  ```
- 每次取樣：截目標視窗內容區（照 `MinimapSampler.read_once` 的 scale 換算）、存 `out_dir/{prefix}{n}.png`、同一張圖上裁小地圖範圍讀黃點（不必再截一次）、建 `Frame`。單次擷取失敗只記 warning、跳過該張。
- `root` 用 MainWindow 的 `self._data_dir`。

- [ ] **Step 1: 寫失敗測試**：`test_sampler_writes_frames_with_ids`（FakeScreenCapture、clock 注入，跑 3 次取樣 → D1..D3 檔案存在、`t_ms` 遞增）；`test_sampler_survives_capture_error`；`test_read_dot_none_when_no_dot`；`test_store_keeps_latest_10`；`test_version_roundtrip`。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**（含 `MinimapSampler` 改呼叫 `read_dot`，`tests/app/test_route_recorder.py` 須仍通過）。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): sample window frames and store demo sessions`

### Task 8: Controller（接上 ports）

**Files:**
- Create: `src/keyboard_executor/app/ai_demo_controller.py`
- Test: `tests/app/test_ai_demo_controller.py`

**Interfaces:**
- Consumes: Task 6 `run_demo_loop`、`DemoPorts`；Task 7 `FrameSampler`、`AiDemoSessionStore`、`read_dot`；`RunController`；`make_provider`；`TemplateStore.save_template`；`core.naming.numbered_name`
- Produces:
  ```python
  class AiDemoController(QObject):
      progress = Signal(dict)            # ports.report 轉來的事件
      finished = Signal(object)          # DemoLoopResult
      reset_needed = Signal(str)         # 需要使用者帶回起點
      active_changed = Signal(bool)
      def __init__(self, *, get_settings, auth_service, script_storage, templates,
                   sessions: AiDemoSessionStore, get_platform, provider_factory=make_provider,
                   run_controller_factory=RunController, worker_factory=Worker)
      def start_loop(self, rec: DemoRecording, session: Path, win) -> None
      def stop(self) -> None                     # 設 stop flag＋停目前回放
      def interrupt(self, reason: str) -> None   # 規則觸發時由 MainWindow 呼叫
      def resume_after_reset(self, proceed: bool) -> None
      def apply_version(self, session: Path, version: int) -> str   # 總結卡片「退回此版」
      @property
      def active(self) -> bool
  ```
- 實作重點：
  - 自建**獨立** `RunController`（不可用 MainWindow 那一個）。
  - `run_main`：建 job 後在同一個背景執行緒直接呼叫 `job(progress)`；另開 `threading.Timer(max_seconds, rc.stop)`；同時跑 `FrameSampler(prefix=f"R{round}-")` 並收集 progress 事件。結束原因判定：自己的 stop flag → `stopped`；`interrupt()` 被呼叫 → `interrupted`（reason 用傳入字串）；Timer 觸發 → `time_up`；`PlayResult.ok` → `finished`；否則 `aborted`（reason = `result.error`）。
  - `ask_ai`：provider 建法照 `AiPanel.send_message`（api_key / subscription 兩條路）；system = `build_demo_system_prompt()`；tools 依 provider 用 `demo_tools_anthropic/openai`；`should_abort = stop flag`；沒有 `tool_call` 或名稱不是 `TOOL_DEMO` → `DemoProposalError("AI 沒有提出腳本")`。
  - `save_version`：模板依 `sent_scale` 換算回原尺寸 rect，從 `Frame.path` 讀原圖裁切，名稱改成 `f"{主腳本名}-{name}"` 後 `save_template`；腳本內引用的模板名同步替換。
  - `apply_version`：第一次決定最終名稱（`numbered_name(AI 名稱, storage.list_names())`、`-回起點` 同理），之後版本沿用同名稱覆寫自己的腳本，不會碰到其他腳本。
  - `wait_user_reset`：emit `reset_needed`，以 `threading.Event` 阻塞，直到 `resume_after_reset` 或 `stop`；同時若 `settings.discord_webhook_url` 有值，用 `core.discord_notify` 發一則通知。

- [ ] **Step 1: 寫失敗測試**（fake provider 回固定 `ChatResult(tool_call=...)`、fake run controller）：`test_runs_loop_end_to_end_with_fakes`；`test_uses_own_run_controller`；`test_stop_stops_current_run_and_loop`；`test_interrupt_marks_round_interrupted`；`test_name_conflict_gets_number`（腳本庫已有同名 → 用 `名 2`，原腳本內容不變）；`test_template_crop_scaled_back`（sent_scale 2.0、rect (10,10,20,20) → 存出 40×40）。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): wire demo loop to providers, playback and storage`

### Task 9: UI 入口、設定與主視窗整合

**Files:**
- Create: `src/keyboard_executor/app/ai_demo_dialog.py`
- Modify: `src/keyboard_executor/app/ai_panel.py`、`src/keyboard_executor/app/main_window.py`、`src/keyboard_executor/app/settings.py`、`src/keyboard_executor/app/settings_page.py`、`src/keyboard_executor/core/ai/manual.py`（APP_MANUAL 補一行功能總覽）、`README.md`
- Test: `tests/app/test_ai_demo_dialog.py`、`tests/app/test_ai_panel.py`、`tests/app/test_main_window.py`、`tests/app/test_settings.py`

**Interfaces:**
- Consumes: Task 2 `DemoEventLog`；Task 7 `FrameSampler`、`AiDemoSessionStore`；Task 8 `AiDemoController`
- Produces:
  - `Settings.ai_demo_max_frames: int = 30`（4–100）、`Settings.ai_demo_max_rounds: int = 3`（1–10），`validate_settings` 檢查範圍；設定頁 AI 區塊兩個 QSpinBox。
  - `AiDemoDialog(QDialog)`：目標視窗下拉、小地圖框選（重用 `RecorderPanel._pick_region` 用的 region picker）、目的說明輸入框（選填）、開始/停止按鈕；用 `RecorderSession(hook, origin, recorder_factory=DemoEventLog)` 處理 F9/F10。開始時先 `read_dot` 一次，None → 顯示「小地圖範圍內找不到角色黃點，請重新框選」並不開始。停止後回傳 `DemoRecording` 與 session 路徑。超過 3 分鐘時狀態列顯示提示。
  - `AiPanel`：輸入列新增「示範錄製」按鈕（AI 未設定時停用）；循環進行中顯示一個進度氣泡（階段＋輪數）與「停止」；`reset_needed` 時顯示卡片，按鈕「已帶回起點，繼續」/「結束」；`finished` 時顯示總結卡片：`goal`、每輪 `changes` 與結果、最終狀態文字，每個版本一個「退回此版」按鈕，`untested_version` 標「未試跑」。
  - `MainWindow`：建立 `AiDemoController` 傳給 `AiPanel`；`active_changed(True)` 時停用 `run_button` 與腳本快捷鍵（`ScriptHotkeyPoller` 略過觸發）；監看 progress 收到 `kind == "fire"` 且循環進行中 → `controller.interrupt(f"規則「{rule}」觸發")`；關閉視窗時 `controller.stop()`。

- [ ] **Step 1: 寫失敗測試**：`test_settings_demo_limits_validated`；`test_demo_button_disabled_without_ai`；`test_run_button_disabled_while_demo_active`；`test_rule_fire_interrupts_demo`；`test_summary_card_marks_untested_version`；`test_dialog_refuses_start_without_dot`。
- [ ] **Step 2: 執行確認失敗**。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 執行確認通過**。
- [ ] **Step 5: Commit** `feat(ai-demo): add demo recording entry, progress and summary UI`

### Task 10: 全測試、打包、實機驗收

- [ ] **Step 1: 全部測試**：`cd /mnt/d/keyboard-executor && QT_QPA_PLATFORM=offscreen python.exe -m pytest -q` → 全 PASS（記下通過數）。
- [ ] **Step 2: 打包**到新的獨立目錄（依 windows-build-env 記憶：先查有沒有正在跑的 PyInstaller，不要殺掉使用者正在用的 EXE）：`cd packaging && <venv-py> -m PyInstaller --noconfirm --distpath dist/ai-demo-record keyboard-executor.spec`。確認 log 有 `Build complete!` 且 EXE 時間戳是新的。
- [ ] **Step 3: `--help` 試開** EXE，確認可以啟動。
- [ ] **Step 4: 圖片數量實測**：用使用者目前設定的 AI 連線方式，以 30 張 1280px 圖送一次 `propose_demo_scripts`（離線用錄好的 session 重播即可，不送遊戲按鍵）。若供應商拒收，記下上限並把該供應商的預設上限調低、補測試。
- [ ] **Step 5: 回報**：EXE 路徑、測試數、需要使用者實機驗收的步驟（實機操作會送按鍵進遊戲，交給使用者執行）。
