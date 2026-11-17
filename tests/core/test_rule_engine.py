import logging
import threading

import numpy as np

from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.core.player import PlayResult
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window():
    return WindowInfo(handle=object(), title="遊戲", app_name="App",
                      x=0, y=0, width=200, height=100, is_active=False)


def tbox(text):
    return TextBox(text=text, x=0, y=0, width=10, height=10, confidence=0.9)


def make_platform(capture=None, ocr=None):
    return Platform(input_backend=FakeInputBackend(),
                    window_manager=FakeWindowManager([make_window()]),
                    screen_capture=capture, ocr_engine=ocr)


def text_rule(name="斷線", trigger=None, interval=5, cooldown=60):
    return rule_from_dict({
        "name": name,
        "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "interval_sec": interval, "cooldown_sec": cooldown,
        "trigger": trigger or {"type": "notify", "message": "斷線了"},
    })


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePlayer:
    instances = []

    def __init__(self, platform, storage=None, templates=None, **k):
        self.played = []
        FakePlayer.instances.append(self)

    def play(self, script):
        self.played.append(script.name)
        return PlayResult(ok=True, actions_run=1)


class DictStorage:
    def __init__(self, scripts=None):
        self._s = scripts or {}

    def load(self, name):
        return self._s[name]


def test_rule_script_rejects_sequence_input_service_missing(caplog):
    from keyboard_executor.core.models import script_from_dict
    from tests.core.test_sequence_input_config import script_data
    platform = make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")]))
    script = script_from_dict(script_data())
    engine = RuleEngine(platform, DictStorage({script.name: script}))
    rule = text_rule(trigger={"type": "run_script", "script_name": script.name})
    with caplog.at_level(logging.WARNING):
        engine.evaluate_once([rule])
    assert "圖片順序輸入" in caplog.text
    assert not platform.input_backend.calls


def test_text_match_fires_notify():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷了")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])
    assert notes == ["斷線了"]


def test_no_match_no_trigger():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("一切正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])
    assert notes == []


def test_missing_target_is_logged_once_until_found_or_status_interval(caplog):
    clock = Clock()
    platform = make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("正常")]))
    platform.window_manager.windows.clear()
    engine = RuleEngine(platform, storage=DictStorage(), clock=clock)
    rule = text_rule(interval=1)
    with caplog.at_level(logging.INFO, logger="keyboard_executor.core.rule_engine"):
        engine.evaluate_once([rule])
        clock.t = 1
        engine.evaluate_once([rule])
    assert len(caplog.records) == 1
    assert "找不到目標視窗" in caplog.text
    assert "斷線" in caplog.text


def test_image_miss_logs_score_and_threshold_without_spamming(caplog):
    rng = np.random.default_rng(7)
    tpl = rng.integers(0, 256, (10, 12, 3), dtype=np.uint8)
    scene = rng.integers(0, 256, (100, 200, 3), dtype=np.uint8)
    notes, clock = [], Clock()
    rule = rule_from_dict({
        "name": "圖片規則", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "提示文字", "threshold": .85},
        "trigger": {"type": "notify", "message": "命中"}, "interval_sec": 1})
    engine = RuleEngine(make_platform(FakeScreenCapture(scene)), storage=DictStorage(),
                        notifier=notes.append, templates=lambda _: tpl, clock=clock)
    with caplog.at_level(logging.INFO, logger="keyboard_executor.core.rule_engine"):
        engine.evaluate_once([rule])
        for clock.t in range(1, 30):
            engine.evaluate_once([rule])
        assert len(caplog.records) == 1
        assert "未命中" in caplog.text
        assert "0.850" in caplog.text
        assert "提示文字" in caplog.text
        clock.t = 30
        engine.evaluate_once([rule])
        assert len(caplog.records) == 2
        scene[10:20, 20:32] = tpl
        clock.t = 31
        engine.evaluate_once([rule])
    assert notes == ["命中"]
    assert any("規則" in r.message and "觸發" in r.message for r in caplog.records)


