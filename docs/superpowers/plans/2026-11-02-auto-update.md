# 自動更新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 朋友的 Windows EXE 自動從公開倉庫 `simamaplestar/keyboard-executer` 發現、下載、驗證新版，閒置時提示並一鍵替換重啟；作者用一個指令發布。

**Architecture:** 純邏輯放 `core/update/`（版本比對、Release 解析、下載驗證、檔案替換），無 Qt、全注入可測。`app/update_controller.py` 用 QTimer 排程、背景 thread 做網路，Signal 回 GUI 執行緒；主視窗提供「忙碌」判斷與提示對話框。發布腳本 `packaging/release.py`（Python，可測的純函式）＋ `release.ps1` 薄包裝。

**Tech Stack:** Python 3.13 stdlib（urllib、hashlib、json、os）、PySide6、PyInstaller 6.21 onefile、gh CLI 2.92（Windows 已安裝）。

**Spec:** docs/superpowers/specs/2026-11-02-auto-update-design.md

## Global Constraints

- 公開倉庫 `simamaplestar/keyboard-executer`，tag `v<版本>`，附件 `KeyboardExecutor.exe` 與 `KeyboardExecutor.exe.sha256`，Release 內文＝更新說明。
- 不新增相依；HTTP 用 urllib，帶 `User-Agent: KeyboardExecutor/<版本>`（沿用 discord_notify 的理由）。
- 只在 `getattr(sys, "frozen", False)` 且 `sys.platform == "win32"` 時啟用更新。
- 只有遠端版本**大於**目前 `__version__` 才更新；不降級、不強制。
- 網路／限流／解析失敗：只寫 log（WARNING 以下），不跳任何視窗。
- 忙碌（腳本執行、規則監看、AI 示範試跑、任何 modal 對話框開著）時不提示。
- 任何替換失敗都必須讓原 EXE 回到原名、可正常開啟。
- 發布腳本不執行原始碼的 git 提交／推送，也不檢查工作目錄乾淨。
- 使用者介面文字一律繁體中文。
- 常數：`START_DELAY_SEC=5`、`CHECK_INTERVAL_SEC=6*3600`、`REMIND_AFTER_SEC=30*60`、`BUSY_RETRY_SEC=60`、`LOCK_STALE_SEC=3600`、API timeout 10s、下載每次讀取 timeout 60s。

## Review Focus

1. 下載到一半斷線／檔案大小或 SHA 不符 → 殘檔清掉，下次重下，原 EXE 不受影響（Task 2 測試）。
2. EXE 被改過名（例如 `KE.exe`）或放在中文路徑 → 依 `sys.executable` 實際路徑替換，重啟的也是同名同路徑（Task 3 測試）。
3. 兩個程式同時開 → 只有一個在下載；另一個看到已驗證的 `.new` 直接用（Task 2 鎖檔測試）。
4. 新版 EXE 被防毒鎖住、改名失敗 → 回滾成原名，提示「更新失敗，請稍後再試」（Task 3 測試）。
5. 「稍後」後 30 分鐘才再提醒；同一版不在每次 6 小時檢查時重下載（Task 5 測試）。

---

### Task 1: 版本比對與 Release 解析

**Files:**
- Create: `src/keyboard_executor/core/update/__init__.py`、`src/keyboard_executor/core/update/release.py`
- Test: `tests/core/test_update_release.py`

**Interfaces:**
- Produces:
  - `REPO = "simamaplestar/keyboard-executer"`、`ASSET_NAME = "KeyboardExecutor.exe"`、`SHA_NAME = ASSET_NAME + ".sha256"`、`RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"`
  - `parse_version(text: str) -> tuple[int, int, int]`（接受前綴 `v`；不合法拋 `ValueError`）
  - `is_newer(remote: str, current: str) -> bool`
  - `@dataclass(frozen=True) ReleaseInfo(version: str, notes: str, exe_url: str, exe_size: int, sha_url: str)`
  - `class UpdateError(Exception)`
  - `parse_latest_release(data: dict) -> ReleaseInfo`（缺附件／tag 不合法 → `UpdateError`）
  - `parse_sha256(text: str) -> str`（接受 `"<hex>"` 或 `"<hex>  KeyboardExecutor.exe"`，回小寫 64 hex；不合法 → `UpdateError`）
  - `fetch_latest(*, current: str, opener=None, timeout=10.0) -> ReleaseInfo`（GET `https://api.github.com/repos/{REPO}/releases/latest`，`Accept: application/vnd.github+json`；HTTP／JSON 錯誤包成 `UpdateError`）

