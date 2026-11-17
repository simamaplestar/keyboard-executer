"""M1 驗收 demo：把目標視窗切到前景，執行一段寫死的動作序列。

不給 --title 時會列出目前所有視窗，輸入編號選擇目標：
    python -m keyboard_executor.demo
也可用標題 regex 直接指定：
    python -m keyboard_executor.demo --title "未命名|Untitled"   # macOS 文字編輯
    python -m keyboard_executor.demo --title "記事本|Notepad"    # Windows 記事本
"""
from __future__ import annotations

import argparse
import sys
import time

from keyboard_executor.core.geometry import Point, to_absolute
from keyboard_executor.picker import choose_window  # re-export：既有測試/呼叫端沿用此路徑
from keyboard_executor.platforms.factory import get_platform

__all__ = ["build_parser", "choose_window", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M1 demo：對指定視窗執行寫死的動作序列")
    parser.add_argument("--title", default=None, help="目標視窗標題（regex）；省略時改用互動式選單")
    parser.add_argument(
        "--game-input", action="store_true",
        help="Windows 遊戲輸入模式（pydirectinput scan code）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if sys.platform == "darwin":
        from keyboard_executor.platforms.darwin.permissions import (
            ACCESSIBILITY_GUIDE,
            check_accessibility,
        )

        if not check_accessibility():
            print(ACCESSIBILITY_GUIDE, file=sys.stderr)
            return 1

    platform = get_platform(game_input_mode=args.game_input)

    if args.title:
        windows = platform.window_manager.find_windows(title_pattern=args.title)
        if not windows:
            print(f"找不到符合 {args.title!r} 的視窗", file=sys.stderr)
            return 1
        win = windows[0]
    else:
        win = choose_window(platform.window_manager.list_all())
        if win is None:
            return 1
    print(f"目標視窗：{win.title}（{win.app_name}）@ ({win.x}, {win.y}) {win.width}x{win.height}")

    if not platform.window_manager.activate(win):
        print("無法將視窗切到前景", file=sys.stderr)
        return 1
    time.sleep(0.3)  # 前景切換後留給系統穩定的時間

    origin = Point(win.x, win.y)
    center = to_absolute(origin, Point(win.width // 2, win.height // 2))
    backend = platform.input_backend
    backend.mouse_click(center.x, center.y)
    backend.type_text("hello from keyboard-executor")
    backend.key_press("enter")
    backend.type_text("M1 acceptance ok")
    print("動作序列執行完畢")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
