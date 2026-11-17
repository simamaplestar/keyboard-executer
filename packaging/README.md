# Keyboard Executor 打包與發布

## 前置

在專案根目錄，以實際建置用的 Python 執行：

    python -m pip install -e ".[packaging]"
    python packaging/prepare_chat_ocr_models.py

建議使用乾淨 venv。PyInstaller >= 6.16 僅建置期需要；目前 Windows 驗證環境為
Python 3.13。若改用 Python 3.14，先確認 PyInstaller 及原生依賴都有相容版本。
包內含 PySide6、RapidOCR、ONNX Runtime 與離線模型；體積以本次產物為準，不使用 UPX。

### 所有入口共用的 OCR 模型

聊天、圖片順序輸入、文字動作及規則都使用固定的 `rapidocr==3.9.2`、
`onnxruntime==1.30.0` 與 PP-OCRv6 **tiny** 偵測／辨識模型。舊 OCR 引擎、
其 Python 依賴及權重不再收進新包。App 及 PyInstaller 都不負責下載模型。

準備工具沿用 `prepare_chat_ocr_models.py` 名稱及
`~/.keyboard-executor/models/chat-ocr-v6-tiny/` 快取目錄，避免破壞既有指令和快取。
工具從 RapidAI 固定 v3.9.2 網址下載；已有模型時可以完全離線複用：

    python packaging/prepare_chat_ocr_models.py --source-dir <已下載模型的目錄>

每個檔案先驗 SHA256，再原子寫入目的目錄；已有正確快取直接重用。
來源缺檔、雜湊不符或下載失敗皆以非零狀態結束。快取損毀時請處理錯誤訊息指定的檔案，
不要刪除整個使用者模型目錄。`--model-dir` 可另備模型；日常 runtime/spec 仍使用預設目錄。

固定包含三個檔案（合計約 6.9 MB）：

- `PP-OCRv6_det_tiny.onnx`
- `PP-OCRv6_rec_tiny.onnx`
- `ch_ppocr_mobile_v2.0_cls_mobile.onnx`

第三個檔案供 RapidOCR 初始化使用，辨識時關閉方向分類推論。模型名稱、網址及
SHA256 共用 `platforms/common/ocr_rapid.py` 定義。spec 再驗一次 SHA256，收進
`ocr_models/`；凍結 runtime 只從 `sys._MEIPASS/ocr_models/` 載入，不退回舊模型或連網。
使用者既有的舊模型快取不會被本次遷移刪除。

spec 收集 RapidOCR 的 YAML 設定、所需套件 metadata、ONNX 原生函式庫及 OpenCC
字典／設定。OpenCC 只用於圖片順序提示的繁簡比較，原始 OCR 文字及一般正則不改寫。
不再收集建置環境全部 metadata；明確排除 `paddle`、`paddleocr`、`paddlex` 及未使用的
OpenVINO／PyTorch／TensorRT／MNN 後端。

OpenCV 統一使用 `opencv-python`，不再需要 contrib 或 headless 版本。
不要在既有混合安裝環境中只卸載其中一個共用 `cv2` 檔案的 wheel；改用乾淨 venv，
或完整重裝並驗證 `import cv2` 及實際 OCR。`psutil` 為視窗查詢快取的直接依賴，不能
只靠 PyInstaller hidden import 或其他 OCR 套件間接安裝。

### 平台限制

