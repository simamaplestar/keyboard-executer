from types import SimpleNamespace

from keyboard_executor.platforms.common.window_pywinctl import PywinctlWindowManager


class StubWindow:
    """模擬 pywinctl 視窗物件的最小介面。"""

    def __init__(self, title, app="App", box=(10, 20, 800, 600), active=False,
                 alive=True, minimized=False, handle_id=1234):
        self.title = title
        self._app = app
        self.box = SimpleNamespace(left=box[0], top=box[1], width=box[2], height=box[3])
        self.isActive = active
        self.isAlive = alive
        self.isMinimized = minimized
        self.activate_calls = 0
        self.restore_calls = 0
        self._handle_id = handle_id

    def getAppName(self):
        return self._app

    def activate(self):
        self.activate_calls += 1

    def restore(self):
        self.restore_calls += 1
        self.isMinimized = False

    def getHandle(self):
        return self._handle_id


class StubPwc:
    def __init__(self, windows):
        self._windows = windows

    def getAllWindows(self):
        return list(self._windows)


class FakeClock:
    """sleep 一次就前進一格的假時鐘。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_manager(windows):
    clock = FakeClock()
    manager = PywinctlWindowManager(
        pwc=StubPwc(windows), sleep=clock.sleep, clock=clock.monotonic
    )
    return manager, clock


def test_list_all_converts_to_window_info():
    manager, _ = make_manager([StubWindow("記事本", app="Notepad", box=(1, 2, 300, 400))])
    infos = manager.list_all()
    assert len(infos) == 1
    info = infos[0]
    assert (info.title, info.app_name) == ("記事本", "Notepad")
    assert (info.x, info.y, info.width, info.height) == (1, 2, 300, 400)


def test_find_windows_by_title_regex():
    manager, _ = make_manager([StubWindow("記事本 - 未命名"), StubWindow("瀏覽器")])
    result = manager.find_windows(title_pattern="記事")
    assert [w.title for w in result] == ["記事本 - 未命名"]


def test_find_windows_by_app_name_case_insensitive():
    manager, _ = make_manager([StubWindow("A", app="Notepad"), StubWindow("B", app="Safari")])
    result = manager.find_windows(app_name="notepad")
    assert [w.app_name for w in result] == ["Notepad"]


def test_activate_returns_true_when_window_becomes_active():
    stub = StubWindow("目標")
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]

    # 第一次輪詢後視窗變為 active
    original_sleep = manager._sleep

    def sleep_then_activate(seconds):
        original_sleep(seconds)
        stub.isActive = True

    manager._sleep = sleep_then_activate
    assert manager.activate(info) is True
    assert stub.activate_calls == 1


def test_activate_times_out_and_returns_false():
    stub = StubWindow("目標", active=False)
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info, timeout_ms=200) is False


def test_refresh_returns_updated_geometry():
    stub = StubWindow("目標", box=(0, 0, 100, 100))
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    stub.box = SimpleNamespace(left=50, top=60, width=100, height=100)
    updated = manager.refresh(info)
    assert (updated.x, updated.y) == (50, 60)


def test_refresh_returns_none_when_window_closed():
    stub = StubWindow("目標", alive=False)
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.refresh(info) is None


def test_find_windows_intersects_title_and_app():
    manager, _ = make_manager([
        StubWindow("記事本 A", app="Notepad"),
        StubWindow("記事本 B", app="Editor"),
        StubWindow("瀏覽器", app="Notepad"),
    ])
    result = manager.find_windows(title_pattern="記事本", app_name="notepad")
    assert [w.title for w in result] == ["記事本 A"]


class ExplodingWindow:
    """isAlive 一讀就拋例外的視窗物件（模擬 pywinctl 平台相依失效）。"""

    title = "爆炸"

    def __init__(self):
        self.box = SimpleNamespace(left=0, top=0, width=10, height=10)
        self.isActive = False

    def getAppName(self):
        return "App"

    def activate(self):
        pass

    @property
    def isAlive(self):
        raise RuntimeError("視窗物件已失效")


def test_is_alive_true_for_living_window():
    manager, _ = make_manager([StubWindow("目標")])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is True


def test_is_alive_false_when_window_closed():
    manager, _ = make_manager([StubWindow("目標", alive=False)])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is False


def test_is_alive_false_when_handle_raises():
    manager, _ = make_manager([ExplodingWindow()])
    info = manager.list_all()[0]
    assert manager.is_alive(info) is False


def test_find_windows_title_filter_skips_get_app_name():
    """M3 審查待辦 5：getAppName() 在 macOS 是百 ms 級 AppleScript，
    find_windows 必須先以原生 title 過濾、再做 _to_info 轉換，
    避免 watcher 每 tick 對每個不相干視窗都付 getAppName 成本。"""
    class CountingWindow(StubWindow):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.app_name_calls = 0

        def getAppName(self):
            self.app_name_calls += 1
            return super().getAppName()

    target = CountingWindow("記事本")
    other = CountingWindow("瀏覽器")
    manager, _ = make_manager([target, other])
    result = manager.find_windows(title_pattern="記事")
    assert [w.title for w in result] == ["記事本"]
    assert target.app_name_calls == 1
    assert other.app_name_calls == 0   # title 不合的視窗不得呼叫 getAppName


def test_activate_restores_minimized_window():
    stub = StubWindow("目標", minimized=True)

    def activate_side():
        stub.activate_calls += 1
        stub.isActive = True

    stub.activate = activate_side
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert stub.restore_calls == 1
    assert stub.isMinimized is False


def test_activate_retries_activate_until_active():
    stub = StubWindow("目標")

    def activate_side():
        stub.activate_calls += 1
        if stub.activate_calls >= 3:        # 第三次才成功 → 證明有重試
            stub.isActive = True

    stub.activate = activate_side
    manager, _ = make_manager([stub])
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert stub.activate_calls >= 3


def test_activate_calls_force_foreground_after_grace():
    stub = StubWindow("目標")               # 靠自己永遠切不到
    forced = []

    def fake_force(hwnd):
        forced.append(hwnd)
        stub.isActive = True                # 強制前景成功
        return True

    clock = FakeClock()
    manager = PywinctlWindowManager(pwc=StubPwc([stub]), sleep=clock.sleep,
                                    clock=clock.monotonic, force_foreground=fake_force)
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert forced == [stub.getHandle()]     # grace 過後呼叫恰一次，帶 handle


def test_activate_no_force_when_active_before_grace():
    stub = StubWindow("目標")
    forced = []

    def activate_side():
        stub.activate_calls += 1
        stub.isActive = True                # 立刻成功（grace 之前）

    stub.activate = activate_side
    clock = FakeClock()
    manager = PywinctlWindowManager(pwc=StubPwc([stub]), sleep=clock.sleep,
                                    clock=clock.monotonic,
                                    force_foreground=lambda hwnd: forced.append(hwnd))
    info = manager.list_all()[0]
    assert manager.activate(info) is True
    assert forced == []                     # grace 前就成功，不呼叫 force
