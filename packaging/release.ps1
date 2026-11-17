# 發布新版：packaging\release.ps1 0.6.0 "這版改了什麼"
# 細節見 release.py；專案登入用 python packaging/github_cli.py auth login。
$python = Join-Path $env:USERPROFILE "ke-build-venv\Scripts\python.exe"
& $python (Join-Path $PSScriptRoot "release.py") @args
exit $LASTEXITCODE
