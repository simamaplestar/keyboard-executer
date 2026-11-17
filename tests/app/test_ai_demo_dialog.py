import numpy as np

from keyboard_executor.app.ai_demo_dialog import AiDemoDialog
from keyboard_executor.core.ai_demo.frames import Frame, make_thumb
from keyboard_executor.platforms.base import EventKind, InputEvent, WindowInfo
from keyboard_executor.storage.ai_demo_sessions import AiDemoSessionStore
from tests.fakes import FakeWindowManager

WIN = WindowInfo(handle=object(), title="MapleStory Worlds", app_name="msw.exe",
                 x=0, y=0, width=320, height=240, is_active=True)


class FakeSession:
    def __init__(self, hook, origin, *, recorder_factory, on_state, **kw):
        self.recorder = recorder_factory(origin, mode="simplified")
        self.on_state = on_state
        self.started = False

    def start(self):
        self.started = True

    def toggle(self):
        pass

    def finish(self):
        return self.recorder.finish()


class FakeSampler:
    def __init__(self, capture_factory, wm, win, region, out_dir, prefix, *, t0_ms, **kw):
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        img = np.zeros((10, 10, 3), np.uint8)
        return [Frame("D1", 0, None, (320, 240), (50.0, 40.0), make_thumb(img))]


class FakeCapture:
    def scale_factor(self):
        return 1.25


def make_dialog(tmp_path, dot):
    return AiDemoDialog(FakeWindowManager([WIN]), AiDemoSessionStore(tmp_path),
                        hook_factory=lambda: object(), session_factory=FakeSession,
                        sampler_factory=FakeSampler, capture_factory=FakeCapture,
                        dot_reader=lambda *a: dot, overlay_factory=None)


def test_dialog_refuses_start_without_dot(qapp, tmp_path):
    dialog = make_dialog(tmp_path, None)
    dialog.region_edit.setText("10, 20, 200, 100")
    dialog.toggle_button.click()
    assert "找不到角色黃點" in dialog.status_label.text()
    assert dialog._session is None


def test_dialog_requires_region(qapp, tmp_path):
    dialog = make_dialog(tmp_path, (50.0, 40.0))
    dialog.toggle_button.click()
    assert "小地圖" in dialog.status_label.text()


def test_dialog_emits_recording_on_done(qapp, tmp_path):
    dialog = make_dialog(tmp_path, (50.0, 40.0))
    dialog.region_edit.setText("10, 20, 200, 100")
    dialog.goal_edit.setText("左右打怪")
    got = []
    dialog.recorded.connect(lambda rec, win, session: got.append((rec, win, session)))
    dialog.toggle_button.click()
    assert dialog._session.started
    dialog._on_state("recording")
    dialog._session.recorder.feed(InputEvent(EventKind.KEY_DOWN,
                                             dialog._t0_ms + 1000, key="right"))
    dialog._session.recorder.feed(InputEvent(EventKind.KEY_UP,
                                             dialog._t0_ms + 2500, key="right"))
    dialog._on_state("done")
    [(rec, win, session)] = got
    assert win is WIN
    assert rec.start_dot == (50.0, 40.0)
    assert rec.minimap_region == (10, 20, 200, 100)
    assert rec.goal_text == "左右打怪"
    assert rec.capture_scale == 1.25
    assert rec.holds[0].key == "right" and rec.holds[0].start_ms == 1000
    assert rec.event_times_ms == [1000]
    assert session.is_dir()
    assert (session / "timeline.json").is_file()


def test_dialog_abort_emits_nothing(qapp, tmp_path):
    dialog = make_dialog(tmp_path, (50.0, 40.0))
    dialog.region_edit.setText("10, 20, 200, 100")
    got = []
    dialog.recorded.connect(lambda *a: got.append(a))
    dialog.toggle_button.click()
    dialog._on_state("recording")
    dialog._on_state("aborted")
    assert got == []
    assert "放棄" in dialog.status_label.text()


def test_escape_during_recording_aborts(qapp, tmp_path):
    """Esc 走 reject() 不經 closeEvent：也要停止監聽與截圖，之後不可再觸發試跑。"""
    dialog = make_dialog(tmp_path, (50.0, 40.0))
    dialog.region_edit.setText("10, 20, 200, 100")
    got = []
    dialog.recorded.connect(lambda *a: got.append(a))
    dialog.toggle_button.click()
    dialog._on_state("recording")
    sampler = dialog._sampler
    session = dialog._session
    finished = []
    session.finish = lambda: finished.append(True)
    dialog.reject()
    assert dialog._session is None and dialog._sampler is None
    assert finished == [True]
    assert got == []
