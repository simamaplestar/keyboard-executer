from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton, WindowInfo
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(title="視窗A", app="AppA", active=False):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=10, y=20, width=800, height=600, is_active=active)


def test_fake_input_backend_records_calls():
    backend = FakeInputBackend()
    backend.key_press("enter")
    backend.key_combo(["ctrl", "s"])
    backend.type_text("哈囉")
    backend.mouse_click(5, 6, MouseButton.RIGHT, count=2)
    assert backend.calls == [
        ("key_press", "enter", 0),
        ("key_combo", ["ctrl", "s"]),
        ("type_text", "哈囉"),
        ("mouse_click", 5, 6, MouseButton.RIGHT, 2),
    ]


def test_fake_window_manager_finds_by_title_regex():
    w1, w2 = make_window("記事本 - 未命名"), make_window("瀏覽器", app="Browser")
    manager = FakeWindowManager([w1, w2])
    assert manager.find_windows(title_pattern="記事") == [w1]
    assert manager.find_windows(title_pattern="不存在") == []


def test_fake_window_manager_finds_by_app_name_case_insensitive():
    w = make_window(app="Notepad")
    manager = FakeWindowManager([w])
    assert manager.find_windows(app_name="notepad") == [w]


def test_fake_window_manager_activate_records_and_succeeds():
    w = make_window()
    manager = FakeWindowManager([w])
    assert manager.activate(w) is True
    assert manager.activated == [w]


def test_fake_window_manager_refresh_returns_none_for_closed_window():
    w = make_window()
    manager = FakeWindowManager([])
    assert manager.refresh(w) is None


def test_mouse_button_values():
    assert MouseButton.LEFT == "left"
    assert MouseButton("right") is MouseButton.RIGHT


def test_event_kind_values():
    assert EventKind.KEY_DOWN == "key_down"
    assert EventKind("mouse_up") is EventKind.MOUSE_UP


def test_input_event_carries_typed_kind():
    e = InputEvent(kind=EventKind.SCROLL, timestamp_ms=1500, x=10, y=20, dx=0, dy=-3)
    assert e.kind is EventKind.SCROLL
    assert (e.x, e.y, e.dx, e.dy) == (10, 20, 0, -3)


def test_fake_window_manager_is_alive_tracks_windows():
    w = make_window()
    manager = FakeWindowManager([w])
    assert manager.is_alive(w) is True
    manager.windows = []
    assert manager.is_alive(w) is False


def test_fake_screen_capture_records_region_and_returns_image():
    import numpy as np
    from keyboard_executor.core.geometry import Rect
    from tests.fakes import FakeScreenCapture

    img = np.zeros((6, 8, 3), dtype=np.uint8)
    cap = FakeScreenCapture(image=img, scale=2.0)
    out = cap.capture(Rect(10, 20, 8, 6))
    assert out is img
    assert cap.captures == [Rect(10, 20, 8, 6)]
    assert cap.scale_factor() == 2.0
