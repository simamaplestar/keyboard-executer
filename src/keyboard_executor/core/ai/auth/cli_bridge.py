"""Locate official AI CLIs, including a Windows-to-WSL fallback."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from keyboard_executor.platforms.common.process import background_process_options


def macos_cli_prefix(executable: str, *, run=subprocess.run,
                     platform_name: str | None = None) -> list[str] | None:
    """Finder 不繼承終端機 PATH；讓登入 shell 載入 Homebrew／npm／使用者設定。

    只在探測時讀取 .zshrc，支援以 nvm 安裝的官方 CLI；探測最多等候八秒。
    執行時透過 env 帶入 PATH 並直接啟動檔案，避免 shell 歡迎訊息污染 JSON。
    """
    if (platform_name or sys.platform) != "darwin":
        return None
    try:
        script = ('cli=$(whence -p -- "$1") || exit 1; '
                  'printf "\\n__KEYBOARD_EXECUTOR_CLI__=%s\\n'
                  '__KEYBOARD_EXECUTOR_PATH__=%s\\n" "$cli" "$PATH"')
        probe = run(["/bin/zsh", "-lic", script, "keyboard-executor", executable],
                    capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    values = {}
    for line in (probe.stdout or "").splitlines():
        if line.startswith(("__KEYBOARD_EXECUTOR_CLI__=", "__KEYBOARD_EXECUTOR_PATH__=")):
            name, value = line.split("=", 1)
            values[name] = value
    path = values.get("__KEYBOARD_EXECUTOR_CLI__", "")
    search_path = values.get("__KEYBOARD_EXECUTOR_PATH__", "")
    if not path.startswith("/") or not search_path:
        return None
    return ["/usr/bin/env", f"PATH={search_path}", path]


def wsl_cli_prefix(executable: str, *, which: Callable[[str], str | None],
                   run=subprocess.run, platform_name: str = os.name) -> list[str] | None:
    """Return a safe argv prefix that forwards later arguments through WSL.

    npm-installed CLIs commonly live in a login shell's PATH, so ``wsl -e
    executable`` is insufficient.  ``$@`` forwards only argv supplied by this
    application; no user text is interpolated into the shell command.
    """
    if platform_name != "nt":
        return None
    wsl = which("wsl.exe") or which("wsl")
    if not wsl:
        return None
    try:
        probe = run([wsl, "-e", "bash", "-lc", f"command -v {executable}"],
                    capture_output=True, text=True, timeout=8, check=False,
                    **background_process_options())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0 or not (probe.stdout or "").strip():
        return None
    return [wsl, "-e", "bash", "-lc", f'exec {executable} "$@"', executable]


def command_uses_wsl(command: list[str]) -> bool:
    if not command:
        return False
    name = str(command[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in ("wsl", "wsl.exe")


def path_for_cli(path: str, *, uses_wsl: bool, run=subprocess.run) -> str:
    """把本機絕對路徑轉成 CLI 可讀路徑；Windows→WSL 用官方 wslpath。"""
    absolute = str(Path(path).resolve())
    if not uses_wsl or os.name != "nt":
        return absolute
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return absolute
    try:
        result = run([wsl, "-e", "wslpath", "-a", "-u", absolute],
                     capture_output=True, text=True, timeout=8, check=False,
                     **background_process_options())
    except (OSError, subprocess.TimeoutExpired):
        return absolute
    converted = (result.stdout or "").strip()
    return converted if result.returncode == 0 and converted else absolute
