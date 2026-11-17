"""Player 回報等待與分支結果（AI 示範錄製的試跑紀錄需要）。"""
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import TextBox, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeScreenCapture, FakeWindowManager


def make_platform(boxes):
    window = WindowInfo(handle=object(), title="記事本", app_name="App",
                        x=0, y=0, width=200, height=100, is_active=False)
    return Platform(input_backend=FakeInputBackend(),
                    window_manager=FakeWindowManager([window]),
                    screen_capture=FakeScreenCapture(scale=1.0),
                    ocr_engine=FakeOcrEngine(boxes=boxes))


def make_script(actions):
    return script_from_dict({"name": "測試", "target_window": {"title_pattern": "記事本"},
                             "actions": actions})


def run(actions, boxes):
    records = []
    result = Player(make_platform(boxes), sleep=lambda s: None,
                    on_step=records.append).play(make_script(actions))
    return result, records


def of_kind(records, kind):
    return [r for r in records if r["kind"] == kind]


def box(text):
    return TextBox(text=text, x=0, y=0, width=10, height=10, confidence=0.9)


def test_wait_timeout_emits_wait_result():
    result, records = run([
        {"type": "key_press", "key": "a"},
        {"type": "wait_text", "pattern": "X", "timeout_ms": 0, "on_timeout": "continue"},
    ], boxes=[])
    assert result.ok
    [event] = of_kind(records, "wait_result")
    assert event["index"] == 1
    assert event["type"] == "wait_text"
    assert event["matched"] is False
    assert event["on_timeout"] == "continue"
    assert isinstance(event["elapsed_ms"], int)


def test_wait_hit_emits_matched_true():
    _, records = run([{"type": "wait_text", "pattern": "完成"}], boxes=[box("完成")])
    [event] = of_kind(records, "wait_result")
    assert event["matched"] is True
    assert event["on_timeout"] is None


def test_if_text_emits_branch_else():
    _, records = run([{"type": "if_text", "pattern": "X",
                       "then": [{"type": "key_press", "key": "a"}],
                       "else": [{"type": "key_press", "key": "b"}]}], boxes=[])
    [event] = of_kind(records, "branch")
    assert event == {"kind": "branch", "index": 0, "type": "if_text", "taken": "else"}


def test_if_text_emits_branch_then():
    _, records = run([{"type": "key_press", "key": "z"},
                      {"type": "if_text", "pattern": "完成",
                       "then": [{"type": "key_press", "key": "a"}]}], boxes=[box("完成")])
    [event] = of_kind(records, "branch")
    assert event["index"] == 1
    assert event["taken"] == "then"


def test_existing_step_events_unchanged():
    _, records = run([{"type": "wait_text", "pattern": "完成"}], boxes=[box("完成")])
    for event in of_kind(records, "step"):
        assert set(event) == {"kind", "index", "total", "type", "label"}