這組版本目前已實機驗證於 **Windows x64／Python 3.13**。
ONNX Runtime 1.30.0 的[官方發布檔](https://pypi.org/project/onnxruntime/1.30.0/#files)
中，macOS wheel 僅提供 Apple Silicon、macOS 14 以上；沒有 Intel Mac wheel。
macOS 支援目標為 **Apple Silicon／macOS 14+／原生 arm64 Python 3.11+**。
不支援 Intel 或 Rosetta，也不自動換成另一套推論後端。Mac 建置及實機驗收需在原生 Mac
執行；Windows／WSL 的測試不能代替 Mac 實機驗收。

## Windows

    powershell -ExecutionPolicy Bypass -File build.ps1
    # → packaging\dist\KeyboardExecutor.exe

Windows 使用 **onefile 單一 exe**，使用者不必另裝 Python 或複製 `_internal/`。
每次啟動會解壓到 `%TEMP%\_MEIxxxxxx`；體積與防毒掃描都會影響冷啟動速度。
未簽章 exe 可能被 SmartScreen 攔截，需選「其他資訊 → 仍要執行」。

spec 的 `_DROP_BINARY_KEYS` 排除未使用的 `opencv_videoio_ffmpeg*.dll`、Qt Quick/QML/PDF，
保留軟體 OpenGL 及所需 runtime DLL。OCR 不使用影片讀寫功能。

發布前應先在獨立 dist/work 目錄 clean build，檢查 archive 內含 v6 三個模型與 OpenCC
字典、沒有舊 OCR 模組／權重，並執行包內實際 OCR、`--help`、隔離資料目錄 GUI
啟動／正常關閉測試。保存建置前後 source hashes，避免把未測試的並行修改混進產物。

替換 `dist/KeyboardExecutor.exe` 前先備份。若使用者仍在執行舊 exe，保留新產物在
獨立目錄並通知使用者關閉後再替換，**不可強制結束使用者程式**。

自簽（測試機信任用；正式憑證另議）：

    New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=KeyboardExecutor" `
      -CertStoreLocation Cert:\CurrentUser\My
    Set-AuthenticodeSignature -FilePath dist\KeyboardExecutor.exe `
      -Certificate (Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert)[0]

## 發布新版（朋友的程式自動更新）

原始碼與 Windows EXE 更新統一使用公開倉庫 `simamaplestar/keyboard-executer`。
程式從該倉庫最新 Release 的 `release.json` 讀取新版資訊，再下載同一版本的
`KeyboardExecutor.exe` 與 `.sha256`。

1. 第一次使用：在 PowerShell 執行 `python packaging/github_cli.py auth login --hostname github.com --git-protocol https --web --scopes workflow`（瀏覽器登入 GitHub 一次）。登入精靈詢問是否設定 Git 憑證時選 No，Git helper 另以專案設定套用。
2. 發布：`packaging\release.ps1 0.6.0 "這版改了什麼"`。
   依序：版本號必須大於目前版本 → 完整測試（失敗項重跑一次）→ 改版本號 → 打包到 `packaging\dist\release-0.6.0\` → 產生 `.sha256` → 啟動打包好的 EXE 做自我檢查（`--self-test`，失敗就不上傳）→ 公開倉庫不存在就建立 → 建立 Release `v0.6.0` 並上傳 EXE 與 `.sha256`。
3. 打包或上傳失敗時版本號會改回原值。腳本不會 commit；發布 tag 與附件位於同一倉庫。

從舊更新來源切換時，已安裝的舊 EXE 仍保留舊網址，須先手動換用包含新設定的版本。
新倉庫需發布 `release.json`、EXE 與 SHA256，客戶端才有新版可下載。

本機為這個專案設定了 `simamaplestar` 帳號。`git config --local
keyboardExecutor.githubConfigDir github-simamaplestar` 讓 GitHub CLI 使用 Git 目錄下的
專用設定；Git credential helper、提交身分與 HTTPS remote 也只設定於本 repo。
`python packaging/github_cli.py auth status` 可檢查專案登入，發布腳本會自動使用同一份設定。
沒有此本機設定的其他 checkout 沿用原本的登入方式。登入資料位於 `.git/` 與系統憑證儲存，
不提交至 Git，也不收進 EXE。

朋友端：啟動 5 秒後與每 6 小時檢查一次；下載完成且沒有腳本／監看／試跑／對話框時才詢問。EXE 所在資料夾不能寫入時改為提示手動下載。舊版 0.5.0 沒有更新功能，第一個有自動更新的版本要手動傳一次。

## macOS（Apple Silicon）

以下從專案根目錄執行，需原生 arm64 Python；不要在 Rosetta 終端機建置：

```bash
python3 packaging/macos_support.py
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,packaging]'
bash packaging/build.sh
```

腳本先檢查 macOS 14+／arm64／Python 3.11+，再準備並驗證三個 OCR 模型，
執行 PyInstaller、驗證 App 完整簽章，以及包內 OCR 子程序實際推論和離屏 GUI 自我檢查。
任一步失敗即以非零狀態停止，不產生新的發布 ZIP。
開始建置時會清除輸出目錄內同名 ZIP／SHA256，避免失敗重建後誤傳舊檔；要保留舊版
請先另存，或用 `KE_DIST_DIR` 指定另一個目錄。壓縮檔和 SHA256 在暫存目錄完整產生後
才放到發布路徑；失敗會回收暫存與這兩個發布檔，不清除其他檔案。

預設產物：

- `packaging/dist/macos-arm64/KeyboardExecutor.app`
- `packaging/dist/macos-arm64/KeyboardExecutor-macos-arm64.zip`
- `packaging/dist/macos-arm64/KeyboardExecutor-macos-arm64.zip.sha256`

使用 `ditto --keepParent` 保留 PyInstaller／Qt framework 的符號連結，請傳 ZIP，
不要將 `.app` 內部檔案逐一複製到不支援符號連結的磁碟。接收者解壓縮後，先把 App
拖到「應用程式」，再開啟及授權；無需 Python 或連網下載模型。

可選環境變數：`PYTHON` 指定建置用 Python（預設 `python3`），`OCR_SOURCE_DIR`
從既有本機模型完全離線建置，`KE_DIST_DIR`／`KE_WORK_DIR` 指定獨立輸出與快取目錄。
預設快取在 `packaging/build/macos-arm64/`，不與 Windows 輸出混用。

預設由 PyInstaller 使用 ad-hoc 簽章。重建後可能需重新授權 TCC，Gatekeeper 也可能
攔截；確認來源後可至「系統設定 → 隱私權與安全性」按「仍要打開」。
正式發布時，在建置前透過環境變數交給 PyInstaller，由內而外簽章及套用 entitlements：

```bash
CODESIGN_IDENTITY='Developer ID Application: <名稱> (<TEAMID>)' bash packaging/build.sh
xcrun notarytool submit packaging/dist/macos-arm64/KeyboardExecutor-macos-arm64.zip \
  --keychain-profile ke-notary --wait