- [ ] **Step 1: Write the failing tests**

```python
def test_version_compare():
    assert parse_version("v0.6.0") == (0, 6, 0)
    assert is_newer("0.6.0", "0.5.10") is False and is_newer("0.5.10", "0.5.9")
    assert is_newer("v1.0.0", "0.9.9") and not is_newer("0.5.0", "0.5.0")
    with pytest.raises(ValueError): parse_version("0.6")

def test_parse_latest_release_picks_assets():
    info = parse_latest_release({"tag_name": "v0.6.0", "body": "修正", "assets": [
        {"name": "KeyboardExecutor.exe", "browser_download_url": "U1", "size": 123},
        {"name": "KeyboardExecutor.exe.sha256", "browser_download_url": "U2", "size": 80}]})
    assert info == ReleaseInfo("0.6.0", "修正", "U1", 123, "U2")

def test_parse_latest_release_missing_sha_raises():  # match="sha256"
def test_parse_sha256_formats():  # 兩種格式＋大寫轉小寫；"xyz" 拋 UpdateError
def test_fetch_latest_wraps_http_error():  # opener 拋 urllib.error.URLError → UpdateError
def test_fetch_latest_sends_user_agent():  # opener 收到的 Request 帶 User-Agent 含版本
```

- [ ] **Step 2: Run — Expected: FAIL（ModuleNotFoundError keyboard_executor.core.update）**

`QT_QPA_PLATFORM=offscreen <venv-py> -m pytest -q -p no:cacheprovider tests/core/test_update_release.py`

- [ ] **Step 3: Implement `core/update/release.py`**（opener 預設 `urllib.request.urlopen`，簽名 `opener(request, timeout=...)`）
- [ ] **Step 4: Run — Expected: PASS**

### Task 2: 下載、驗證與鎖檔

**Files:**
- Create: `src/keyboard_executor/core/update/download.py`
- Test: `tests/core/test_update_download.py`

**Interfaces:**
- Consumes: `ReleaseInfo`, `UpdateError`, `parse_sha256`（Task 1）
- Produces:
  - `staged_path(exe: Path) -> Path` ＝ `exe.with_name(exe.name + ".new")`；`version_marker(exe) -> Path` ＝ `exe.name + ".new.version"`（內容＝版本字串）
  - `class UpdateLock`：`acquire(exe: Path, *, now=time.time) -> bool`（`os.open(O_CREAT|O_EXCL)` 建 `<exe>.update.lock`；舊於 `LOCK_STALE_SEC` 視為殘留，刪掉重搶）、`release()`
  - `class FolderNotWritable(UpdateError)`：鎖檔建立遇 `PermissionError` 時拋
  - `staged_version(exe: Path) -> str | None`：`.new` 與標記都存在才回版本
  - `download_release(info: ReleaseInfo, exe: Path, *, opener=None, chunk=1<<20, on_progress=None) -> Path`：已有同版 staged 直接回；否則抓 sha → 串流寫 `<exe>.download` 邊算 SHA → 驗證大小與 SHA → `os.replace` 成 `.new` → 寫版本標記；任何失敗刪 `.download` 並拋 `UpdateError`

- [ ] **Step 1: Write the failing tests**（opener 以假 response 物件提供 bytes；全部用 `tmp_path`）

```python
def test_download_verifies_and_stages(tmp_path):  # 正確 bytes → .new 內容相同、staged_version == "0.6.0"、無 .download 殘檔
def test_size_mismatch_cleans_up(tmp_path):        # 少 1 byte → UpdateError("大小")，.download/.new 都不存在
def test_sha_mismatch_cleans_up(tmp_path):         # match="SHA"
def test_connection_drop_mid_stream(tmp_path):     # read() 第二次拋 OSError → UpdateError，無殘檔
def test_existing_staged_same_version_skips_network(tmp_path):  # opener 被呼叫就 fail
def test_lock_excludes_second_holder(tmp_path):    # 第一把 acquire True、第二把 False；release 後可再拿
def test_stale_lock_is_taken_over(tmp_path):       # now 給 mtime+LOCK_STALE_SEC+1 → True
def test_unwritable_folder_raises(tmp_path, monkeypatch):  # os.open 拋 PermissionError → FolderNotWritable
```

- [ ] **Step 2: Run — Expected: FAIL（ImportError download）**
- [ ] **Step 3: Implement `core/update/download.py`**
- [ ] **Step 4: Run — Expected: PASS**

