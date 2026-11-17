# AI 腳本助手（BYO 金鑰）— 設計文件

- **日期**：2026-07-15
- **狀態**：已與需求方確認設計方向

## 1. 動機

使用者想在 App 內直接問 AI「這個功能怎麼用」，並讓 AI 幫忙產生或修改腳本。
不自建後端、不做訂閱金流：使用者自帶（BYO）Anthropic 或 OpenAI API 金鑰，
App 直接呼叫官方 API。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| 交付模式 | **BYO 金鑰**：設定頁填供應商＋model＋API key；無後端、無帳號、無金流 |
| 能力範圍 | 問答（依內建手冊）＋**產生／修改腳本**（一律預覽 → 按「套用」才落地） |
| UI 位置 | **主視窗右側可收合聊天面板**（QDockWidget） |
| 供應商 | **Anthropic 與 OpenAI 都支援**，抽 provider 介面 |
| 改當前腳本語意 | **覆寫存回＋卡片上一鍵復原**（記憶體保留改動前版本） |
| HTTP client | **只用 stdlib urllib（自解 SSE）**，不新增依賴（比照 `discord_notify.py`；避免 PyInstaller 打包膨脹） |

## 3. 架構總覽

分層比照現有慣例：core 純 Python 無 Qt，app 層是薄 Qt 件。

```
core/ai/
  provider.py            # ChatProvider 抽象介面 + ChatResult/ToolCall dataclass
  anthropic_provider.py  # Anthropic Messages API（SSE + tool use）
  openai_provider.py     # OpenAI Chat Completions（SSE + tool calling）
  manual.py              # 內建使用手冊 + 動作 schema 說明 → system prompt
  tools.py               # 兩個工具的 JSON schema（雙供應商格式各自轉換）
  script_gen.py          # tool_call args → 既有 script_from_dict 驗證 → Script
app/
  settings.py            # Settings 加 ai_provider / ai_model / ai_api_key / ai_privacy_ack
  settings_page.py       # 設定頁加 AI 區塊
  ai_worker.py           # 包現有 Worker：背景執行緒串流，delta 經 progress signal 回 UI
  ai_panel.py            # QDockWidget 聊天面板：氣泡、輸入、預覽卡片、套用/捨棄/復原
  main_window.py         # 掛 dock、標題列加「AI 助手」切換鈕
```

## 4. 單元一：provider 抽象（`core/ai/provider.py`）

```python
@dataclass(frozen=True)
class ToolCall:
    name: str          # "propose_new_script" | "propose_edit_current"
    args: dict         # 已從 JSON 解出的參數

@dataclass(frozen=True)
class ChatResult:
    text: str                     # 完整回覆文字（delta 累積後）
    tool_call: ToolCall | None    # 模型若呼叫工具

class ChatProvider(ABC):
    @abstractmethod
    def stream_chat(self, messages: list[dict], *, system: str,
                    tools: list[dict], on_delta: Callable[[str], None],
                    should_abort: Callable[[], bool]) -> ChatResult: ...
```

- `messages`：`[{"role": "user"|"assistant", "content": str}, ...]`（內部通用格式，
  各 provider 自行轉換成自家 payload）。
- `on_delta(text)`：每收到一段文字即回呼（呼叫端負責 marshal 回 UI 執行緒）。
- `should_abort()`：SSE 逐行讀取間檢查；True 則關閉連線、拋 `AiAborted`。
- 傳輸／HTTP 例外不在 provider 內吞：包成 `AiProviderError(繁中訊息)` 拋出，
  由呼叫端（Worker job）隔離。

### 4.1 Anthropic（`anthropic_provider.py`）

- `POST https://api.anthropic.com/v1/messages`，headers：`x-api-key`、
  `anthropic-version: 2023-06-01`、`content-type: application/json`。
- body：`{"model", "max_tokens": 4096, "system", "messages", "tools", "stream": true}`。
- SSE 解析：`content_block_delta`（`text_delta` → on_delta；`input_json_delta` →
  累積 tool args JSON）、`content_block_start`（`tool_use` → 記 name）、
  `message_stop` 結束。
- tools 格式：`{"name", "description", "input_schema"}`。

### 4.2 OpenAI（`openai_provider.py`）

- `POST https://api.openai.com/v1/chat/completions`，headers：
  `Authorization: Bearer <key>`。
- body：`{"model", "messages": [{"role":"system",...}] + messages, "tools",
  "stream": true}`。
