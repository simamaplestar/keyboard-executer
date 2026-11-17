# macOS Apple Silicon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Apple Silicon／macOS 14+ 的執行相容性與可重現 .app 建置流程。

**Architecture:** 延伸現有 Darwin 後端，保留共用播放器、OCR 與 PySide6 編輯器。
平台差異集中於 Darwin、平台工廠及必要的 GUI／認證入口。

**Tech Stack:** Python 3.11+、PySide6、pynput、pywinctl、mss、RapidOCR、ONNX Runtime、PyInstaller。

**Spec:** `docs/superpowers/specs/2026-11-16-macos-apple-silicon-design.md`

## Global Constraints

- Apple Silicon（M 系列）、macOS 14 以上；不支援 Intel／Rosetta。
- RapidOCR 3.9.2／ONNX Runtime 1.30.0／v6 tiny 模型不變。
- 保留目前工作區修改；不提交或發布使用者的其他變更。
- macOS 不走 Windows EXE 自動更新。

## Review Focus

- Darwin 缺少的 Windows 按鍵不得中斷整個 GUI 匯入。
- Windows 腳本在 Mac 執行及編輯後儲存應使用標準輸入。
- 重複／含停止鍵的啟動熱鍵不得造成多重啟動。
- Finder 的精簡 PATH 與含空白路徑不得破壞 AI CLI 啟動。
- OCR 子程序必須在 frozen .app 使用 freeze_support；ZIP 必須保留框架符號連結。

### Task 1: 鍵盤與輸入相容性

**Files:** `platforms/common/keymap.py`、`platforms/factory.py`、`app/script_editor.py`，及對應 tests。
**Interfaces:** `parse_key(name)` 對 Mac 不支援的鍵拋 ValueError；`ScriptEditorDialog(..., platform_name=None)` 可注入平台。

- [x] 加入 Darwin 按鍵集合的隔離匯入與不支援按鍵測試，先確認失敗。
- [x] 改以平台實際支援的按鍵建立映射，保留 Windows 全集合。
- [x] 加 Mac 標準模式／Windows 腳本轉存測試，先確認失敗，再實作選單與後端提示。
- [x] 驗證：`python -m pytest -q tests/platforms tests/app/test_script_editor_widget.py`，預期全數通過（平台限定項可略過）。

### Task 2: 權限與啟動熱鍵

**Files:** `platforms/darwin/permissions.py`、`app/application.py`、新增 `app/pynput_hotkeys.py`、`app/main_window.py`，及對應 tests。
**Interfaces:** `request_accessibility(_request=None)`；`PynputScriptHotkeys.start(bindings)`／`stop()`，bindings 為腳本名與按鍵名稱串列。

- [x] 先以注入原生呼叫驗證輔助使用請求與 GUI 接線。
- [x] 先測按下／放開、重複事件、衝突及關閉，再補 Mac 啟動熱鍵並接入主視窗生命週期。
- [x] 驗證：`python -m pytest -q tests/platforms/test_darwin_permissions.py tests/app/test_application.py tests/app/test_main_window.py tests/app/test_pynput_hotkeys.py`，預期通過。

### Task 3: Mac AI 登入

**Files:** `core/ai/auth/secret_store.py`、`core/ai/auth/cli_bridge.py`、`claude_auth.py`、`codex_account.py`、`pyproject.toml`，及對應 tests。
**Interfaces:** `MacOSKeychainStore` 實作 SecretStore；`macos_cli_prefix(executable, ...) -> list[str] | None` 使用登入 shell 安全轉送 argv。

- [x] 先測 Keychain 寫入／讀回／刪除／錯誤不洩漏 token，再實作。
- [x] 先測精簡 PATH 下 CLI 查找、逾時與帶空白／特殊字元參數，再接入兩個認證命令。
- [x] 驗證：`python -m pytest -q tests/core/test_ai_auth_store.py tests/core/test_ai_claude_auth.py tests/core/test_ai_codex_account.py tests/core/test_macos_cli.py`，預期通過。

### Task 4: 建置與驗收

**Files:** `packaging/build.sh`、`packaging/keyboard-executor.spec`、`app/self_test.py`、新增 `.github/workflows/build-macos.yml`、`README.md`、`packaging/README.md`、`docs/macos-manual-checklist.md`。
**Interfaces:** `bash packaging/build.sh` 在原生 Mac 產生 `.app`、ZIP、SHA256；`PYTHON`／`CODESIGN_IDENTITY` 供建置設定。

- [x] 先以可控制的工具替身執行 build.sh，驗證拒絕非 Mac／Intel／舊 OS／非 arm64 Python與錯誤傳遞。
- [x] 實作模型準備、arm64 PyInstaller、簽章、自我檢查與 ditto ZIP；spec 設定最低系統版本與簽章。
- [x] 加入手動原生 Mac CI 並更新安裝／使用／實機驗收說明。
- [x] 驗證：`bash -n packaging/build.sh`、建置腳本行為測試、完整 `python -m pytest -q`；審查本次增量並記錄原生 Mac 尚待執行的驗收。