### Task 3: 替換 EXE、回滾、重啟指令與舊檔清理

**Files:**
- Create: `src/keyboard_executor/core/update/install.py`
- Test: `tests/core/test_update_install.py`

**Interfaces:**
- Consumes: `staged_path`, `version_marker`（Task 2）
- Produces:
  - `old_path(exe: Path) -> Path` ＝ `exe.name + ".old"`
  - `install_staged(exe: Path, *, rename=os.replace) -> None`：(1) 刪掉既有 `.old`（刪不掉時拋 `UpdateError("舊版檔案仍被使用中…")`，什麼都不動）(2) `exe → .old` (3) `.new → exe`；第 3 步失敗時把 `.old` 改回 `exe` 再拋 `UpdateError("更新失敗…")`；成功後刪版本標記
  - `restart_command(exe: Path, argv: list[str]) -> list[str]` ＝ `[str(exe), *argv[1:]]`（保留 `--dir` 等參數）
  - `restart_env(base: dict) -> dict`：複製並設 `PYINSTALLER_RESET_ENVIRONMENT="1"`（PyInstaller 6.x：讓子程序重新解壓，不沿用父程序的 `_MEI` 暫存）
  - `cleanup_after_update(exe: Path) -> None`：刪 `.old`；刪不掉（被其他執行中的程式占用）就留著，不拋例外

- [ ] **Step 1: Write the failing tests**

```python
def test_install_swaps_files(tmp_path):            # exe 內容 b"old"、.new b"new" → exe 為 b"new"、.old 為 b"old"、標記已刪
def test_install_rolls_back_when_new_cannot_move(tmp_path):
    # rename 假函式：第二次呼叫（.new→exe）拋 PermissionError
    # → UpdateError；exe 內容仍為 b"old"；.new 仍在
def test_install_keeps_renamed_exe_name(tmp_path): # exe 名為「我的 KE.exe」在中文資料夾 → 換完仍是同一路徑
def test_restart_command_keeps_args():             # ["x.exe","--dir","D:\\s"] → [exe,"--dir","D:\\s"]
def test_restart_env_resets_pyinstaller():         # 原 dict 不被修改
def test_cleanup_ignores_locked_old(tmp_path, monkeypatch):  # unlink 拋 PermissionError 不外漏
```

- [ ] **Step 2: Run — Expected: FAIL（ImportError install）**
- [ ] **Step 3: Implement `core/update/install.py`**
- [ ] **Step 4: Run — Expected: PASS**

### Task 4: 設定欄位與設定頁

**Files:**
- Modify: `src/keyboard_executor/app/settings.py`（`Settings` 加 `auto_update: bool = True`；`validate_settings` 檢查布林）
- Modify: `src/keyboard_executor/app/settings_page.py`（「自動檢查更新」勾選框、目前版本標籤 `目前版本 0.5.0`、「立即檢查更新」按鈕＋結果標籤；建構子新增 `update_controller=None`，為 None 或未啟用時按鈕停用並顯示「從原始碼執行，不檢查更新」）
- Test: `tests/app/test_settings.py`、`tests/app/test_settings_page_widget.py`

**Interfaces:**
- Consumes: Task 5 的 `UpdateController.check_now()` 與 `check_finished(str)` 訊號（本 task 測試用假物件）
- Produces: `Settings.auto_update`

- [ ] **Step 1: Write the failing tests**

