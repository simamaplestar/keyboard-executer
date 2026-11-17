"""小地圖路線錄製：事件紀錄、黃點取樣、錄製面板產生並儲存練功腳本。"""
import numpy as np
import cv2

from keyboard_executor.app.recorder_panel import RecorderPanel
from keyboard_executor.app.route_recorder import MinimapSampler, RouteEventLog
from keyboard_executor.platforms.base import EventKind, InputEvent, WindowInfo
from keyboard_executor.storage.scripts import ScriptStorage
from tests.core.test_route_learn import Rec
from tests.fakes import FakeInputHook, FakeWindowManager

WIN = WindowInfo(handle=object(), title="MapleStory Worlds", app_name="msw.exe",
                 x=100, y=50, width=1280, height=720, is_active=True)


def test_event_log_keeps_key_events_in_seconds():
    log = RouteEventLog(None, mode="simplified")
    log.feed(InputEvent(EventKind.KEY_DOWN, 1500, key="c"))
    log.feed(InputEvent(EventKind.MOUSE_DOWN, 1600, x=1, y=1))
    log.feed(InputEvent(EventKind.KEY_UP, 1700, key="c"))
    events = log.finish()
    assert [(e.t, e.key, e.down) for e in events] == [(1.5, "c", True), (1.7, "c", False)]


class DotCapture:
    def __init__(self, dot):
        self.dot, self.rects = dot, []

    def scale_factor(self):
        return 1.0

    def capture(self, rect):
        self.rects.append(rect)
        image = np.zeros((rect.height, rect.width, 3), np.uint8)
        cv2.circle(image, self.dot, 6, (0, 230, 255), -1)       # 飽和黃（BGR）
        return image


def test_sampler_reads_dot_in_window_coordinates():
    capture = DotCapture((40, 30))
    sampler = MinimapSampler(lambda: capture, FakeWindowManager([WIN]), WIN, [20, 160, 300, 260])
    pos = sampler.read_once(capture)
    assert capture.rects[0].x == 120 and capture.rects[0].y == 210
    assert abs(pos[0] - 60) <= 1 and abs(pos[1] - 190) <= 1


class RouteSession:
    instances = []

    def __init__(self, hook, origin, *, mode="simplified", toggle_key="f9", stop_key="f10",
                 on_state=None, on_event=None, recorder_factory=None):
        self.recorder_factory, self.on_state = recorder_factory, on_state
        self.events = None
        RouteSession.instances.append(self)

    def start(self):
        pass

    def toggle(self):
        pass

    def mark_stop_button_pressed(self):
        pass

    def finish(self):
        return self.events


class FakeSampler:
    def __init__(self, capture_factory, wm, win, region):
        self.region, self.samples, self.started = region, [], False

    def start(self):
        self.started = True

    def stop(self):
        return self.samples


def test_panel_learns_route_and_saves_script(qapp, tmp_path):
    samplers = []

    def sampler_factory(*args):
        samplers.append(FakeSampler(*args))
        return samplers[-1]

    storage = ScriptStorage(tmp_path)
    panel = RecorderPanel(FakeWindowManager([WIN]), storage, hook_factory=FakeInputHook,
                          session_factory=RouteSession, sampler_factory=sampler_factory,
                          route_settle_ms=0)
    panel.route_check.setChecked(True)
    panel.region_edit.setText("20, 160, 300, 260")
    panel.loop_spin.setValue(30)
    panel.style_combo.setCurrentIndex(panel.style_combo.findData("replay"))
    panel.toggle_button.click()
    session = RouteSession.instances[-1]
    assert session.recorder_factory is RouteEventLog and samplers[-1].started
    rec = Rec(100, 300)
    rec.walk("right", 180, hold=("c",))
    rec.climb(250)
    rec.walk("left", 120, hold=("c",))
    session.events, samplers[-1].samples = rec.events, rec.samples
    panel._route_window = (None, None)
    panel._on_state("recording")
    panel._route_window = (None, None)
    panel._on_state("done")
    for _ in range(5):
        qapp.processEvents()
    assert "照錄製重播 3 步" in panel.status_label.text(), panel.status_label.text()
    panel.name_edit.setText("學到的路線")
    panel._on_save_clicked()
    script = storage.load("學到的路線")
    loop = script.actions[0]
    assert loop.params["count"] == 30
    kinds = [a.params.get("method") for a in loop.params["actions"]
             if str(a.type) == "minimap_move"]
    assert kinds == ["walk", "rope", "walk"]