xcrun stapler staple packaging/dist/macos-arm64/KeyboardExecutor.app
```

`ke-notary` 是建置機事先建立的公證憑證 profile。公證成功、staple 後重新產生 ZIP
及 SHA256，再交付給接收者：

```bash
cd packaging/dist/macos-arm64
ditto -c -k --sequesterRsrc --keepParent KeyboardExecutor.app KeyboardExecutor-macos-arm64.zip
shasum -a 256 KeyboardExecutor-macos-arm64.zip > KeyboardExecutor-macos-arm64.zip.sha256
spctl --assess --type execute --verbose=2 KeyboardExecutor.app
```

App 啟動時請求輔助使用／螢幕錄製／輸入監控，權限橫幅可開啟對應系統設定。
pywinctl 視窗操作另可能要求「系統事件」自動化權限。授權後完整結束再重開 App。
實機錄製、回放、F10、Retina／多螢幕及 OCR 依
[`Mac 驗收表`](../docs/macos-manual-checklist.md) 操作，不能只以自我檢查取代。

### 使用 GitHub Actions 建置

原始碼倉庫包含 `.github/workflows/build-macos.yml`，手動在 Actions 選擇
**Build macOS Apple Silicon → Run workflow**。需先將本次修改與其依賴的現有原始碼
一併存到要建置的分支；流程只會讀該分支已提交的內容。

流程使用 GitHub 的 `macos-15` arm64 runner 與 Python 3.13，跑 Mac 相容性測試後建置
並自我檢查 App；成功後下載 `KeyboardExecutor-macos-arm64` artifact，裡面是可傳送的
ZIP 與 SHA256。artifact 保存 14 天，使用 ad-hoc 簽章；不會建立公開 Release，
也不會啟用 Mac 自動更新。runner 規格見 [GitHub 官方清單](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

## 實機驗收限制

單元測試、兩張離線圖片、包內 OCR 或 GUI smoke 都不能證明真實遊戲成功率。
另驗證 pydirectinput、DPI／多螢幕、焦點安全、完整圖片輪播、AI 延遲及 Discord 送達。
詳見 `docs/sequence-input-manual-checklist.md` 與
[`全入口 OCR 遷移報告`](../docs/unified-ocr-migration-report.md)（含已知字形漏辨限制）。