def test_image_match_fires():
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    tpl[2:6, 3:9] = (0, 0, 255)  # 內含紅色方塊，具辨識特徵（避免均勻模板觸發零變異守門而恆不中）
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[10:20, 20:32] = tpl
    notes = []
    rule = rule_from_dict({
        "name": "圖", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠"},
        "trigger": {"type": "notify", "message": "命中"}})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == ["命中"]


def test_cooldown_blocks_second_trigger():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(cooldown=60, interval=0.001)
    engine.evaluate_once([rule])
    clock.t = 10.0
    engine.evaluate_once([rule])   # 冷卻未過（10 < 60）
    assert notes == ["斷線了"]


def test_cooldown_expires_fires_again():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(cooldown=60, interval=0.001)
    engine.evaluate_once([rule])
    clock.t = 61.0
    engine.evaluate_once([rule])
    assert notes == ["斷線了", "斷線了"]


def test_interval_skips_until_due():
    notes = []
    clock = Clock()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    rule = text_rule(interval=5, cooldown=0)
    # 用 ocr 呼叫次數觀察是否評估：正常→不觸發，但 recognize 會被呼叫
    ocr = engine._platform.ocr_engine
    engine.evaluate_once([rule])       # t=0 首次到期，評估
    engine.evaluate_once([rule])       # t=0 未到下次到期（0 < 5），跳過
    clock.t = 5.0
    engine.evaluate_once([rule])       # t=5 到期，再評估
    assert len(ocr.calls) == 2


def test_disabled_rule_skipped():
    notes = []
    rule = rule_from_dict({
        "name": "停", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "notify", "message": "x"}, "enabled": False})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == []


def test_run_script_trigger_plays_via_player_factory():
    FakePlayer.instances = []
    from keyboard_executor.core.models import script_from_dict
    sub = script_from_dict({"name": "重連", "target_window": {"title_pattern": "遊戲"},
                            "actions": [{"type": "key_press", "key": "a"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage({"重連": sub}),
                        player_factory=FakePlayer, clock=Clock())
    engine.evaluate_once([text_rule(trigger={"type": "run_script", "script_name": "重連"})])
    assert FakePlayer.instances[-1].played == ["重連"]


def test_stop_all_trigger_sets_stop_event():
    stop = threading.Event()
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), stop_event=stop, clock=Clock())
    engine.evaluate_once([text_rule(trigger={"type": "stop_all"})])
    assert stop.is_set()


def test_run_loops_until_stop_event():
    stop = threading.Event()
    clock = Clock()
    calls = []

    def sleeper(_s):
        calls.append(1)
        if len(calls) >= 3:
            stop.set()

    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), stop_event=stop, sleep=sleeper, clock=clock)
    engine.run([text_rule(interval=100)])
    assert stop.is_set()


