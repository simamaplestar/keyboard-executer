"""AI stdio 子程序不得開啟主控台搶走遊戲焦點。"""
import io
import os
import subprocess

import pytest

from keyboard_executor.core.ai.auth.codex_account import JsonRpcProcess, codex_command


@pytest.mark.skipif(os.name != "nt", reason="Windows console creation flags")
def test_codex_rpc_is_started_without_a_console_window():
    captured = {}

    class Process:
        stdin = io.StringIO()
        stdout = io.StringIO()

        def wait(self, timeout):
            return 0

    def popen(*args, **kwargs):
        captured.update(kwargs)
        return Process()

    rpc = JsonRpcProcess(["codex", "app-server"], popen=popen)
    rpc.close()
    assert captured.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="Windows console creation flags")
def test_wsl_probe_does_not_open_a_console_before_rpc_starts():
    captured = {}

    def run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="/usr/bin/codex")

    command = codex_command(lambda name: "wsl.exe" if name == "wsl.exe" else None,
                            run=run, platform_name="nt")
    assert command[0] == "wsl.exe"
    assert captured.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="Windows console creation flags")
def test_ocr_child_library_subprocesses_have_no_console(monkeypatch):
    import sys
    from keyboard_executor.platforms.common.process import configure_background_child

    # 撤銷測試中的子程序限定設定，避免影響其他測試的 Popen seam。
    monkeypatch.setattr(subprocess, "Popen", subprocess.Popen)
    configure_background_child()
    result = subprocess.check_output([
        sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"],
        text=True)
    assert result.strip() == "0"