```python
def test_auto_update_defaults_true_and_validates():  # Settings().auto_update is True；auto_update="yes" → ScriptValidationError
def test_settings_page_saves_auto_update(qtbot):      # 取消勾選 → 存檔 auto_update False
def test_settings_page_check_now_shows_result(qtbot): # 假 controller：按按鈕呼叫 check_now；emit check_finished("已是最新版本") → 結果標籤顯示該文字
def test_settings_page_without_controller_disables_button(qtbot)
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run — Expected: PASS（含既有 test_settings*.py 全部）**

### Task 5: UpdateController（排程、背景檢查下載、提醒時機）

**Files:**
- Create: `src/keyboard_executor/app/update_controller.py`
- Test: `tests/app/test_update_controller.py`

**Interfaces:**
- Consumes: Task 1–3 全部；`Settings.auto_update`
- Produces: `class UpdateController(QObject)`
  - `__init__(self, *, exe: Path | None, current: str, get_settings, is_busy: Callable[[], bool], fetch=fetch_latest, download=download_release, run_in_background=None, parent=None)`；`exe=None` ⇒ `enabled == False`
  - Signals：`update_ready(object)`（ReleaseInfo，已下載驗證、且此刻不忙）、`manual_update_needed(str)`（下載頁網址，資料夾不可寫時，每版一次）、`check_finished(str)`（給設定頁的繁中結果）
  - `start()`：`enabled` 時 `START_DELAY_SEC` 後第一次檢查，之後每 `CHECK_INTERVAL_SEC`；`get_settings().auto_update` 為 False 時排程照跑但跳過自動檢查
  - `check_now()`：忽略 auto_update 立即檢查
  - `postpone()`：使用者按「稍後」→ `REMIND_AFTER_SEC` 後再發 `update_ready`
  - 忙碌時不發 `update_ready`，每 `BUSY_RETRY_SEC` 重看一次 `is_busy()`
  - 同一時間只跑一個背景檢查；已下載好的版本不重下載
  - `run_in_background(fn, on_done)` 注入：預設用 `threading.Thread`＋內部 Signal 把結果送回 GUI 執行緒；測試注入同步版本
  - 計時器以 `QTimer` 實作，測試直接呼叫 `_on_check_timer()`／`_on_remind_timer()` 驅動

- [ ] **Step 1: Write the failing tests**（同步 `run_in_background`、假 fetch/download）

```python
def test_disabled_without_exe(qtbot):                 # enabled False，start() 不排程，check_now 發 check_finished("從原始碼執行，不檢查更新")
def test_newer_release_downloads_and_signals(qtbot):  # update_ready 收到 ReleaseInfo("0.6.0",…)
def test_same_version_reports_up_to_date(qtbot):      # check_finished("已是最新版本 0.5.0")，download 未呼叫
def test_network_error_is_silent(qtbot, caplog):      # fetch 拋 UpdateError → 無 update_ready、check_finished 含「檢查失敗」、log WARNING
def test_busy_defers_until_idle(qtbot):               # is_busy True → 無訊號；改 False 後 _on_remind_timer() → update_ready
def test_postpone_waits(qtbot):                       # postpone() 後下一次 _on_check_timer 不重發、remind timer interval == REMIND_AFTER_SEC*1000
def test_auto_update_off_skips_timer_check(qtbot)     # get_settings().auto_update False → _on_check_timer 不呼叫 fetch；check_now 仍會
def test_unwritable_folder_signals_manual_once(qtbot) # download 拋 FolderNotWritable 兩次 → manual_update_needed 只發一次，帶 RELEASES_PAGE
def test_second_check_while_running_is_ignored(qtbot) # 背景尚未完成時再 check_now → fetch 只呼叫一次
```

- [ ] **Step 2: Run — Expected: FAIL（ImportError update_controller）**
- [ ] **Step 3: Implement `app/update_controller.py`**
- [ ] **Step 4: Run — Expected: PASS**

### Task 6: 主視窗接線、提示對話框、替換後重啟、啟動清理

**Files:**
- Modify: `src/keyboard_executor/app/main_window.py`（建構子新增 `update_controller=None`；新增 `is_busy() -> bool`＝`self._worker is not None or self._watch_worker is not None or self._demo.active or QApplication.activeModalWidget() is not None`；`update_ready` → `_on_update_ready(info)`：訊息框標題「有新版本」、內文「新版 {version} 已下載，要現在重新啟動更新嗎？\n\n更新內容：\n{notes}」、按鈕「立即更新」「稍後」；立即更新 → `install_staged` → `subprocess.Popen(restart_command, env=restart_env(os.environ), close_fds=True)` → `QApplication.quit()`（經過 closeEvent 收尾）；`UpdateError` → 訊息框「更新失敗：{原因}，舊版仍可正常使用」；`manual_update_needed(url)` → 訊息框附網址與「開啟下載頁」按鈕（用既有 `self._url_opener`）；設定頁開啟時傳入 controller）
- Modify: `src/keyboard_executor/app/application.py`（`build_app` 新增 `update_controller_factory=None`；frozen＋win32 時建立 `UpdateController(exe=Path(sys.executable), current=__version__, …)` 並 `start()`；否則 `exe=None`；frozen 時啟動先呼叫 `cleanup_after_update(Path(sys.executable))`）
- Test: `tests/app/test_main_window.py`、`tests/app/test_application.py`

**Interfaces:**
- Consumes: Task 3 `install_staged`, `restart_command`, `restart_env`, `cleanup_after_update`；Task 5 `UpdateController` 與其訊號
- Produces: `MainWindow.is_busy()`

- [ ] **Step 1: Write the failing tests**（注入假 controller、假 `confirm_update`／`popen`／`quit` 可呼叫物件，避免真的開視窗或重啟）

```python
def test_is_busy_reflects_worker_watch_demo(qtbot)
def test_update_ready_accept_installs_and_restarts(qtbot, tmp_path)  # popen 收到 restart_command；quit 被呼叫
def test_update_ready_later_postpones(qtbot)                         # controller.postpone 被呼叫，未 install
def test_install_failure_shows_error_and_keeps_running(qtbot)        # install 拋 UpdateError → 錯誤訊息含「舊版仍可正常使用」，quit 未呼叫
def test_manual_update_needed_opens_page(qtbot)                      # 選「開啟下載頁」→ url_opener 收到 RELEASES_PAGE
def test_build_app_not_frozen_has_disabled_updater(qtbot)            # application：非 frozen → controller.enabled False
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement**（對話框與 Popen／quit 走可注入的 `_confirm_update`／`_popen`／`_quit` 屬性，預設為真實實作）
- [ ] **Step 4: Run — Expected: PASS（tests/app 全部）**

