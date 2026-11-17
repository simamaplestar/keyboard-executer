import threading

import numpy as np

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import TAP_HOLD_MS, Player
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window(x=0, y=0, w=200, h=100):
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=x, y=y, width=w, height=h, is_active=False)


def box(text, x=0, y=0, w=10, h=10):
    return TextBox(text=text, x=x, y=y, width=w, height=h, confidence=0.9)


def make_platform(capture=None, ocr=None, windows=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    platform = Platform(input_backend=backend, window_manager=manager,
                        screen_capture=capture, ocr_engine=ocr)
    return platform, backend, manager


def make_script(actions):
    return script_from_dict({"name": "測試",
                             "target_window": {"title_pattern": "記事本"},
                             "actions": actions})


def test_wait_text_matches_immediately_then_continues():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("已完成")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([
        {"type": "wait_text", "pattern": "完成"},
        {"type": "key_press", "key": "a"},
    ])
    result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_wait_text_polls_until_match():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[[box("讀取中")], [box("讀取中")], [box("完成")]])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    sleeps = []
    script = make_script([{"type": "wait_text", "pattern": "完成", "timeout_ms": 100000}])
    result = Player(platform, sleep=sleeps.append).play(script)
    assert result.ok
    assert len(ocr.calls) == 3       # 前兩輪不中、第三輪命中
    assert len(sleeps) == 2          # 兩次輪詢間隔


def test_wait_text_timeout_abort():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    # 注入固定時鐘：第一次檢查 deadline 未到、第二次已過
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([{"type": "wait_text", "pattern": "沒有", "timeout_ms": 500}])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok is False
    assert "逾時" in result.error


def test_wait_text_timeout_continue_runs_next():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([
        {"type": "wait_text", "pattern": "沒有", "timeout_ms": 500, "on_timeout": "continue"},
        {"type": "key_press", "key": "a"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_wait_text_timeout_goto_jumps():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([
        {"type": "wait_text", "pattern": "沒有", "timeout_ms": 500,
         "on_timeout": "goto", "goto_index": 2},
        {"type": "key_press", "key": "z"},   # 被 goto 跳過
        {"type": "key_press", "key": "b"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "b", TAP_HOLD_MS)]


def test_goto_can_jump_backward():
    cap = FakeScreenCapture(scale=1.0)
    # 第一輪不中→goto 回 index 0 再等一次→第二輪命中
    ocr = FakeOcrEngine(boxes=[[box("其他")], [box("完成")]])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 999.0, 0.0, 0.0])
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "timeout_ms": 1,
         "on_timeout": "goto", "goto_index": 0},
        {"type": "key_press", "key": "d"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "d", TAP_HOLD_MS)]


def test_wait_text_stop_event_interrupts_poll():
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("其他")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    stop = threading.Event()

    def sleeper(_s):
        stop.set()  # 第一次輪詢等待即設停止

    script = make_script([{"type": "wait_text", "pattern": "沒有", "timeout_ms": 100000}])
    result = Player(platform, stop_event=stop, sleep=sleeper).play(script)
    assert result.ok is False
    assert "手動停止" in result.error


def test_wait_image_matches_via_template_loader():
    # 模板須具備內部特徵（非單一均勻色塊），否則 match_template 的零變異
    # 保護（見 vision.py／test_vision_template.py 慣例）永遠回傳 found=False。
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 2] = 255  # 紅色背景（BGR）
    tpl[3:7, 4:8] = (0, 255, 0)  # 內含綠色方塊，具備可比對特徵
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[40:50, 80:92] = tpl
    cap = FakeScreenCapture(image=scene, scale=1.0)
    platform, backend, _ = make_platform(capture=cap)
    script = make_script([
        {"type": "wait_image", "template": "綠塊"},
        {"type": "key_press", "key": "a"},
    ])
    result = Player(platform, sleep=lambda s: None,
                    templates=lambda name: tpl).play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_wait_text_captures_region_in_physical_pixels_with_scale():
    from keyboard_executor.core.geometry import Rect

    cap = FakeScreenCapture(scale=2.0)
    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, _, _ = make_platform(capture=cap,
                                   ocr=ocr, windows=[make_window(x=10, y=20)])
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "region": [5, 6, 30, 40]},
    ])
    Player(platform, sleep=lambda s: None).play(script)
    # (win.x+rx)*scale=(10+5)*2=30, (20+6)*2=52, 30*2=60, 40*2=80
    assert cap.captures == [Rect(30, 52, 60, 80)]


def test_nested_goto_inside_if_branch_stays_within_branch():
    """Minor #6 回歸測試：_Goto 契約——if_* then 分支內的 wait_* on_timeout=goto
    只在該分支自己的動作清單內跳轉，不得逸出到外層清單；外層動作仍照自己的
    index 前進、正常執行。"""
    cap = FakeScreenCapture(scale=1.0)
    # OCR 永遠回傳同一段文字：外層 if_text 的 pattern 命中觸發 then 分支，
    # 但 then 分支內 wait_text 要找的 pattern 不在其中，因而逾時。
    ocr = FakeOcrEngine(boxes=[box("觸發if")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])   # wait_text 逾時判斷用的固定時鐘
    script = make_script([
        {"type": "if_text", "pattern": "觸發if",
         "then": [
             {"type": "wait_text", "pattern": "沒有", "timeout_ms": 500,
              "on_timeout": "goto", "goto_index": 2},
             {"type": "key_press", "key": "z"},   # 被 goto 跳過
             {"type": "key_press", "key": "c"},   # goto_index=2 跳到這裡（分支內）
         ]},
        {"type": "key_press", "key": "o"},        # 外層自己的下一個動作
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    # goto 只在分支內生效（跑到 c），沒有逸出到外層清單去跳過或重跑 o
    assert backend.calls == [("key_press", "c", TAP_HOLD_MS), ("key_press", "o", TAP_HOLD_MS)]


def test_vision_action_without_screen_capture_aborts():
    platform, _, _ = make_platform(capture=None, ocr=FakeOcrEngine(boxes=[]))
    script = make_script([{"type": "wait_text", "pattern": "x"}])
    result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok is False
    assert "螢幕擷取" in result.error


class FlakyCapture(FakeScreenCapture):
    """第一次 capture 拋例外（模擬 mss 暫時性失敗），之後正常。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attempts = 0

    def capture(self, region):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("擷取暫時失敗")
        return super().capture(region)


def test_wait_poll_transient_exception_skips_round_then_matches():
    cap = FlakyCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, backend, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "timeout_ms": 100000},
        {"type": "key_press", "key": "a"},
    ])
    result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok
    assert cap.attempts == 2          # 第一輪失敗被跳過、第二輪命中
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_wait_poll_persistent_exception_times_out_honoring_on_timeout():
    class AlwaysBoomCapture(FakeScreenCapture):
        def capture(self, region):
            raise RuntimeError("擷取一直失敗")

    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, backend, _ = make_platform(capture=AlwaysBoomCapture(scale=1.0), ocr=ocr)
    clock = iter([0.0, 0.0, 999.0])
    script = make_script([
        {"type": "wait_text", "pattern": "完成", "timeout_ms": 500,
         "on_timeout": "continue"},
        {"type": "key_press", "key": "a"},
    ])
    player = Player(platform, sleep=lambda s: None)
    player._clock = lambda: next(clock)
    result = player.play(script)
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_wait_poll_exception_logged_in_traditional_chinese(caplog):
    import logging

    cap = FlakyCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([{"type": "wait_text", "pattern": "完成", "timeout_ms": 100000}])
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok
    assert "已跳過" in caplog.text and "擷取暫時失敗" in caplog.text
