# AI 助手訂閱登入（OpenClaw 相容路徑）— 設計文件

- **日期**：2026-07-16
- **狀態**：已實作

## 1. 動機

現有 AI 腳本助手只支援 Anthropic/OpenAI API key。使用者希望也能使用既有的
ChatGPT 或 Claude 訂閱，登入體驗與 OpenClaw 相同，不必另外申請 API key。

本功能保留既有 API-key 路徑，另外新增「訂閱登入」認證模式。App 不處理帳號密碼、
不逆向網頁 session cookie；登入與 token 生命週期使用供應商公開或 OpenClaw 已採用
的相容流程。

## 2. 已確認的需求決策

| 決策點 | 結論 |
|--------|------|
| ChatGPT 訂閱 | 採 OpenClaw 現行預設的 Codex `app-server`：由正式 JSON-RPC auth surface 啟動 browser/device-code 登入 |
| Claude 訂閱 | 採 OpenClaw 現行路徑：優先重用 Claude Code 登入；另支援 Anthropic `setup-token` |
| API key | 既有 Anthropic/OpenAI API-key 模式完整保留 |
| UI | 設定頁選「供應商＋認證方式」，訂閱模式提供登入／登出／重新驗證 |
| 憑證 | Windows 正式版存 Windows Credential Manager；`settings.json` 不保存 access/refresh token |
| AI 腳本安全網 | 不變：所有 AI 提案仍須通過既有 `script_from_dict` 驗證，使用者按套用才落地 |

## 3. 供應商能力不對稱（刻意保留）

兩家不可假設成完全相同的 OAuth API：

- **OpenAI**：ChatGPT 方案包含 Codex；登入後走 Codex account/runtime 路徑。OAuth
  profile 保存 access、refresh、expires、account id，並自動刷新。
- **Anthropic**：Claude Pro/Max 包含 Claude Code，但第三方 App 的通用 OAuth client
  並未公開成與 OpenAI 相同的介面。本版因此不嵌入冒充 Claude Code 的 browser OAuth；
  使用官方 Claude Code 已登入狀態，或由使用者透過 `claude setup-token` 取得 token。

設定頁會如實顯示差異，不把 Claude setup-token 包裝成一般 API key，也不宣稱兩家登入
能力完全相同。

## 4. 架構總覽

```
app/settings.py
  ai_provider       "" | "anthropic" | "openai"
  ai_auth_mode      "api_key" | "subscription"
  ai_model
  ai_api_key        （只供既有 API-key 模式）
  ai_auth_profile   （非祕密 profile id）

core/ai/auth/
  models.py         AuthProfile / AuthStatus / AuthError
  secret_store.py   SecretStore protocol + WindowsCredentialStore
  codex_account.py  Codex app-server JSON-RPC account/login/status/logout client
  claude_auth.py    Claude Code 登入狀態 + setup-token profile

core/ai/
  openai_subscription_provider.py   Codex subscription transport
  claude_subscription_provider.py   Claude Code subscription transport
  factory.py                         依 provider/auth_mode 建 provider

app/
  ai_auth_service.py 認證協調；登入工作沿用既有 Worker，不阻塞 GUI
  settings_page.py   認證方式與登入狀態 UI
  ai_panel.py        使用新 provider factory；過期時提示重新登入
```

auth 層保持無 Qt；瀏覽器開啟、callback server、HTTP、secret store 皆可注入，方便單測。

## 5. 認證資料模型與安全儲存

### 5.1 `AuthProfile`

```python
@dataclass(frozen=True)
class AuthProfile:
    provider: str
    profile_id: str
    access_token: str
    refresh_token: str = ""
    expires_at: float | None = None
    account_id: str = ""
    source: str = ""  # openai_oauth | claude_cli | anthropic_setup_token
```

`AuthStatus` 只含可顯示資訊：configured、expired、provider、profile_id、source、
account label；不得把 token 傳給 Qt widget 或寫入 log。

### 5.2 `SecretStore`

介面：`get(profile_id)`、`put(profile)`、`delete(profile_id)`。

- Windows：Claude setup-token 使用 Credential Manager generic credential，target name 為
  `KeyboardExecutor/ai/<provider>/<profile_id>`；token JSON 作 credential blob。
- 單測：`MemorySecretStore`。
- 非 Windows 開發環境：不偷偷降級成 `settings.json` 明文；顯示「此平台尚未提供
  安全憑證儲存」，API-key 模式仍可用。
- log、錯誤訊息、exception repr 一律不得包含 access/refresh/setup token。

