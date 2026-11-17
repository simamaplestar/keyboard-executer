import numpy as np

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import TAP_HOLD_MS, Player
from keyboard_executor.platforms.base import MouseButton, TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window(x=0, y=0, w=200, h=100):
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=x, y=y, width=w, height=h, is_active=False)


def tbox(text, x=0, y=0, w=10, h=10):
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


def run(actions, capture=None, ocr=None, windows=None, templates=None):
    platform, backend, _ = make_platform(capture=capture, ocr=ocr, windows=windows)
    result = Player(platform, sleep=lambda s: None, templates=templates).play(
        make_script(actions))
    return result, backend


def green_scene_and_template():
    # 12x12 模板，置於 (x=80, y=40) → 中心 (86, 46)：偶數座標，scale=2 除法無捨入歧義。
    # 模板須具備內部特徵（非單一均勻色塊），否則 match_template 的零變異保護
    # （見 vision.py／test_vision_template.py 慣例）永遠回傳 found=False。
    tpl = np.zeros((12, 12, 3), dtype=np.uint8)
    tpl[:, :, 2] = 255  # 紅色背景（BGR）
    tpl[3:9, 3:9] = (0, 255, 0)  # 內含綠色方塊，具備可比對特徵
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[40:52, 80:92] = tpl
    return scene, tpl


def test_if_text_true_runs_then():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("勝利")]))
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_if_text_false_runs_else():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("失敗")]))
    assert result.ok
    assert backend.calls == [("key_press", "b", TAP_HOLD_MS)]


def test_if_text_false_no_else_is_noop():
    result, backend = run(
        [{"type": "if_text", "pattern": "勝利",
          "then": [{"type": "key_press", "key": "a"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("失敗")]))
    assert result.ok
    assert backend.calls == []


def test_if_image_true_runs_then():
    scene, tpl = green_scene_and_template()
    result, backend = run(
        [{"type": "if_image", "template": "綠",
          "then": [{"type": "key_press", "key": "a"}]}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_if_image_false_runs_else():
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 0] = 255  # 場景沒有的藍塊
    result, backend = run(
        [{"type": "if_image", "template": "藍", "threshold": 0.99,
          "then": [{"type": "key_press", "key": "a"}],
          "else": [{"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("key_press", "b", TAP_HOLD_MS)]


def test_click_text_clicks_center():
    # box 位於 region 影像 (x=80,y=40,w=20,h=10) → 中心 (90,45)；scale=1、win 原點 0
    result, backend = run(
        [{"type": "click_text", "pattern": "登入"}],
        capture=FakeScreenCapture(scale=1.0),
        ocr=FakeOcrEngine(boxes=[tbox("登入", x=80, y=40, w=20, h=10)]))
    assert result.ok
    assert backend.calls == [("mouse_click", 90, 45, MouseButton.LEFT, 1)]


def test_click_text_not_found_is_noop():
    result, backend = run(
        [{"type": "click_text", "pattern": "登入"}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("其他")]))
    assert result.ok
    assert backend.calls == []


def test_click_image_clicks_center_with_scale():
    scene, tpl = green_scene_and_template()  # 綠塊中心 px=(86,46) 於 region 影像
    # scale=2、win 原點 (10,20)、region=None：
    #   window-rel 點 = (round(86/2), round(46/2)) = (43, 23)
    #   螢幕絕對點 = (10+43, 20+23) = (53, 43)
    result, backend = run(
        [{"type": "click_image", "template": "綠"}],
        capture=FakeScreenCapture(image=scene, scale=2.0),
        windows=[make_window(x=10, y=20)], templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == [("mouse_click", 53, 43, MouseButton.LEFT, 1)]


def test_click_image_not_found_is_noop():
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :, 0] = 255
    result, backend = run(
        [{"type": "click_image", "template": "藍", "threshold": 0.99}],
        capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert result.ok
    assert backend.calls == []


def test_click_text_region_offset_center_with_scale():
    # region=[5,6,...]（點）、scale=2、win 原點 (10,20)
    # box 中心於 region 影像 px=(40,20)：
    #   window-rel 點 = (5 + round(40/2), 6 + round(20/2)) = (25, 16)
    #   螢幕絕對點 = (10+25, 20+16) = (35, 36)
    result, backend = run(
        [{"type": "click_text", "pattern": "確定", "region": [5, 6, 60, 40]}],
        capture=FakeScreenCapture(scale=2.0),
        windows=[make_window(x=10, y=20)],
        ocr=FakeOcrEngine(boxes=[tbox("確定", x=30, y=10, w=20, h=20)]))
    assert result.ok
    assert backend.calls == [("mouse_click", 35, 36, MouseButton.LEFT, 1)]


def test_if_text_nested_then_runs_through_index_machine():
    result, backend = run(
        [{"type": "if_text", "pattern": "x",
          "then": [{"type": "key_press", "key": "a"},
                   {"type": "key_press", "key": "b"}]}],
        capture=FakeScreenCapture(), ocr=FakeOcrEngine(boxes=[tbox("x")]))
    assert result.ok
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS), ("key_press", "b", TAP_HOLD_MS)]


def test_if_image_mirror_matches_flipped_sprite():
    import cv2
    tpl = np.zeros((10, 12, 3), dtype=np.uint8)
    tpl[:, :6] = (0, 0, 255)
    tpl[:, 6:] = (0, 255, 0)
    tpl[2:5, 8:11] = 255
    scene = np.full((100, 200, 3), 128, dtype=np.uint8)
    scene[40:50, 60:72] = cv2.flip(tpl, 1)
    for mirror, expected in ((False, "b"), (True, "a")):
        result, backend = run(
            [{"type": "if_image", "template": "怪", "threshold": 0.95, "mirror": mirror,
              "then": [{"type": "key_press", "key": "a"}],
              "else": [{"type": "key_press", "key": "b"}]}],
            capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
        assert result.ok, result.error
        assert backend.calls == [("key_press", expected, TAP_HOLD_MS)]


def test_if_image_logs_similarity_for_diagnosis(caplog):
    import logging
    scene, tpl = green_scene_and_template()
    with caplog.at_level(logging.INFO, logger="keyboard_executor.core.player"):
        run([{"type": "if_image", "template": "綠", "then": [{"type": "key_press", "key": "a"}]}],
            capture=FakeScreenCapture(image=scene), templates=lambda n: tpl)
    assert any("若出現圖像「綠」" in r.message and "相似度" in r.message for r in caplog.records)
