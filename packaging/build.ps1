# Windows 打包：產出 packaging\dist\KeyboardExecutor\KeyboardExecutor.exe。
# 前置：Windows 機器、venv 內 pip install -e ".[packaging]"。
# 自簽與驗收步驟見 README.md。本腳本尚未實機驗證（Windows backlog，M5 如實記錄）。
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m PyInstaller --clean --noconfirm keyboard-executor.spec
Write-Host "完成：$PSScriptRoot\dist\KeyboardExecutor.exe（onefile，單檔即可發布）"
