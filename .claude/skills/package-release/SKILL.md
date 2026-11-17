---
name: package-release
description: Keyboard Executor 的打包、訂版、發布流程（PyInstaller EXE、packaging/release.py、simamaplestar/keyboard-executer 自動更新）。使用者說「打包」「訂版」「發布」「出新版」「上傳新版」「給朋友更新」「release」「build exe」，或改完程式要交付 EXE 時使用。
---

# 打包與發布

三種動作，依使用者用詞選一種。**只有使用者明確說「發布」才上傳**；「打包」「訂版」都不上傳。

| 使用者說 | 動作 | 會上傳嗎 |
|---|---|---|
| 改完程式（沒特別說）、「打包」「給我 EXE」 | A. 測試用打包 | 否 |
| 「訂版 X.Y.Z」「打包訂版」 | B. 訂版只打包 | 否 |
| 「發布」「出新版給朋友」「上傳」 | C. 發布 | 是 |

一律在背景執行（完整測試約 8 分鐘、打包約 3 分鐘），完成後回報 EXE 路徑。

## 共用環境

- 專案：`/mnt/d/keyboard-executor`（從 WSL 編輯，Windows 端執行）
- Python：使用已安裝 `dev` 與 `packaging` 依賴的原生 Windows 虛擬環境。執行前依本機路徑設定 `PY`，後續 `$PY` 都指向該環境的 `python.exe`；WSL 也透過這個 Windows Python 執行。
- 版本號單一來源：`src/keyboard_executor/__init__.py` 的 `__version__`，`pyproject.toml` 同步；**只能由 release.py 改**
- 輸出含中文時 Windows 端是 cp950：讀 log 用 `iconv -f cp950 -t utf-8`
- **不要關掉使用者正在執行的 KeyboardExecutor.exe**
- 不 commit、不打 tag（使用者沒要求）
- 原始碼、發布與更新使用 `simamaplestar/keyboard-executer`；發布腳本從 `core/update/release.py` 讀取共用 `REPO`。
- 本機以 `git config --local keyboardExecutor.githubConfigDir github-simamaplestar` 指定專案登入；`packaging/github_cli.py` 與發布腳本共用這份設定，不切換其他專案的帳號。

## A. 測試用打包（版本號不變）

1. 完整測試（背景）：
   `cd /mnt/d/keyboard-executor && QT_QPA_PLATFORM=offscreen $PY -m pytest -q -p no:cacheprovider > <log> 2>&1`
2. 打包到新資料夾（名稱描述這次改動，例如 `chat-fix`）：
   `cd packaging && $PY -m PyInstaller --noconfirm --distpath dist/<名稱> --workpath build/keyboard-executor keyboard-executor.spec`
3. 試開：`dist/<名稱>/KeyboardExecutor.exe --help` 回 exit 0；必要時 `--self-test`（需 `QT_QPA_PLATFORM=offscreen`）
4. 回報 `D:\keyboard-executor\packaging\dist\<名稱>\KeyboardExecutor.exe`

## B. 訂版只打包

`cd /mnt/d/keyboard-executor && $PY packaging/release.py --build-only X.Y.Z "更新說明" > <log> 2>&1`

做：完整測試（失敗項 `--lf` 重跑一次）→ 改版本號 → 打包到 `packaging/dist/release-X.Y.Z/` → 產生 `.sha256`、`release.json` → `--self-test`。失敗會把版本號改回。

之後要發布同一版：版本號已是 X.Y.Z，`release.py X.Y.Z` 會拒絕（必須大於目前版本）。改用 gh 直接上傳既有檔案：
`python packaging/github_cli.py release create vX.Y.Z <exe> <exe>.sha256 <release.json> --repo simamaplestar/keyboard-executer --title vX.Y.Z --notes "<說明>"`

## C. 發布（使用者說「發布」才做）

1. 確認登入：Windows 端 `python packaging/github_cli.py auth status`（本專案帳號 `simamaplestar`）。未登入時用同一入口執行 `auth login --hostname github.com --git-protocol https --web --scopes workflow`；登入精靈詢問設定 Git 憑證時選 No，Git helper 另以 `git config --local` 設定。
2. 版本號：沒指定就把目前版本第三位加 1，並告訴使用者。更新說明用朋友看得懂的中文寫這版改了什麼。
3. 執行（背景）：
   `cd /mnt/d/keyboard-executor && $PY packaging/release.py X.Y.Z "更新說明" > .superpowers/release-X.Y.Z.log 2>&1`
   流程：完整測試 → 改版本號 → 打包 `dist/release-X.Y.Z/` → `.sha256`＋`release.json` → `--self-test`（壞的 EXE 不會上傳）→ 公開倉庫不存在就建 → `gh release create` 上傳三個檔
4. 驗證朋友端看得到：
   `curl -sL https://github.com/simamaplestar/keyboard-executer/releases/latest/download/release.json` 應顯示新版本
5. 回報：下載頁 `https://github.com/simamaplestar/keyboard-executer/releases/latest`、本機 EXE 路徑；朋友的程式會在 6 小時內（或重開後 5 秒）自動提示更新

使用者自己跑：PowerShell `packaging\release.ps1 X.Y.Z "說明"`（加 `--build-only` 只打包）。

## 已踩過的坑

- **不可用 api.github.com 檢查新版**：未登入每小時 60 次，共用網路會用完（實測 403）。朋友端讀 `releases/latest/download/release.json`，release.py 會自動上傳它；發布時三個檔缺一不可。
- 發布被測試擋下時，先看失敗是不是寫死版本號或時序不穩定的測試，修測試本身（不改產品行為），再重跑發布。
- 要中止進行中的發布：PowerShell 找 CommandLine 含 `release.py` 與 `ke-build-venv` 的 pytest 程序並 `Stop-Process`；版本號在測試階段之後才改，測試中中止不用還原。
- 視窗標題固定「Keyboard Executor」不寫版本（使用者要求）；版本只顯示在頂部 `QLabel#ver`，讀 `__version__`。
- v0.6.0 內含舊的 API 檢查碼，不要給朋友。
- 程式碼與設計：`src/keyboard_executor/core/update/`、`app/update_controller.py`、`app/self_test.py`、`packaging/release.py`；設計文件 `docs/superpowers/specs/2026-11-02-auto-update-design.md`。