def test_capture_failure_skips_round_without_crashing():
    notes = []

    class BoomCapture(FakeScreenCapture):
        def capture(self, region):
            raise RuntimeError("截圖失敗")

    engine = RuleEngine(make_platform(BoomCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    engine.evaluate_once([text_rule()])   # 不得拋例外
    assert notes == []


def test_region_captured_in_physical_pixels_with_scale():
    from keyboard_executor.core.geometry import Rect

    cap = FakeScreenCapture(scale=2.0)
    engine = RuleEngine(make_platform(cap, FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), clock=Clock())
    rule = rule_from_dict({
        "name": "區", "target_window": {"title_pattern": "遊戲"},
        "region": [5, 6, 30, 40],
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "notify", "message": "y"}})
    engine.evaluate_once([rule])
    assert cap.captures == [Rect(10, 12, 60, 80)]  # (5*2,6*2,30*2,40*2)，win 原點 0


# -- 韌性補強（M2b/M3 審查折入）：per-rule 失敗隔離 + 失敗記錄不可靜默 --

def test_capture_failure_logged_in_traditional_chinese(caplog):
    """擷取例外必須「記錄」（spec §10），不能只是吞掉；訊息含規則名稱，繁中。
    M5 起經 logging（GUI 日誌面板與滾動日誌檔皆可見），不再 print 到 stderr。"""
    class BoomCapture(FakeScreenCapture):
        def capture(self, region):
            raise RuntimeError("截圖失敗")

    engine = RuleEngine(make_platform(BoomCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([text_rule(name="斷線監控")])
    assert "斷線監控" in caplog.text
    assert "跳過" in caplog.text


def test_multi_rule_round_isolated_from_single_rule_failure():
    """同一輪內某規則擷取例外，不得阻擋同一輪其他規則的評估與觸發（per-rule isolation）。"""
    notes = []

    class FlakyCapture(FakeScreenCapture):
        def __init__(self):
            super().__init__()
            self._calls = 0

        def capture(self, region):
            self._calls += 1
            if self._calls == 1:
                raise RuntimeError("擷取失敗")
            return super().capture(region)

    engine = RuleEngine(make_platform(FlakyCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    broken_rule = text_rule(name="故障規則", trigger={"type": "notify", "message": "不該出現"})
    healthy_rule = text_rule(name="正常規則", trigger={"type": "notify", "message": "正常觸發"})
    engine.evaluate_once([broken_rule, healthy_rule])
    assert notes == ["正常觸發"]


# -- I1（M3 最終審查）：_fire 失敗隔離 + PlayResult 不可靜默丟棄 --

def test_fire_missing_script_isolated_and_logged_without_crashing(caplog):
    """觸發 run_script 時腳本不存在（storage.load 拋例外）：_fire 的例外必須被隔離
    （與 _matches 一樣），watch 不可因此崩潰；同一輪其他規則仍須評估與觸發。"""
    notes = []
    broken = text_rule(name="缺腳本規則",
                       trigger={"type": "run_script", "script_name": "不存在的腳本"})
    healthy = text_rule(name="正常規則", trigger={"type": "notify", "message": "正常觸發"})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append,
                        player_factory=FakePlayer, clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([broken, healthy])   # 不得拋例外
    assert "缺腳本規則" in caplog.text
    assert "跳過" in caplog.text
    assert notes == ["正常觸發"]


def test_fire_run_script_failure_result_is_logged_not_discarded(caplog):
    """run_script 觸發的 Player 回傳 ok=False：PlayResult 過去被完全丟棄，
    現在必須記錄規則名稱、腳本名稱與 result.error，不可悄悄無痕跡。"""
    from keyboard_executor.core.models import script_from_dict

    class FailingPlayer:
        def __init__(self, platform, storage=None, templates=None, **k):
            pass

        def play(self, script):
            return PlayResult(ok=False, actions_run=1, error="目標視窗已關閉")

    sub = script_from_dict({"name": "重連", "target_window": {"title_pattern": "遊戲"},
                            "actions": [{"type": "key_press", "key": "a"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage({"重連": sub}),
                        player_factory=FailingPlayer, clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([text_rule(trigger={"type": "run_script",
                                                 "script_name": "重連"})])
    assert "重連" in caplog.text
    assert "目標視窗已關閉" in caplog.text


def test_fire_run_script_failure_also_reaches_on_error_callback():
    """M4 最終審查：run_script 觸發失敗過去只印到 stderr，GUI 看不到。現在必須
    也經 on_error 回呼送出，讓 WatchController 轉成 progress(kind=error) 進
    GUI 日誌（spec §10 不可靜默）。"""
    from keyboard_executor.core.models import script_from_dict

    class FailingPlayer:
        def __init__(self, platform, storage=None, templates=None, **k):
            pass

        def play(self, script):
            return PlayResult(ok=False, actions_run=1, error="目標視窗已關閉")

    sub = script_from_dict({"name": "重連", "target_window": {"title_pattern": "遊戲"},
                            "actions": [{"type": "key_press", "key": "a"}]})
    errors = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage({"重連": sub}),
                        player_factory=FailingPlayer, clock=Clock(),
                        on_error=lambda name, message: errors.append((name, message)))
    engine.evaluate_once([text_rule(trigger={"type": "run_script", "script_name": "重連"})])
    assert errors
    name, message = errors[-1]
    assert name == "斷線"
    assert "重連" in message
    assert "目標視窗已關閉" in message


# -- M4 前置（M3 審查 M6(b)）：on_fire 觸發回呼 --

def test_on_fire_called_with_rule_name_and_trigger_type():
    fired = []
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock(),
                        on_fire=lambda name, ttype: fired.append((name, ttype)))
    engine.evaluate_once([text_rule(name="斷線監控")])
    assert fired == [("斷線監控", "notify")]
    assert notes == ["斷線了"]


def test_on_fire_exception_isolated_like_fire_failures(caplog):
    notes = []

    def boom(name, ttype):
        raise RuntimeError("GUI 回呼壞掉")

    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock(),
                        on_fire=boom)
    first = text_rule(name="規則甲", trigger={"type": "notify", "message": "甲"})
    second = text_rule(name="規則乙", trigger={"type": "notify", "message": "乙"})
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([first, second])   # 不得拋例外（on_fire 例外由 _fire 隔離吸收）
    assert "規則甲" in caplog.text and "規則乙" in caplog.text and "跳過" in caplog.text
    assert notes == []   # on_fire 於觸發前失敗，兩條規則的 notify 都未執行、皆被記錄


# -- Task 8（spec §10）：on_error 回呼與連續失敗 3 次通知 --

class _BoomCapture(FakeScreenCapture):
    def capture(self, region):
        raise RuntimeError("截圖失敗")


def test_on_error_callback_receives_rule_name_and_message():
    errors = []
    engine = RuleEngine(make_platform(_BoomCapture(), FakeOcrEngine([tbox("x")])),
                        storage=DictStorage(), clock=Clock(),
                        on_error=lambda name, message: errors.append((name, message)))
    engine.evaluate_once([text_rule(name="監控")])
    assert errors and errors[0][0] == "監控" and "截圖失敗" in errors[0][1]


def test_consecutive_failures_notify_once_at_threshold():
    notes = []
    clock = Clock()
    rule = text_rule(name="監控", interval=1)
    engine = RuleEngine(make_platform(_BoomCapture(), FakeOcrEngine([tbox("x")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):       # 連續 5 輪失敗
        clock.t = t
        engine.evaluate_once([rule])
    # 恰於第 3 次通知一次，之後不重複轟炸
    assert notes == ["規則「監控」已連續 3 次擷取或比對失敗，請檢查權限與目標視窗"]


def test_failure_streak_resets_after_successful_round():
    notes = []
    clock = Clock()

    class FlakyCapture(FakeScreenCapture):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def capture(self, region):
            self.calls += 1
            if self.calls != 3:
                raise RuntimeError("失敗")
            return super().capture(region)

    rule = text_rule(name="監控", interval=1, cooldown=0)
    engine = RuleEngine(make_platform(FlakyCapture(), FakeOcrEngine([tbox("正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=clock)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):   # 失敗、失敗、成功(歸零)、失敗、失敗
        clock.t = t
        engine.evaluate_once([rule])
    assert notes == []                     # 從未達「連續」3 次


# -- Task 4：color 條件（出現/消失） --

def _color_rule(absent=False, min_pixels=3):
    return rule_from_dict({
        "name": "紅點", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "color", "hue": 0, "sat": 255, "val": 255,
                      "min_pixels": min_pixels, "absent": absent},
        "trigger": {"type": "notify", "message": "有紅點"},
    })


def _red_image():
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)      # BGR 紅
    return img


def test_color_condition_matches_when_red_present():
    from tests.fakes import FakeScreenCapture
    engine = RuleEngine(make_platform(capture=FakeScreenCapture(image=_red_image())),
                        storage=None)
    assert engine._matches(_color_rule())[0] is True


def test_color_condition_absent_mode_matches_when_no_red():
    from tests.fakes import FakeScreenCapture
    grey = np.full((20, 20, 3), 128, dtype=np.uint8)
    engine = RuleEngine(make_platform(capture=FakeScreenCapture(image=grey)),
                        storage=None)
    assert engine._matches(_color_rule(absent=True))[0] is True
    # 出現模式在同一灰圖應為 False
    assert engine._matches(_color_rule(absent=False))[0] is False


def test_color_condition_boundary_at_min_pixels():
    from tests.fakes import FakeScreenCapture
    img = np.full((10, 10, 3), 128, dtype=np.uint8)   # 灰底
    img[0, 0:3] = (0, 0, 255)                          # 剛好 3 顆紅（BGR）
    engine = RuleEngine(make_platform(capture=FakeScreenCapture(image=img)),
                        storage=None)
    # count(3) == min_pixels(3)：出現模式命中（>=）、消失模式不命中（<）
    assert engine._matches(_color_rule(min_pixels=3, absent=False))[0] is True
    assert engine._matches(_color_rule(min_pixels=3, absent=True))[0] is False
    # count(3) < min_pixels(4)：出現不命中、消失命中
    assert engine._matches(_color_rule(min_pixels=4, absent=False))[0] is False
    assert engine._matches(_color_rule(min_pixels=4, absent=True))[0] is True


def test_stop_all_trigger_also_invokes_on_stop_all_callback():
    # stop_all 除了停監看（stop_event），還要回呼 on_stop_all 以停掉其他自動化
    # （例如用「執行」按鈕獨立跑的腳本，其 stop_event 與監看不同一個）。
    stop = threading.Event()
    called = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), stop_event=stop, clock=Clock(),
                        on_stop_all=lambda: called.append(True))
    engine.evaluate_once([text_rule(trigger={"type": "stop_all"})])
    assert stop.is_set()          # 仍停監看
    assert called == [True]       # 也停掉執行中的腳本


def test_multi_trigger_fires_notify_and_stop_all():
    stop = threading.Event()
    notified = []
    called = []
    engine = RuleEngine(
        make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), stop_event=stop, clock=Clock(),
        notifier=notified.append, on_stop_all=lambda: called.append(True))
    rule = rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "有事"}, {"type": "stop_all"}]})
    engine.evaluate_once([rule])
    assert notified == ["有事"]        # 通知動作有跑
    assert stop.is_set()               # 停止動作有跑
    assert called == [True]            # 連執行中腳本一併停（on_stop_all）


def test_multi_trigger_isolates_action_failure_still_runs_stop_all():
    # 每個動作各自隔離：前面的動作（notify）拋例外，也不可讓後面的安全動作
    # （stop_all）漏做，並將失敗動作記錄到 on_error。
    stop = threading.Event()
    called = []
    errors = []

    def boom_notifier(msg):
        raise RuntimeError("通知壞了")

    engine = RuleEngine(
        make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), stop_event=stop, clock=Clock(),
        notifier=boom_notifier, on_stop_all=lambda: called.append(True),
        on_error=lambda name, message: errors.append((name, message)))
    rule = rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "有事"}, {"type": "stop_all"}]})
    engine.evaluate_once([rule])
    assert stop.is_set()               # notify 失敗後 stop_all 仍執行
    assert called == [True]            # on_stop_all 也仍被呼叫
    assert errors                      # 失敗的 notify 動作有記錄（on_error）


