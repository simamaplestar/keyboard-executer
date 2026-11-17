import re

import pytest

from keyboard_executor.app.recorder_session import RecorderSession, script_from_recording
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ActionType, ScriptValidationError
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton, WindowInfo
from tests.fakes import FakeInputHook


def key(name, ts=0, kind=EventKind.KEY_DOWN):
    return InputEvent(kind=kind, timestamp_ms=ts, key=name)


def mouse_down(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_DOWN, timestamp_ms=ts, x=x, y=y,
                      button=MouseButton.LEFT)


def mouse_up(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_UP, timestamp_ms=ts, x=x, y=y,
                      button=MouseButton.LEFT)


def make_window(title="記事本", app="App"):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=0, y=0, width=10, height=10, is_active=False)


def test_toggle_via_f9_records_between_toggles_and_builds_script():
    hook = FakeInputHook()
    states = []
    session = RecorderSession(hook, Point(0, 0), on_state=states.append)
    session.start()
    hook.push(key("f9"))            # 開始錄製
    hook.push(key("a", ts=10))
    hook.push(key("f9", ts=20))     # 停止
    actions = session.finish()
    assert [a.type for a in actions] == [ActionType.KEY_PRESS]
    assert actions[0].params["key"] == "a"
    assert states == ["recording", "done"]
    assert hook.stopped == 1
    script = script_from_recording("錄一", make_window("記事本 β"), actions)
    assert script.name == "錄一"
    assert script.target_window.title_pattern == re.escape("記事本 β")
    assert script.target_window.app_name is None     # 有標題時只用標題


def test_control_key_up_events_not_recorded():
    hook = FakeInputHook()
    session = RecorderSession(hook, Point(0, 0))
    session.start()
    hook.push(key("f9"))
    hook.push(key("f9", ts=5, kind=EventKind.KEY_UP))   # 控制鍵 up：自我過濾
    hook.push(key("b", ts=10))
    hook.push(key("f9", ts=20))
    actions = session.finish()
    assert [a.params["key"] for a in actions
            if a.type is ActionType.KEY_PRESS] == ["b"]


def test_events_before_first_toggle_ignored():
    hook = FakeInputHook()
    session = RecorderSession(hook, Point(0, 0))
    session.start()
    hook.push(key("x"))             # 尚未開始錄製
    hook.push(key("f9", ts=5))
    hook.push(key("y", ts=10))
    hook.push(key("f9", ts=20))
    actions = session.finish()
    assert [a.params["key"] for a in actions
            if a.type is ActionType.KEY_PRESS] == ["y"]


def test_stop_key_aborts_and_finish_returns_none():
    hook = FakeInputHook()
    states = []
    session = RecorderSession(hook, Point(0, 0), on_state=states.append)
    session.start()
    hook.push(key("f9"))
    hook.push(key("a", ts=10))
    hook.push(key("f10", ts=20))    # 放棄
    assert session.stop_event.is_set()
    assert session.finish() is None
    assert states == ["recording", "aborted"]


def test_stop_button_press_suppresses_trailing_click_but_not_f9():
    """M4 最終審查：面板 STOP 鈕的實體點擊（mouse_down/up）可能被 pynput hook
    搶先送進 Recorder，早於 Qt 的 clicked→toggle()。mark_stop_button_pressed()
    模擬面板在 `pressed` 訊號（早於 clicked）呼叫的旗標，之後的滑鼠事件應被
    忽略，不進腳本；F9 停止則完全不受影響（不呼叫此方法）。"""
    hook = FakeInputHook()
    states = []
    session = RecorderSession(hook, Point(0, 0), on_state=states.append)
    session.start()
    hook.push(key("f9"))                          # 開始錄製
    hook.push(mouse_down(10, 10, ts=10))
    hook.push(mouse_up(10, 10, ts=15))             # 合法點擊，應保留
    session.mark_stop_button_pressed()             # 模擬面板 STOP 鈕 pressed 訊號
    hook.push(mouse_down(20, 20, ts=20))           # STOP 鈕本身的點擊：應被忽略
    hook.push(mouse_up(20, 20, ts=25))
    session.toggle()                               # 模擬 clicked() 觸發 → 停止錄製
    actions = session.finish()
    assert [a.type for a in actions] == [ActionType.MOUSE_CLICK]
    assert actions[0].params == {"x": 10, "y": 10, "button": "left", "count": 1}


def test_cancelled_stop_button_press_does_not_permanently_suppress_clicks():
    """M4 最終審查 re-review 邊界：使用者在 STOP 鈕上按下（pressed 觸發、旗標設起）
    後拖離取消（clicked 不觸發、toggle() 不跑、錄製繼續）。該次點擊的實體放開
    仍會產生 MOUSE_UP → 旗標即解除，之後的合法點擊必須恢復錄製，不可被永久靜默丟棄。"""
    hook = FakeInputHook()
    session = RecorderSession(hook, Point(0, 0))
    session.start()
    hook.push(key("f9"))                          # 開始錄製
    session.mark_stop_button_pressed()             # 面板 STOP 鈕 pressed（隨後拖離取消）
    hook.push(mouse_down(20, 20, ts=20))           # 取消點擊的 down：吞掉
    hook.push(mouse_up(20, 20, ts=25))             # 取消點擊的 up：吞掉並解除旗標
    hook.push(mouse_down(30, 30, ts=40))           # 之後的合法點擊：必須恢復錄製
    hook.push(mouse_up(30, 30, ts=45))
    hook.push(key("f9", ts=60))                    # F9 停止
    actions = session.finish()
    assert [a.type for a in actions] == [ActionType.MOUSE_CLICK]
    assert actions[0].params == {"x": 30, "y": 30, "button": "left", "count": 1}


def test_finish_empty_when_nothing_recorded_and_bad_window_raises():
    hook = FakeInputHook()
    session = RecorderSession(hook, Point(0, 0))
    session.start()
    hook.push(key("f9"))
    hook.push(key("f9", ts=10))
    assert session.finish() == []
    with pytest.raises(ScriptValidationError, match="無法建立腳本"):
        script_from_recording("空", make_window(title="  ", app=""), [])


def test_on_event_reports_only_what_entered_the_script():
    """浮動窗顯示的必須與實際錄進腳本的一致——否則使用者以為錄到了其實沒有。

    控制鍵（F9）與 STOP 鈕的點擊都已在 _dispatch 濾掉，不得回報。
    """
    hook = FakeInputHook()
    seen = []
    session = RecorderSession(hook, Point(0, 0), on_event=seen.append)
    session.start()
    hook.push(key("a"))                  # 尚未開始錄：不回報
    hook.push(key("f9", ts=10))          # 控制鍵：開始錄製，本身不回報
    hook.push(key("home", ts=20))
    hook.push(key("num7", ts=30))
    hook.push(key("f9", ts=40))          # 控制鍵：停止，不回報
    session.finish()
    assert [e.key for e in seen] == ["home", "num7"]


def test_on_event_not_required():
    """沒給 on_event 也要正常運作（CLI 錄製不需要浮動窗）。"""
    hook = FakeInputHook()
    session = RecorderSession(hook, Point(0, 0))
    session.start()
    hook.push(key("f9"))
    hook.push(key("home", ts=10))
    hook.push(key("f9", ts=20))
    actions = session.finish()
    assert [a.params.get("key") for a in actions
            if a.type is ActionType.KEY_PRESS] == ["home"]
