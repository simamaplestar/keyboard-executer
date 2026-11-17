"""互動式視窗選擇器（demo 與 CLI record 共用）。"""
from __future__ import annotations

from keyboard_executor.platforms.base import WindowInfo


def choose_window(windows: list[WindowInfo], ask=input, echo=print) -> WindowInfo | None:
    """列出視窗讓使用者輸入編號選擇；q 取消回傳 None。無標題的視窗不列入。"""
    candidates = [w for w in windows if w.title.strip()]
    if not candidates:
        echo("目前沒有可選擇的視窗")
        return None
    for i, w in enumerate(candidates, start=1):
        echo(f"{i:3d}. {w.title}（{w.app_name}）")
    while True:
        answer = ask("輸入視窗編號（q 取消）: ").strip()
        if answer.lower() == "q":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        echo(f"請輸入 1–{len(candidates)} 的數字")