`settings.json` 只保存 `ai_auth_mode` 與 `ai_auth_profile`，不保存 OAuth token。
OpenAI token 由 Codex app-server 自己的 credential store 管理，本 App 不複製或刷新它；
Credential Manager 主要保存 Claude setup-token。
既有 `ai_api_key` 暫時維持原明文相容性，本功能不順帶遷移它。

## 6. OpenAI ChatGPT/Codex 訂閱登入（Codex app-server）

### 6.1 為何採 app-server

Codex app-server 是 OpenAI Codex 公開的程式控制介面，不是把 prompt 當 shell 指令
交給互動 CLI。它以 stdio JSON-RPC 提供 `account/read`、`account/login/start`、
`account/login/cancel`、`account/logout`、rate limits 與 agent thread/turn；OpenClaw
現行的 native Codex runtime 也是同一類架構。這避免第三方 App 複製 Codex OAuth
client id、scope、callback allow-list 或自行保存 refresh token。

### 6.2 登入流程

1. App 啟動／連接 `codex app-server` 子程序，以 JSON-RPC 初始化。
2. browser 模式送 `account/login/start {type:"chatgpt"}`，取得 `loginId` 與
   `authUrl` 後用系統瀏覽器開啟。
3. callback、PKCE、token exchange 與安全儲存由 Codex 管理；App 等待
   `account/login/completed` notification。
4. callback 不適用時改送 `type:"chatgptDeviceCode"`，UI 顯示官方回傳的驗證資訊。
5. 成功後以 `account/read` 取得非敏感 account/plan 狀態，settings 只記
   `ai_auth_profile="codex"`。
6. 使用者取消時送 `account/login/cancel`；登出送 `account/logout`。

找不到 Codex app-server 時顯示安裝／修復引導；第一版不自動下載未驗證的 binary。

### 6.3 Refresh 與併發

- token refresh 完全由 Codex 管理；App 不讀 access/refresh token。
- account login/logout 與每次聊天各使用一條短生命週期 app-server client；設定頁在
  worker 執行期間停用重複操作，聊天面板亦禁止同時送出第二個 turn。
- `account/read(refreshToken=true)` 或 turn 回報需重新登入時，UI 顯示重新登入；不得
  自動改走 API key。
- 關閉 App 時先取消在途 turn/login，再結束 app-server；必須有 timeout＋terminate
  fallback，避免殘留子程序。

### 6.4 Provider transport

新增 `OpenAiSubscriptionProvider`，透過 app-server thread/turn JSON-RPC 執行，
不直接接觸 OAuth token。它將 Codex event 轉成現有 `ChatProvider.stream_chat` 的文字
delta 與 `ToolCall`；若 app-server 的工具輸出介面與現有 function tool 不同，則使用
嚴格標記的 proposal JSON envelope，再交既有 `script_gen` 驗證，安全網不分叉。

## 7. Claude 訂閱登入

### 7.1 Claude Code 登入重用（預設）

- 設定頁按「連結 Claude 訂閱」時，先偵測受支援的 Claude Code credential store。
- 找到已登入且可用的 credential 時，建立 `source="claude_cli"` profile；不複製到
  `settings.json`，執行前重新讀取官方 credential store，讓 Claude Code 自己管理
  refresh／登出。
- 未安裝或未登入時，顯示明確引導：「請先安裝 Claude Code 並以 Pro/Max 帳號登入」。
- 不讀瀏覽器 cookie、不要求 Claude.ai 帳密。

### 7.2 setup-token（替代）

- UI 提供「使用 setup-token」，顯示本機執行 `claude setup-token` 的說明與貼上欄。
- token 經最低格式檢查後存入 `SecretStore`，source 為
  `anthropic_setup_token`；貼上欄儲存後立即清空。
- `ClaudeSubscriptionProvider` 一律呼叫官方 Claude Code；setup-token 只透過
  `CLAUDE_CODE_OAUTH_TOKEN` 傳給該子程序，不由 App 自行拼 Anthropic 私有 header
  或直接呼叫未承諾相容的端點。
- 401/403 顯示「Claude 訂閱登入已失效，請重新連結」，不顯示 token。

若 Anthropic 停止 setup-token 或 credential 格式改變，該模式顯示不可用，但既有
Anthropic API-key provider 不受影響。

## 8. 設定與 UI

設定頁 AI 區塊改為：

1. 供應商：停用／Anthropic Claude／OpenAI GPT。
2. 認證方式：API 金鑰／訂閱登入。
3. Model：保留文字欄；訂閱模式登入成功後可由 provider catalog 填入建議值，但不在
   未驗證時硬編一個永遠有效的 model 名稱。
