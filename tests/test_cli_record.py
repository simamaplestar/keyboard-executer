import re

from keyboard_executor.cli import run_record
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import Action, ActionType
from keyboard_executor.platforms.base import EventKind, InputEvent, InputHook, WindowInfo
from keyboard_executor.platforms.factory import Platform
from keyboard_executor.storage.scripts import ScriptStorage
from tests.fakes import FakeInputBackend, FakeWindowManager


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


class ScriptedHook(InputHook):
    """start 時同步把預先安排好的事件全部送進 callback（模擬使用者操作）。"""

    def __init__(self, events):
        self._events = list(events)
        self.started = 0
        self.stopped = 0

    def start(self, on_event):
        self.started += 1
        for event in self._events:
            on_event(event)

    def stop(self):
        self.stopped += 1


class FakeRecorder:
    """記錄 feed 呼叫；finish 回傳注入的動作清單。"""

    def __init__(self, origin, mode="simplified"):
        self.origin = origin
        self.mode = mode
        self.fed = []
        self.finish_actions = [
            Action(type=ActionType.KEY_PRESS, params={"key": "a", "hold_ms": 0}),
        ]

    def feed(self, event):
        self.fed.append(event)

    def finish(self):
        return list(self.finish_actions)


def make_window(title="記事本", app="Notepad"):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=100, y=200, width=800, height=600, is_active=False)


def make_platform(windows=None):
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    return Platform(input_backend=FakeInputBackend(), window_manager=manager)


def run(events, tmp_path, answers=("我的腳本",), title_pattern="記事本",
        full_trajectory=False, platform=None, finish_actions=None):
    storage = ScriptStorage(tmp_path)
    hook = ScriptedHook(events)
    recorders = []

    def recorder_factory(origin, mode="simplified"):
        recorder = FakeRecorder(origin, mode)
        if finish_actions is not None:
            recorder.finish_actions = list(finish_actions)
        recorders.append(recorder)
        return recorder

    answer_iter = iter(answers)
    echoes = []
    code = run_record(platform if platform is not None else make_platform(),
                      storage, hook,
                      ask=lambda _prompt: next(answer_iter),
                      echo=echoes.append,
                      recorder_factory=recorder_factory,
                      title_pattern=title_pattern,
                      full_trajectory=full_trajectory)
    return code, storage, recorders, echoes, hook


HAPPY_EVENTS = [
    key_down("x", ts=0),     # F9 之前：不得進 recorder
    key_down("f9", ts=10),   # 開始錄製（控制鍵，不得進 recorder）
    key_up("f9", ts=20),
    key_down("a", ts=100),
    key_up("a", ts=150),
    key_down("f9", ts=500),  # 停止錄製
]


def test_record_happy_path_saves_script(tmp_path):
    code, storage, recorders, echoes, hook = run(HAPPY_EVENTS, tmp_path)
    assert code == 0
    assert hook.started == 1 and hook.stopped == 1
    [recorder] = recorders
    assert recorder.origin == Point(100, 200)
    assert recorder.mode == "simplified"
    assert [(e.kind, e.key) for e in recorder.fed] == [
        (EventKind.KEY_DOWN, "a"), (EventKind.KEY_UP, "a"),
    ]
    loaded = storage.load("我的腳本")
    assert loaded.target_window.title_pattern == re.escape("記事本")
    assert [a.type for a in loaded.actions] == [ActionType.KEY_PRESS]
    assert any("已儲存" in line for line in echoes)


def test_record_f10_abandons_without_saving(tmp_path):
    events = [key_down("f9", ts=0), key_down("a", ts=10), key_down("f10", ts=20)]
    code, storage, _, echoes, _ = run(events, tmp_path)
    assert code == 1
    assert any("已放棄" in line for line in echoes)
    assert storage.list_names() == []


def test_record_empty_recording_returns_error(tmp_path):
    events = [key_down("f9", ts=0), key_down("f9", ts=100)]
    code, storage, _, echoes, _ = run(events, tmp_path, finish_actions=[])
    assert code == 1
    assert any("沒有錄到" in line for line in echoes)
    assert storage.list_names() == []


def test_record_full_trajectory_uses_full_mode(tmp_path):
    code, _, recorders, _, _ = run(HAPPY_EVENTS, tmp_path, full_trajectory=True)
    assert code == 0
    assert recorders[0].mode == "full"


def test_record_title_pattern_not_found_returns_error(tmp_path):
    code, _, _, echoes, _ = run(HAPPY_EVENTS, tmp_path, title_pattern="無此視窗")
    assert code == 1
    assert any("找不到符合" in line for line in echoes)


def test_record_picker_flow_selects_window(tmp_path):
    # 不給 title_pattern → 走互動選單：先答視窗編號，再答腳本名稱
    code, storage, _, _, _ = run(HAPPY_EVENTS, tmp_path,
                                 answers=("1", "選單腳本"), title_pattern=None)
    assert code == 0
    assert storage.list_names() == ["選單腳本"]


def test_record_picker_cancel_returns_error(tmp_path):
    code, storage, _, _, hook = run(HAPPY_EVENTS, tmp_path,
                                    answers=("q",), title_pattern=None)
    assert code == 1
    assert storage.list_names() == []
    assert hook.started == 0  # 取消選視窗就不開監聽


def test_record_invalid_script_name_returns_error(tmp_path):
    code, storage, _, echoes, _ = run(HAPPY_EVENTS, tmp_path, answers=("a/b",))
    assert code == 1
    assert any("儲存失敗" in line for line in echoes)
    assert storage.list_names() == []
