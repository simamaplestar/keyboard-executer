@echo off
setlocal
set "KE_PYTHON=%USERPROFILE%\ke-build-venv\Scripts\python.exe"
set "PYTHONPATH=%~dp0..\src"
set "QT_QPA_PLATFORM=offscreen"
pushd "%~dp0.."
if errorlevel 1 exit /b 1
if not exist "%KE_PYTHON%" (
    echo Missing build environment: "%KE_PYTHON%"
    goto failed
)
echo Running Windows regression tests...
"%KE_PYTHON%" -m pytest -q
if errorlevel 1 goto failed
cd /d "%~dp0"
echo Building the chat update in a separate output directory...
"%KE_PYTHON%" -m PyInstaller --clean --noconfirm --distpath "%~dp0dist\ai-chat-speed" --workpath "%~dp0build\ai-chat-speed" keyboard-executor.spec
if errorlevel 1 goto failed
"%~dp0dist\ai-chat-speed\KeyboardExecutor.exe" --help
if errorlevel 1 goto failed
echo New executable: "%~dp0dist\ai-chat-speed\KeyboardExecutor.exe"
popd
pause
exit /b 0
:failed
echo Tests or build failed. See the output above. The existing executable was not replaced.
popd
pause
exit /b 1
