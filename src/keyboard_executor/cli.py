"""CLI 進入點。

    python -m keyboard_executor.cli list                 # 列出腳本
    python -m keyboard_executor.cli play <腳本名稱>      # 回放（F10/左上角/Ctrl+C 可中斷）
    python -m keyboard_executor.cli record               # 錄製（F9 開始/停止，F10 放棄）
    python -m keyboard_executor.cli watch                # 監看規則（stop_all 觸發、F10/左上角或 Ctrl+C 停止）

腳本目錄預設 ~/.keyboard-executor/scripts，可用 --dir 覆寫。
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
from pathlib import Path

from keyboard_executor import __version__
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.core.models import (
    Script,
    ScriptSettings,
    ScriptValidationError,
    TargetWindow,
)
from keyboard_executor.core.logging_config import setup_logging
from keyboard_executor.core.player import Player
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.picker import choose_window
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook
from keyboard_executor.platforms.factory import get_platform
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.templates import TemplateStore


def default_scripts_dir() -> Path:
    return Path.home() / ".keyboard-executor" / "scripts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="keyboard-executor CLI")
    parser.add_argument("--version", action="version",
                        version=f"keyboard-executor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="回放腳本")
    play.add_argument("name", help="腳本名稱（不含 .json）")
    play.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")

    list_cmd = sub.add_parser("list", help="列出腳本")
    list_cmd.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")

    record = sub.add_parser("record", help="錄製腳本（F9 開始/停止，F10 放棄）")
    record.add_argument("--dir", default=None, help="腳本目錄（預設 ~/.keyboard-executor/scripts）")
    record.add_argument("--title", default=None,
                        help="目標視窗標題（regex）；省略時改用互動式選單")
    record.add_argument("--full-trajectory", action="store_true",
                        help="完整軌跡模式：保留滑鼠移動路徑（預設只留點擊/拖曳/捲動）")

    watch = sub.add_parser("watch", help="監看規則（Ctrl+C 停止）")
    watch.add_argument("--dir", default=None, help="資料目錄（預設 ~/.keyboard-executor/scripts）")

    return parser


def _check_darwin_permissions() -> bool:
    if sys.platform != "darwin":
        return True
    from keyboard_executor.platforms.darwin.permissions import (
        ACCESSIBILITY_GUIDE,
        check_accessibility,
    )

    if not check_accessibility():
        print(ACCESSIBILITY_GUIDE, file=sys.stderr)
        return False
    return True


def run_record(platform, storage, hook, ask=input, echo=print,
               guard_factory=SessionGuard, recorder_factory=Recorder,
               title_pattern: str | None = None, full_trajectory: bool = False) -> int:
    """錄製流程（元件全注入，供單元測試）。回傳 exit code：0 成功存檔、1 失敗/放棄。"""
    wm = platform.window_manager
    if title_pattern:
        windows = wm.find_windows(title_pattern=title_pattern)
        if not windows:
            echo(f"找不到符合 {title_pattern!r} 的視窗")
            return 1
        win = windows[0]
    else:
        win = choose_window(wm.list_all(), ask=ask, echo=echo)
        if win is None:
            return 1
    echo(f"目標視窗：{win.title}（{win.app_name}）")

    recorder = recorder_factory(Point(win.x, win.y),
                                mode="full" if full_trajectory else "simplified")
    stop_event = threading.Event()
    done = threading.Event()
    recording = False

    def on_toggle() -> None:
        nonlocal recording
        if done.is_set():
            return
        if recording:
            done.set()
        else:
            recording = True
            echo("錄製中……再按 F9 停止")

    guard = guard_factory(hook, stop_event, on_toggle=on_toggle)

    dispatch_lock = threading.Lock()

    def dispatch(event) -> None:
        with dispatch_lock:  # keyboard/mouse listener 各一執行緒，序列化進 Recorder
            guard.handle(event)  # 控制語義優先（F9 切換、F10/角落停止）
            if recording and not done.is_set() and not guard.is_control_event(event):
                recorder.feed(event)  # 自我過濾：控制鍵與 toggle 前的事件不進腳本

    try:
        hook.start(dispatch)
    except Exception as e:
        echo(f"無法啟動輸入監聽（可能缺輸入監控權限）：{e}")
        return 1
    echo("按 F9 開始錄製，再按 F9 停止，F10 放棄")
    try:
        while not done.is_set() and not stop_event.is_set():
            stop_event.wait(0.05)
    finally:
        hook.stop()

    if stop_event.is_set():
        echo("已放棄錄製")
        return 1
    actions = recorder.finish()
    if not actions:
        echo("沒有錄到任何動作")
        return 1

    title = re.escape(win.title) if win.title.strip() else None
    app = win.app_name if win.app_name.strip() else None
    if title is None and app is None:
        echo("目標視窗沒有標題與應用程式名稱，無法建立腳本")
        return 1
    target = TargetWindow(title_pattern=title, app_name=None if title else app)
    name = ask("腳本名稱: ").strip()
    script = Script(name=name, target_window=target,
                    actions=tuple(actions), settings=ScriptSettings())
    try:
        path = storage.save(script)
    except ScriptValidationError as e:
        echo(f"儲存失敗：{e}")
        return 1
    echo(f"已儲存：{path}（共 {len(actions)} 個動作）")
    return 0


def _start_play_guard(player: Player) -> SessionGuard | None:
    """best-effort 啟動 F10/左上角緊急停止；失敗（如缺輸入監控權限）不阻斷回放。"""
    try:
        guard = SessionGuard(PynputInputHook(), player.stop_event)
        guard.start()
        return guard
    except Exception:
        print("緊急停止熱鍵無法啟用（可能缺輸入監控權限），仍可用 Ctrl+C", file=sys.stderr)
        return None


def _start_watch_guard(stop_event: threading.Event,
                       hook_factory=PynputInputHook) -> SessionGuard | None:
    """best-effort 啟動 watch 迴圈的 F10/左上角緊急停止；失敗（如缺輸入監控權限）
    不阻斷監看，仍可用 Ctrl+C 或規則的 stop_all 觸發。"""
    try:
        guard = SessionGuard(hook_factory(), stop_event)
        guard.start()
        return guard
    except Exception:
        print("緊急停止熱鍵無法啟用（可能缺輸入監控權限），仍可用 Ctrl+C", file=sys.stderr)
        return None


def run_watch(platform, rule_storage, script_storage, templates, echo=print,
              engine_factory=RuleEngine, rules=None, stop_event=None) -> int:
    """監看流程（元件全注入，供單元測試）。回傳 exit code。

    stop_event 由呼叫端注入時（真實 CLI 路徑，見 main），供外部 SessionGuard
    共用同一顆事件，如此 F10/滑鼠甩左上角才能與 stop_all 觸發、Ctrl+C 一樣
    中斷監看；未注入時建立獨立事件（供不需要 guard 的單元測試使用）。
    """
    rules = rules if rules is not None else rule_storage.load_enabled()
    if not rules:
        echo("沒有啟用中的規則")
        return 0
    echo(f"開始監看 {len(rules)} 條規則（Ctrl+C 停止）")

    # 建立（或沿用注入的）共用 stop_event，並以 player_factory 閉包把它穿透給
    # RuleEngine 觸發 run_script 時建立的 Player：如此 stop_all 觸發（或 Ctrl+C、
    # F10/左上角 failsafe）才能立即中斷正在執行中的規則腳本。
    stop_event = stop_event if stop_event is not None else threading.Event()

    def player_factory_with_stop(*args, **kwargs):
        return Player(*args, stop_event=stop_event, **kwargs)

    def cli_notifier(message, *, image_png=None):
        echo(message)   # CLI 無 Discord 扇出，忽略截圖（截圖只用於 Discord 通知）

    engine = engine_factory(platform, storage=script_storage,
                            templates=templates, notifier=cli_notifier,
                            player_factory=player_factory_with_stop,
                            stop_event=stop_event)

    try:
        engine.run(rules)
    except KeyboardInterrupt:
        echo("\n已停止監看")
    return 0


def main(argv: list[str] | None = None, *,
         get_platform=get_platform, player_factory=Player,
         check_permissions=_check_darwin_permissions,
         run_record_fn=run_record, run_watch_fn=run_watch,
         guard_starter=_start_play_guard,
         watch_guard_starter=_start_watch_guard,
         hook_factory=PynputInputHook) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(args.dir) if args.dir else default_scripts_dir()
    setup_logging(data_root / "logs")
    storage = ScriptStorage(data_root)

    if args.command == "list":
        names = storage.list_names()
        if not names:
            print("（沒有腳本）")
        for name in names:
            print(name)
        return 0

    if args.command == "record":
        if not check_permissions():
            return 1
        platform = get_platform()
        return run_record_fn(platform, storage, hook_factory(),
                             title_pattern=args.title,
                             full_trajectory=args.full_trajectory)

    if args.command == "watch":
        if not check_permissions():
            return 1
        platform = get_platform()
        data_dir = data_root
        stop_event = threading.Event()
        guard = watch_guard_starter(stop_event, hook_factory)
        try:
            return run_watch_fn(platform, RuleStorage(data_dir), storage,
                                TemplateStore(data_dir).load_template,
                                stop_event=stop_event)
        finally:
            if guard is not None:
                try:
                    guard.stop()
                except Exception:
                    pass  # 守護收尾失敗不影響監看結果

    # play
    if not check_permissions():
        return 1
    try:
        script = storage.load(args.name)
    except ScriptValidationError as e:
        print(f"腳本載入失敗：{e}", file=sys.stderr)
        return 1

    platform = get_platform(
        game_input_mode=script.settings.game_input_mode,
        window_message_mode=script.settings.window_message_mode,
        scan_pulse_mode=script.settings.scan_pulse_mode)
    data_dir = data_root
    player = player_factory(platform, storage=storage,
                            templates=TemplateStore(data_dir).load_template)
    guard = guard_starter(player)
    print(f"開始回放：{script.name}（F10 或滑鼠甩到螢幕左上角可緊急停止；Ctrl+C 亦可）")
    try:
        result = player.play(script)
    except KeyboardInterrupt:
        print("\n已中斷（Ctrl+C）", file=sys.stderr)
        return 1
    finally:
        if guard is not None:
            try:
                guard.stop()
            except Exception:
                pass  # 守護收尾失敗不影響回放結果
    if result.ok:
        print(f"回放完成，共執行 {result.actions_run} 個動作")
        return 0
    print(f"回放中止：{result.error}（已執行 {result.actions_run} 個動作）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