def test_slow_check_schedules_next_poll_from_completion_not_start():
    # 效能根因回歸：一次 OCR 比 interval 還久時，下一輪輪詢時間須以「本輪比對完成後」
    # 起算，否則規則會立刻過期、OCR 背靠背連跑吃滿 CPU（使用者實測系統卡頓）。
    clock = Clock()
    calls = []

    class SlowCountingOcr:
        def recognize(self, image):
            calls.append(1)
            clock.t += 3.0            # 模擬一次 3 秒的 OCR
            return [tbox("連線中斷")]

    engine = RuleEngine(make_platform(FakeScreenCapture(), SlowCountingOcr()),
                        storage=DictStorage(), notifier=[].append, clock=clock)
    rule = text_rule(interval=1.0)    # interval 1s 遠小於 3s 的 OCR
    engine.evaluate_once([rule])      # 到期 → 跑 OCR（clock 0→3），下次到期應為 3+1=4
    engine.evaluate_once([rule])      # clock=3 < 4 → 未到期，OCR 不可再跑
    assert calls == [1]               # OCR 只跑一次，沒有背靠背再跑


# -- Task 3：notify 動作附截圖 --

def _screenshot_rule(attach):
    return rule_from_dict({
        "name": "截圖規則", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "斷線"}],
        "attach_screenshot": attach})


