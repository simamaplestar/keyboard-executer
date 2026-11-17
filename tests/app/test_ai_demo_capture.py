import cv2
import numpy as np

from keyboard_executor.app.ai_demo_capture import FrameSampler, read_dot
from keyboard_executor.platforms.base import WindowInfo
from tests.fakes import FakeWindowManager

WIN = WindowInfo(handle=object(), title="MapleStory Worlds", app_name="msw.exe",
                 x=100, y=50, width=320, height=240, is_active=True)
MINIMAP = (20, 30, 100, 60)


class WindowCapture:
    """整個視窗的假截圖：小地圖範圍內 (40, 25) 畫一顆黃點。"""

    def __init__(self, scale=1.0, fail_at=()):
        self.scale, self.rects, self.calls, self.fail_at = scale, [], 0, set(fail_at)

    def scale_factor(self):
        return self.scale

    def capture(self, rect):
        self.calls += 1
        if self.calls in self.fail_at:
            raise OSError("擷取失敗")
        self.rects.append(rect)
        image = np.zeros((rect.height, rect.width, 3), np.uint8)
        if rect.width > 150:                      # 整個視窗
            cx, cy = round((20 + 40) * self.scale), round((30 + 25) * self.scale)
        else:                                     # 只截小地圖
            cx, cy = round(40 * self.scale), round(25 * self.scale)
        cv2.circle(image, (cx, cy), round(6 * self.scale), (0, 230, 255), -1)
        return image


class Clock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


def test_sampler_writes_frames_with_ids(tmp_path):
    capture = WindowCapture()
    sampler = FrameSampler(lambda: capture, FakeWindowManager([WIN]), WIN, MINIMAP,
                           tmp_path, "D", t0_ms=10_000, clock=Clock([10.0, 10.5, 11.0]))
    for _ in range(3):
        sampler.sample_once(capture)
    frames = sampler.frames()
    assert [f.id for f in frames] == ["D1", "D2", "D3"]
    assert [f.t_ms for f in frames] == [0, 500, 1000]
    assert all(f.path.is_file() for f in frames)
    assert frames[0].size == (320, 240)
    assert abs(frames[0].dot[0] - 60) <= 1 and abs(frames[0].dot[1] - 55) <= 1
    assert frames[0].thumb.shape == (36, 64)
    assert capture.rects[0].x == 100 and capture.rects[0].width == 320


def test_sampler_hidpi_dot_in_window_coordinates(tmp_path):
    capture = WindowCapture(scale=2.0)
    sampler = FrameSampler(lambda: capture, FakeWindowManager([WIN]), WIN, MINIMAP,
                           tmp_path, "R1-", t0_ms=0, clock=Clock([0.0]))
    sampler.sample_once(capture)
    [frame] = sampler.frames()
    assert frame.id == "R1-1"
    assert frame.size == (640, 480)
    assert abs(frame.dot[0] - 60) <= 1 and abs(frame.dot[1] - 55) <= 1


def test_sampler_survives_capture_error(tmp_path):
    capture = WindowCapture(fail_at={2})
    sampler = FrameSampler(lambda: capture, FakeWindowManager([WIN]), WIN, MINIMAP,
                           tmp_path, "D", t0_ms=0, clock=Clock([0.0, 0.5, 1.0]))
    for _ in range(3):
        sampler.sample_once(capture)
    assert [f.id for f in sampler.frames()] == ["D1", "D2"]


def test_sampler_thread_start_stop(tmp_path):
    capture = WindowCapture()
    sampler = FrameSampler(lambda: capture, FakeWindowManager([WIN]), WIN, MINIMAP,
                           tmp_path, "D", t0_ms=0, interval=0.01)
    sampler.start()
    import time
    time.sleep(0.15)
    frames = sampler.stop()
    assert len(frames) >= 2


def test_read_dot_in_window_coordinates():
    capture = WindowCapture()
    pos = read_dot(capture, FakeWindowManager([WIN]), WIN, MINIMAP)
    assert capture.rects[0].x == 120 and capture.rects[0].y == 80
    assert abs(pos[0] - 60) <= 1 and abs(pos[1] - 55) <= 1


def test_read_dot_none_when_no_dot():
    class Blank(WindowCapture):
        def capture(self, rect):
            return np.zeros((rect.height, rect.width, 3), np.uint8)
    assert read_dot(Blank(), FakeWindowManager([WIN]), WIN, MINIMAP) is None