### Task 7: 發布腳本與文件

**Files:**
- Create: `packaging/release.py`、`packaging/release.ps1`
- Modify: `packaging/README.md`（「發布新版」一節）、`README.md`（功能清單加「自動更新」一行）
- Test: `tests/packaging/test_release.py`（新目錄，含 `__init__.py`）

**Interfaces:**
- Consumes: Task 1 `parse_version`, `is_newer`, `REPO`, `ASSET_NAME`, `SHA_NAME`
- Produces:
  - `bump_version_text(init_text: str, pyproject_text: str, new: str) -> tuple[str, str]`（只換 `__version__ = "…"` 與 `[project]` 的 `version = "…"` 各一處；找不到拋 `SystemExit`）
  - `sha256_line(path: Path) -> str` ＝ `"<hex>  KeyboardExecutor.exe\n"`
  - `main(argv) -> int`：`release.py <版本> <更新說明>` 依序：版本必須 `is_newer(新, 目前)` → 跑完整測試（失敗即停，版本號未動）→ 改版本號 → PyInstaller 到 `packaging/dist/release-<版本>/` → 寫 `.sha256` → `gh repo view REPO` 失敗則 `gh repo create REPO --public --description "Keyboard Executor 發布版"` → `gh release create v<版本> <exe> <sha> --repo REPO --title v<版本> --notes <說明>`；打包或上傳失敗時把版本號改回原值並回傳非 0
  - `release.ps1`：`& <venv python> $PSScriptRoot\release.py @args`，venv 路徑 `$env:USERPROFILE\ke-build-venv\Scripts\python.exe`
  - 外部指令走可注入的 `run(cmd) -> int`，測試不真的跑

- [ ] **Step 1: Write the failing tests**

```python
def test_bump_version_text():               # 兩檔各換一處，其餘不變
def test_rejects_not_newer(capsys):          # main(["0.5.0","x"]) 回非 0、run 未被呼叫
def test_runs_steps_in_order(tmp_path):      # 假 run 全回 0 → 指令順序：pytest、PyInstaller、gh repo view、gh release create（附 exe 與 sha）
def test_tests_fail_keeps_version(tmp_path): # pytest 回 1 → 版本檔未改、未打包
def test_upload_fail_reverts_version(tmp_path)
def test_creates_repo_when_missing(tmp_path) # gh repo view 回 1 → 有 gh repo create … --public
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement**（`main` 接受 `root: Path` 與 `run` 注入參數供測試）
- [ ] **Step 4: Run — Expected: PASS**

### Task 8: 整合驗證與打包

- [ ] **Step 1: 完整測試**（背景執行，約 8 分鐘）Expected: 全過；`test_sequence_background` 既有不穩定測試若失敗須單獨重跑通過
- [ ] **Step 2: 打包到 `packaging/dist/auto-update/`**，`--help` 啟動 exit 0
- [ ] **Step 3: 本機替換演練（不碰遊戲）**：複製打包的 EXE 到暫存資料夾，用 Python 呼叫 `install_staged`＋`restart_command` 對兩個不同 EXE 做一次替換，確認新 EXE 能啟動（`--help`）、`.old` 於下次 `cleanup_after_update` 被刪
- [ ] **Step 4: 不實際發布**——發布需要使用者說「發布」並先 `gh auth login`
