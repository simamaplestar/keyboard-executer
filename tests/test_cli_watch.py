import numpy as np

from keyboard_executor.cli import build_parser, main, run_watch
from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from keyboard_executor.storage.rules import RuleStorage
from tests.fakes import (
    FakeInputBackend,
    FakeInputHook,
    FakeOcrEngine,
    FakeScreenCapture,
    FakeWindowManager,
)


def make_rule(name="規則", enabled=True):
    return rule_from_dict({
        "name": name, "target_window": {"title_pattern": "記事本"},
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "notify", "message": "y"}, "enabled": enabled})


class OneShotStopEvent:
    """讓 RuleEngine.run() 的輪詢迴圈只跑一輪就結束：is_set() 首次呼叫回 False
    （進迴圈跑一輪 evaluate_once），第二次起回 True（結束迴圈）。用來驅動 run_watch
    走真實 RuleEngine 接線（而非 FakeEngine），驗證 attach_screenshot 規則命中時
    notifier 的呼叫簽章相容。"""

    def __init__(self):
        self._checked = False

    def is_set(self):
        if not self._checked:
            self._checked = True
            return False
        return True

    def set(self):
        self._checked = True

    def wait(self, timeout=None):
        return False


def _attach_screenshot_rule():
    return rule_from_dict({
        "name": "附圖規則", "target_window": {"title_pattern": "記事本"},
        "condition": {"type": "text", "pattern": "斷線"},
        "triggers": [{"type": "notify", "message": "斷線了"}],
        "attach_screenshot": True, "enabled": True})


def test_run_watch_attach_screenshot_rule_notifies_without_crashing(tmp_path):
    """M3 最終審查：真實 RuleEngine 命中 attach_screenshot 規則時以
    notifier(message, image_png=...)（雙參數）呼叫。run_watch 若仍接單參數的
    echo=print，per-rule isolation 會吞掉 TypeError，通知被靜默丟棄（記成
    「觸發失敗，已跳過」）。此測驗證訊息確實被 echo 到，證明 run_watch 已改用
    相容 image_png 參數的 notifier。"""
    window = WindowInfo(handle=object(), title="記事本", app_name="Notepad",
                        x=0, y=0, width=200, height=100, is_active=False)
    platform = Platform(
        input_backend=FakeInputBackend(),
        window_manager=FakeWindowManager([window]),
        screen_capture=FakeScreenCapture(image=np.zeros((4, 4, 3), dtype=np.uint8)),
        ocr_engine=FakeOcrEngine([TextBox(text="斷線", x=0, y=0, width=10, height=10,
                                          confidence=0.9)]))
    echoes = []
    stop_event = OneShotStopEvent()

    code = run_watch(platform, RuleStorage(tmp_path), object(), templates=None,
                     echo=echoes.append, rules=[_attach_screenshot_rule()],
                     stop_event=stop_event)

    assert code == 0
    assert any("斷線了" in line for line in echoes)


def test_watch_parser_dir():
    args = build_parser().parse_args(["watch", "--dir", "/tmp/s"])
    assert args.command == "watch" and args.dir == "/tmp/s"


def test_run_watch_runs_engine_with_enabled_rules(tmp_path):
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("開", enabled=True))
    storage.save(make_rule("關", enabled=False))
    ran = {}

    class FakeEngine:
        def __init__(self, platform, storage=None, templates=None, notifier=None,
                     player_factory=None, stop_event=None):
            ran["init"] = True
            ran["player_factory"] = player_factory
            ran["stop_event"] = stop_event

        def run(self, rules):
            ran["names"] = [r.name for r in rules]

    code = run_watch(object(), storage, object(), templates=None,
                     echo=lambda *_: None, engine_factory=FakeEngine)
    assert code == 0
    assert ran["names"] == ["開"]
    assert ran["player_factory"] is not None
    assert ran["stop_event"] is not None


def test_run_watch_no_enabled_rules_message(tmp_path):
    storage = RuleStorage(tmp_path)
    echoes = []
    code = run_watch(object(), storage, object(), templates=None,
                     echo=echoes.append, engine_factory=None)
    assert code == 0
    assert any("沒有啟用" in line for line in echoes)


def test_run_watch_threads_shared_stop_event_into_player_factory(tmp_path):
    """驗證真實接線路徑：player_factory 閉包穿透的 stop_event 與 engine 收到的相同。"""
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("開", enabled=True))
    recorded = {}

    class FakeEngine:
        def __init__(self, platform, storage=None, templates=None, notifier=None,
                     player_factory=None, stop_event=None):
            recorded["player_factory"] = player_factory
            recorded["stop_event"] = stop_event

        def run(self, rules):
            pass

    code = run_watch(object(), storage, object(), templates=None,
                     echo=lambda *_: None, engine_factory=FakeEngine)
    assert code == 0
    assert recorded["player_factory"] is not None
    assert recorded["stop_event"] is not None

    # 呼叫閉包產生 Player（比照 RuleEngine._fire 呼叫方式），
    # 其 stop_event 必須與 engine 收到的是同一物件，證明真的共用而非各自獨立。
    player = recorded["player_factory"](object(), storage=object(), templates=None)
    assert player.stop_event is recorded["stop_event"]


def test_main_watch_dispatches(tmp_path):
    seen = {}

    def spy_run_watch(platform, rule_storage, script_storage, templates, **k):
        seen["ok"] = True
        return 0

    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                run_watch_fn=spy_run_watch,
                hook_factory=lambda: FakeInputHook())
    assert code == 0 and seen == {"ok": True}


def test_main_watch_permission_denied(tmp_path):
    called = []
    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                run_watch_fn=lambda *a, **k: called.append(1) or 0)
    assert code == 1 and called == []


# -- I2（M3 最終審查）：watch 迴圈的 best-effort SessionGuard --

def test_main_watch_guard_start_failure_does_not_abort_watch(tmp_path, capsys):
    """緊急停止熱鍵啟動失敗（如缺輸入監控權限）不得阻斷監看：run_watch_fn 仍須被呼叫，
    且必須印出繁中警告，仍可用 Ctrl+C（或規則的 stop_all）停止。"""
    class RaisingHook:
        def start(self, on_event):
            raise RuntimeError("無輸入監控權限")

        def stop(self):
            pass

    seen = {}

    def spy_run_watch(platform, rule_storage, script_storage, templates, **k):
        seen["ok"] = True
        seen["stop_event"] = k.get("stop_event")
        return 0

    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                run_watch_fn=spy_run_watch,
                hook_factory=lambda: RaisingHook())
    assert code == 0 and seen["ok"] is True
    assert seen["stop_event"] is not None
    assert "緊急停止熱鍵無法啟用" in capsys.readouterr().err


def test_main_watch_guard_starts_and_stops_around_run_watch(tmp_path):
    """守護啟動成功時：guard.start() 與 guard.stop() 皆須被呼叫（透過真實 hook_factory
    注入 FakeInputHook 觀察 started/stopped 計數）。"""
    hook = FakeInputHook()

    def spy_run_watch(platform, rule_storage, script_storage, templates, **k):
        assert hook.started == 1   # run_watch_fn 執行時，守護應已啟動
        return 0

    code = main(["watch", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                run_watch_fn=spy_run_watch,
                hook_factory=lambda: hook)
    assert code == 0
    assert hook.stopped == 1
