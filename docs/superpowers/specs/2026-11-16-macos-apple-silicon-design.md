# Apple Silicon macOS 支援

使用者選定 Apple Silicon（M 系列）、macOS 14 以上，並要求沿建議直接實作。

## 目標與限制

沿用 Python 3.11+／PySide6 桌面程式，讓使用者可以從原始碼執行，或在原生
Apple Silicon Mac 建置附離線 OCR 模型的 `KeyboardExecutor.app`。Windows 行為保持相容。
不支援 Intel／Rosetta，不更換已固定的 RapidOCR 3.9.2／ONNX Runtime 1.30.0／v6 tiny 模型。
現有工作區包含大量未提交功能，修改必須保留它們；不提交或發布使用者的其他變更。

## Approaches

1. 沿用現有 macOS pynput／pywinctl／mss 後端及 PyInstaller .app：最少重寫，
   使用者選擇此方案。
2. 重寫原生 Swift 前端或另做 Web 介面：需要重做編輯器和系統操作，與現有需求不合。
3. 同時支援 Intel：需要另一套 ONNX Runtime 版本及額外驗證，使用者未選擇。

## 實作決策

- 鍵盤映射只載入平台實際提供的鍵；Windows 專用鍵在 Mac 明確報錯，不可使模組匯入失敗。
- Mac 編輯器只提供標準輸入；Windows 腳本可在 Mac 使用標準後端播放並留下提示，
  儲存時清除 Windows 專用輸入旗標。
- 補齊輔助使用的主動請求，保留輸入監控與螢幕錄製引導。F9／F10 需在 Mac 設定
  標準功能鍵或搭配 Fn；TCC 實際授權必須由使用者於 Mac 進行。
- 補 Mac 腳本啟動熱鍵；沿用播放器既有 F10／滑鼠角落停止機制。
- Claude setup-token 存 Mac Keychain；Finder 啟動時缺少的 CLI PATH 透過登入 shell 查找。
- 建置腳本檢查原生 arm64、macOS 14+ 及 Python 版本，準備／驗證離線模型，
  執行 PyInstaller、簽章驗證與包內自我檢查，產生保留 .app 符號連結的 ZIP。
  允許指定 Developer ID；未指定使用 ad-hoc。正式公證保留為有憑證時的獨立步驟。
- 加入 GitHub Actions 的手動 Mac 建置流程，產物只存為 workflow artifact，不自動發布。
- Mac 自動更新不在本次範圍；既有 Windows EXE 更新流程保持不變。

## 驗證

在現有 Windows 環境跑平台替身測試、GUI 離屏回歸及完整 pytest；使用真實 Darwin
pynput 按鍵集合模擬匯入以捕捉原先啟動崩潰。Mac CI 使用原生 arm64 執行相關測試、
建置及包內 OCR／GUI 自我檢查。實機 TCC、視窗前景切換、Retina／多螢幕座標、
錄製／回放／快捷鍵需照驗收表在 Mac 操作；Windows 測試不宣稱已完成實機 Mac 驗收。