- SSE 解析：`choices[0].delta.content` → on_delta；`delta.tool_calls[0]` 的
  `function.name` / `function.arguments` 分段累積；`data: [DONE]` 結束。
- tools 格式：`{"type": "function", "function": {"name", "description", "parameters"}}`。

### 4.3 共用 SSE 讀取

兩個 provider 共用一個模組層函式：`urllib.request.urlopen(req)` 後逐行
`iter(resp.readline, b"")`，`data: ` 前綴行解 JSON 交給 provider 的事件處理；
每行之間檢查 `should_abort()`。User-Agent 比照 discord_notify 設自訂字串。

## 5. 單元二：手冊與工具（`manual.py` / `tools.py`）

- `manual.py`：常數 `APP_MANUAL`（從 README 精煉的功能 cheat-sheet：各動作
  類型與參數、規則引擎、錄製、熱鍵、視窗指定、設定項）＋
  `build_system_prompt(current_script_json: str | None) -> str`：
  手冊＋行為界線＋（若有）當前選中腳本的 JSON。
- 行為界線（寫進 system prompt）：只協助本 App 的**合法自動化**用途；
  不協助反偵測／反外掛繞過、驗證碼（CAPTCHA）辨識或繞過、對背景視窗注入輸入
  等規避類請求——遇到一律婉拒並說明。
- `tools.py`：
  - `propose_new_script`：`{name: str, target_title_regex: str, actions: array}`
  - `propose_edit_current`：`{actions: array}`
  - `actions` 的 schema 描述既有動作類型與欄位（描述性即可，嚴格驗證交給
    script_gen——schema 只是引導模型，不是安全網）。
  - 提供 `as_anthropic() / as_openai()` 兩種格式輸出。

## 6. 單元三：產出驗證（`core/ai/script_gen.py`）

```python
def script_from_proposal(name: str, target_title_regex: str,
                         actions: list[dict]) -> Script:
    """組 script dict → 既有 script_from_dict 全套驗證。
    非法動作/欄位 → ScriptValidationError（原樣拋出，繁中訊息）。"""

def actions_for_edit(current: Script, actions: list[dict]) -> Script:
    """保留 current 的 name/target/settings，只換 actions，整份重驗。"""
```

安全網在此：**只有通過既有 `script_from_dict` / `action_from_dict` 驗證的
提案才可能落地**，不支援的動作類型、缺欄位、型別錯誤全數擋下。

## 7. 單元四：設定（`app/settings.py` ＋ `settings_page.py`）

`Settings` 新欄位（皆有預設值，舊 settings.json 直接相容）：

| 欄位 | 預設 | 驗證 |
|------|------|------|
| `ai_provider: str` | `""`（停用） | `"" / "anthropic" / "openai"` 白名單 |
| `ai_model: str` | `""` | 設了 provider 則不可空白 |
| `ai_api_key: str` | `""` | 設了 provider 則不可空白；strip |
| `ai_privacy_ack: bool` | `False` | 布林 |

設定頁新增「AI 助手」區塊：供應商下拉（停用／Anthropic Claude／OpenAI GPT）、
model 文字欄（placeholder 依供應商提示，如 `claude-sonnet-5` / `gpt-5-mini`）、
API key 欄（`QLineEdit.EchoMode.Password`）。旁註如實說明：
「金鑰以明文儲存於本機 settings.json」（與 Discord webhook 慣例一致，不引入 keyring）。

## 8. 單元五：背景串流（`app/ai_worker.py`）

薄件，包現有 `Worker`（一次性、moveToThread、progress/finished/failed）：

- job：`provider.stream_chat(...)`，`on_delta` → `progress({"kind": "delta",
  "text": ...})`；回傳 `ChatResult` 經 `finished` 投遞。
- 中止：panel 設 `abort_event`（`threading.Event`），`should_abort` 讀它；
  中止後 job 拋 `AiAborted` → 以 `finished(None)` 收尾（不是 failed）。
- `AiProviderError` → `failed(繁中訊息)` → 面板顯示錯誤氣泡，不崩潰（§10 慣例）。

## 9. 單元六：聊天面板（`app/ai_panel.py`）＋主視窗接線

- `QDockWidget("AI 助手")` 掛 `RightDockWidgetArea`，預設收起；標題列加
  切換鈕（比照 template_manage_button / settings_button）。
