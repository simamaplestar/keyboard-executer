"""不需互動的背景工具不得開啟主控台，避免搶走使用者的前景視窗。"""
import os
import subprocess


def background_process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class _BackgroundPopen(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        kwargs["creationflags"] = (kwargs.get("creationflags", 0)
                                   | subprocess.CREATE_NO_WINDOW)
        super().__init__(*args, **kwargs)


def configure_background_child():
    """僅供專用 OCR 子程序：Paddle 載入時的 where 等探測也不得彈窗。"""
    if os.name == "nt":
        subprocess.Popen = _BackgroundPopen