def test_attach_screenshot_passes_png_to_notifier():
    received = []

    def notifier(message, *, image_png=None):
        received.append((message, image_png))

    engine = RuleEngine(
        make_platform(FakeScreenCapture(image=np.zeros((4, 4, 3), np.uint8)),
                      FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=notifier, clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=True)])
    assert len(received) == 1
    msg, png = received[0]
    assert msg == "斷線"
    assert png is not None and bytes(png[:8]) == b"\x89PNG\r\n\x1a\n"


def test_no_attach_calls_notifier_single_arg():
    calls = []
    # 單參數 notifier：若引擎傳了 image_png 會 TypeError，此測即證明走單參數路徑。
    engine = RuleEngine(
        make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=lambda message: calls.append(message),
        clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=False)])
    assert calls == ["斷線"]


def test_encode_failure_falls_back_to_text_notify(monkeypatch):
    import keyboard_executor.core.rule_engine as re_mod
    received = []

    def boom(_img):
        raise RuntimeError("encode 壞了")

    def notifier(message, *, image_png=None):
        received.append((message, image_png))

    monkeypatch.setattr(re_mod, "encode_png", boom)
    engine = RuleEngine(
        make_platform(FakeScreenCapture(image=np.zeros((4, 4, 3), np.uint8)),
                      FakeOcrEngine([tbox("連線中斷")])),
        storage=DictStorage(), notifier=notifier, clock=Clock())
    engine.evaluate_once([_screenshot_rule(attach=True)])   # 不崩潰
    assert received == [("斷線", None)]                     # 退回純文字（無 image_png）