def test_panel_requires_region_before_route_recording(qapp, tmp_path):
    panel = RecorderPanel(FakeWindowManager([WIN]), ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=RouteSession,
                          sampler_factory=FakeSampler, route_settle_ms=0)
    before = len(RouteSession.instances)
    panel.route_check.setChecked(True)
    panel.toggle_button.click()
    assert len(RouteSession.instances) == before
    assert "小地圖範圍" in panel.status_label.text()


def test_panel_ignores_timed_keys_and_saves_them(qapp, tmp_path):
    samplers = []

    def sampler_factory(*args):
        samplers.append(FakeSampler(*args))
        return samplers[-1]

    storage = ScriptStorage(tmp_path)
    panel = RecorderPanel(FakeWindowManager([WIN]), storage, hook_factory=FakeInputHook,
                          session_factory=RouteSession, sampler_factory=sampler_factory,
                          route_settle_ms=0)
    panel.route_check.setChecked(True)
    panel.region_edit.setText("20, 160, 300, 260")
    panel.timed_edit.setText("1:120")
    panel.toggle_button.click()
    session = RouteSession.instances[-1]
    rec = Rec(100, 300)
    rec.press("1")                        # 錄製中剛好放了 buff
    rec.walk("right", 180)
    session.events, samplers[-1].samples = rec.events, rec.samples
    panel._on_state("done")
    for _ in range(5):
        qapp.processEvents()
    assert "照錄製重播 1 步" in panel.status_label.text(), panel.status_label.text()
    panel.name_edit.setText("含定時技能")
    panel._on_save_clicked()
    script = storage.load("含定時技能")
    assert [t.key for t in script.settings.timed_keys] == ["1"]
    body = script.actions[0].params["actions"]
    assert not any(str(a.type) == "key_press" and a.params["key"] == "1" for a in body)


def test_panel_patrol_mode_saves_map_sidecar(qapp, tmp_path):
    from tests.core.test_route_map import two_laps
    samplers = []

    def sampler_factory(*args):
        samplers.append(FakeSampler(*args))
        samplers[-1].last_image = np.zeros((20, 30, 3), np.uint8)
        return samplers[-1]

    storage = ScriptStorage(tmp_path)
    panel = RecorderPanel(FakeWindowManager([WIN]), storage, hook_factory=FakeInputHook,
                          session_factory=RouteSession, sampler_factory=sampler_factory,
                          route_settle_ms=0)
    panel.route_check.setChecked(True)
    panel.region_edit.setText("20, 160, 300, 260")
    panel.sweep_spin.setValue(2)
    panel.toggle_button.click()
    rec = two_laps()
    RouteSession.instances[-1].events, samplers[-1].samples = rec.events, rec.samples
    panel._on_state("done")
    for _ in range(5):
        qapp.processEvents()
    text = panel.status_label.text()
    assert "整理成 2 個打怪平台循環，每層左右掃 2 趟" in text and "平台 1" in text
    panel.name_edit.setText("巡邏")
    panel._on_save_clicked()
    data = storage.load_route_map("巡邏")
    assert "平台 2" in data["analysis"] and data["map"]["cycle"] == [1, 2]
    assert data["recording"]["samples"] and storage.route_map_image("巡邏") is not None
    sweeps = [a for a in storage.load("巡邏").actions[0].params["actions"]
              if a.params.get("name", "").startswith("平台")]
    assert len(sweeps) == 8
    storage.delete("巡邏")
    assert storage.load_route_map("巡邏") is None
