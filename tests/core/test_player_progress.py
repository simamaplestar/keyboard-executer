"""Player on_step 進度回呼（M3 審查 M6(a)：GUI 日誌面板的掛點）。"""
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_window():
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=0, y=0, width=200, height=100, is_active=False)


def make_platform(capture=None, ocr=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager([make_window()])
    return Platform(input_backend=backend, window_manager=manager,
                    screen_capture=capture, ocr_engine=ocr), backend


def make_script(actions):
    return script_from_dict({"name": "測試", "target_window": {"title_pattern": "記事本"},
                             "actions": actions})


def test_on_step_receives_ordered_records():
    records = []
    platform, _ = make_platform()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "delay", "ms": 0},
        {"type": "key_press", "key": "b"},
    ])
    result = Player(platform, sleep=lambda s: None, on_step=records.append).play(script)
    assert result.ok
    assert [(r["index"], r["total"], r["type"]) for r in records] == [
        (0, 3, "key_press"), (1, 3, "delay"), (2, 3, "key_press")]
    assert all(r["kind"] == "step" for r in records)
    assert records[0]["label"] == "按鍵 a"
    assert records[1]["label"] == "延遲 0ms"


def test_on_step_branch_local_index_and_total():
    records = []
    platform, _ = make_platform()
    script = make_script([
        {"type": "loop", "count": 2, "actions": [
            {"type": "key_press", "key": "x"},
            {"type": "key_press", "key": "y"},
        ]},
    ])
    result = Player(platform, sleep=lambda s: None, on_step=records.append).play(script)
    assert result.ok
    # 外層 loop 一筆＋每輪兩筆 ×2；index/total 為該層動作清單的（GUI 顯示 [n/N]）
    assert [(r["index"], r["total"], r["type"]) for r in records] == [
        (0, 1, "loop"),
        (0, 2, "key_press"), (1, 2, "key_press"),
        (0, 2, "key_press"), (1, 2, "key_press")]


def test_on_step_reported_before_wait_polling():
    records = []
    cap = FakeScreenCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[TextBox(text="完成", x=0, y=0, width=10, height=10,
                                       confidence=0.9)])
    platform, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([{"type": "wait_text", "pattern": "完成"}])
    result = Player(platform, sleep=lambda s: None, on_step=records.append).play(script)
    assert result.ok
    steps = [r for r in records if r["kind"] == "step"]
    assert [r["type"] for r in steps] == ["wait_text"]
    assert steps[0]["label"] == "等待文字「完成」"
    assert records[0]["kind"] == "step"   # step 事件先於等待結果


def test_on_step_exception_aborts_as_unexpected_error():
    def boom(record):
        raise RuntimeError("GUI 回呼壞掉")

    platform, backend = make_platform()
    script = make_script([{"type": "key_press", "key": "a"}])
    result = Player(platform, sleep=lambda s: None, on_step=boom).play(script)
    assert result.ok is False
    assert "未預期錯誤" in result.error
    assert backend.calls == []   # 回呼於動作執行前，動作未送出