def test_text_absent_fires_when_text_missing():
    # 消失時（absent=True）：畫面找不到符合文字才觸發
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("一切正常")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    rule = rule_from_dict({
        "name": "文字消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷", "absent": True},
        "triggers": [{"type": "notify", "message": "沒斷線"}]})
    engine.evaluate_once([rule])
    assert notes == ["沒斷線"]


def test_text_absent_does_not_fire_when_text_present():
    notes = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock())
    rule = rule_from_dict({
        "name": "文字消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷", "absent": True},
        "triggers": [{"type": "notify", "message": "沒斷線"}]})
    engine.evaluate_once([rule])
    assert notes == []


def _img_scene(with_template):
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 1] = 255
    tpl[2:6, 3:9] = (0, 0, 255)     # 內含紅色方塊，具辨識特徵
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    if with_template:
        scene[10:20, 20:32] = tpl   # 命中
    return tpl, scene


def test_image_absent_fires_when_template_missing():
    # 消失時（absent=True）：模板未命中才觸發
    tpl, scene = _img_scene(with_template=False)
    notes = []
    rule = rule_from_dict({
        "name": "圖消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠", "absent": True},
        "triggers": [{"type": "notify", "message": "圖不見了"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == ["圖不見了"]


def test_image_absent_does_not_fire_when_template_present():
    tpl, scene = _img_scene(with_template=True)
    notes = []
    rule = rule_from_dict({
        "name": "圖消失", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "image", "template": "綠", "absent": True},
        "triggers": [{"type": "notify", "message": "圖不見了"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(image=scene), None),
                        storage=DictStorage(), notifier=notes.append,
                        templates=lambda n: tpl, clock=Clock())
    engine.evaluate_once([rule])
    assert notes == []


def test_on_fire_done_called_after_triggers_finish():
    """AI 示範試跑要等規則觸發的動作做完才繼續：動作全部做完後回報 fire_done。"""
    order = []
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=lambda m: order.append("notify"),
                        clock=Clock(),
                        on_fire=lambda name, ttype: order.append("fire"),
                        on_fire_done=lambda name: order.append(("done", name)))
    engine.evaluate_once([text_rule(name="斷線監控")])
    assert order == ["fire", "notify", ("done", "斷線監控")]


def test_on_fire_done_called_even_when_trigger_fails():
    done = []

    def bad_notify(message):
        raise RuntimeError("壞掉")

    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=bad_notify, clock=Clock(),
                        on_fire_done=done.append)
    engine.evaluate_once([text_rule(name="斷線監控")])
    assert done == ["斷線監控"]