4. API-key 模式：顯示既有 key 欄。
5. 訂閱模式：隱藏 key 欄，顯示狀態與「登入／重新登入」「登出」。Claude 另顯示
   「重用 Claude Code」與「setup-token」兩條路徑。

狀態例：未登入、登入中、已連結（provider/account）、即將到期、已失效。登入與 token
refresh 全部在 worker 執行；設定視窗關閉時必須中止／等待 worker，避免 QThread 崩潰。

切換 auth mode 不刪除另一模式的 credential；只有使用者按「登出／刪除憑證」才刪。
這讓使用者可在訂閱達限時手動切回 API key，但不做未告知的自動付費 fallback。

## 9. Factory 與聊天面板接線

`make_provider` 改接受一個已解析的 credential/context，而非假定所有模式都有 API key：

```python
def make_provider(provider: str, auth_mode: str, model: str, *,
                  api_key: str = "",
                  auth_profile: AuthProfile | None = None) -> ChatProvider | None:
    ...
```

`AiPanel.send`：

1. 讀設定。
2. API-key 模式沿用現有 provider。
3. subscription 模式請 `AiAuthManager.resolve_profile` 檢查／refresh。
4. 建 subscription provider 後走既有 worker、對話、tool schema、預覽／套用流程。

認證錯誤在訊息區顯示可操作按鈕「開啟 AI 設定」，不把它當模型回答加入對話歷史。

## 10. 失敗與降級行為

| 情況 | 行為 |
|------|------|
| OAuth callback state 不符 | 立即拒絕，profile 不變 |
| callback port 無法綁定 | 提供 device-code，不靜默關閉 |
| 使用者取消登入 | 回到原狀，不清除舊 profile |
| refresh token 失效 | 標記需重新登入；不自動改用可能計費的 API key |
| 訂閱達使用上限／429 | 顯示方案用量已達限與可能的重置提示；不無限重試 |
| Claude Code 未安裝／未登入 | 顯示安裝登入指引，仍可選 setup-token 或 API key |
| Credential Manager 失敗 | 不落盤 token，回報錯誤；不得降級成明文 |
| provider 政策／端點變更 | 僅停用該 subscription provider；API-key 路徑續用 |

## 11. 測試（全程 TDD）

| 層 | 測試 |
|----|------|
| auth models/store | profile round-trip；Windows store 呼叫契約；錯誤與 log 不洩漏 token |
| Codex account client | JSON-RPC framing/id correlation；browser/device login start；completed/cancel/logout；account status；程序退出/逾時 |
| Claude auth | CLI credential found/missing/expired；setup-token 存取與清除；不寫 settings.json |
| providers | fake app-server／Claude Code process：payload、結構化結果、工具提案、登入失效與用量錯誤翻譯 |
| settings | 新欄位預設與 round-trip；API-key/subscription 各自必填條件；舊設定相容 |
| settings page | auth mode 切換欄位；登入狀態；登入/登出 signal；worker shutdown |
| ai_panel | 四條 provider/auth 組合都建對 provider；失效 profile 顯示設定按鈕；不自動付費 fallback |
| regression | 既有 API-key provider、串流聊天、提案預覽／套用／復原測試全部續過 |

真實 OAuth 不進 CI；以注入 browser、callback server、clock、HTTP opener、secret store
完整測試。另提供手動 smoke checklist，使用測試帳號驗證登入、refresh、登出與撤銷。

## 12. 資料遷移

- 舊 `settings.json` 無 `ai_auth_mode`：若已有 `ai_provider`＋`ai_api_key`，預設
  `api_key`；否則保持停用。
- 不自動搬動或刪除既有 API key。
- 新 subscription profile 寫入成功後才更新 settings，避免半完成狀態。
- 登出只刪指定 profile，不刪聊天紀錄以外的腳本資料。

## 13. 非目標

- 不逆向 ChatGPT/Claude 網頁 session、cookie 或 CAPTCHA。
- 不收集或代理使用者帳密。
- 不自建帳號、訂閱、金流或共享 token 後端。
- 不把 API key 自動轉成訂閱登入，反之亦然。
- 不在訂閱達限後自動切到付費 API key。
- 不承諾供應商未公開的 model 永久可用。
- 不做多帳號輪替／用量池化；第一版每家一個 active profile。

## 14. 可維護性與發布條件

- OAuth config、provider endpoint 與事件 parser 各自隔離；不得把 client metadata
  散落在 UI。
- 發布前重新核對 OpenAI/Anthropic 官方文件與 OpenClaw 當前實作；若來源互相衝突，
  以供應商官方限制為準。
- UI 清楚標示「訂閱用量受方案限制」與資料會送往所選供應商。
- README 增加登入、登出、憑證儲存、撤銷與疑難排解說明。