- provider 未設定 → 面板顯示引導文字＋「開啟設定」按鈕。
- 版面：訊息捲動區（使用者右、AI 左的氣泡）、輸入框（Enter 送出）、
  送出／停止鈕、「清除對話」鈕（對話僅存記憶體，關 App 即清）。
- 送出時：
  1. 首次（`ai_privacy_ack == False`）先跳確認：「你的訊息與選中腳本內容會
     傳送給你設定的 AI 供應商」→ 確認後存 `ai_privacy_ack = True`。
  2. 若腳本清單有選中腳本，`build_system_prompt` 附上其 JSON。
  3. 建 `AiWorker` 串流；delta 即時追加到 AI 氣泡；串流中鎖送出鈕。
- `ChatResult.tool_call` 到達 → `script_gen` 驗證：
  - 通過 → **預覽卡片**：腳本名稱＋動作列表（用既有 `action_label`）＋
    「套用」「捨棄」。
  - 失敗 → 卡片顯示「AI 產出無效：<錯誤>」＋「請 AI 修正」鈕（把錯誤訊息
    當一則 user 訊息回送，重試一次）。
- 套用：
  - `propose_new_script` → 名稱衝突時自動加序號（比照現有 duplicate 慣例）→
    storage 存檔 → 刷新腳本清單。
  - `propose_edit_current` → 記下改動前 `Script`（記憶體）→ 覆寫存回 →
    刷新清單；卡片變為「已套用 ✓ ＋ 復原」，按復原把舊版存回。
- 對話歷史（內部通用 messages 格式）保留在面板記憶體，供多輪追問。

## 10. 資料流

```
使用者輸入 → ai_panel（隱私 ack、附選中腳本 JSON）
  → AiWorker(job=provider.stream_chat)  [背景 QThread]
  → on_delta → progress signal → 氣泡即時更新
  → ChatResult.tool_call → script_gen 驗證
      ├─ OK → 預覽卡片 → 套用 → storage 存檔 → 清單刷新（edit 留復原）
      └─ ScriptValidationError → 錯誤卡片 →（可選）回送錯誤請 AI 修正
```

## 11. 錯誤處理

| 情況 | 行為 |
|------|------|
| provider 未設定 | 面板引導去設定頁，輸入框停用 |
| 401 / 403 | 「API 金鑰無效或無權限，請檢查設定」 |
| 429 | 「已達供應商速率上限，請稍後再試」 |
| 網路錯誤 / 逾時 | 「連線失敗：<原因>」 |
| SSE 中途斷線 | 已收文字保留，尾端標「（回應中斷）」 |
| 模型產非法腳本 | 錯誤卡片＋一鍵回送修正 |
| 使用者按停止 | 已收文字保留，狀態列「已停止」 |

全部不崩潰、繁中訊息（§10 慣例）。

## 12. 測試（TDD；主力在無 Qt 的 core 層，GUI 測試走 offscreen）

| 層 | 測試 |
|----|------|
| provider | 注入 fake urlopen：payload 格式正確（含 tools）、SSE 文字 delta 解析、tool_use/tool_calls 參數跨多段累積、[DONE]/message_stop 收尾、abort 中斷、HTTP 錯誤 → AiProviderError |
| script_gen | 合法提案 → Script；未知動作類型／缺欄位 → ScriptValidationError；edit 保留 name/target/settings 只換 actions |
| manual/tools | system prompt 含手冊與界線；兩種 tools 格式輸出正確 |
| settings | 新欄位預設、白名單驗證、provider 設定時 model/key 必填、round-trip |
| ai_worker | fake provider：delta 進 progress、結果進 finished、AiProviderError 進 failed、abort → finished(None) |
| ai_panel | 未設定 → 引導畫面；送出 → 使用者氣泡＋worker 啟動；delta → AI 氣泡累積；tool_call → 預覽卡片；套用 new → 清單多一筆；套用 edit → 內容變＋復原可還原；非法提案 → 錯誤卡片 |

## 13. 非目標（YAGNI）

- 後端／訂閱／帳號／金流（純 BYO；provider 介面已留擴充點，之後要接自家
  後端＝多一個 provider 實作）。
- keyring／金鑰加密（明文，與現有 webhook 慣例一致，如實標示）。
- RAG／向量檢索（手冊小，直接進 system prompt）。
- 對話歷史持久化（記憶體內，關 App 即清）。
- 多輪自動 agentic 連續改檔（一次一提案，要改再對話）。
- 圖片／截圖上傳給 AI。
- 規則（Rule）的 AI 產生（先只做腳本；介面留得下次加）。
