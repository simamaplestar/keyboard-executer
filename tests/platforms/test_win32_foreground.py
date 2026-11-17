from keyboard_executor.platforms.win32.foreground import force_foreground


class FakeU32:
    def __init__(self, hwnd, activate_ok=True, iconic=False):
        self._hwnd = hwnd
        self._activate_ok = activate_ok
        self._iconic = iconic
        self.fg = 999                     # 一開始前景不是目標
        self.calls = []
        self.attached = []

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("ShowWindow", hwnd, cmd))

    def GetForegroundWindow(self):
        return self.fg

    def GetWindowThreadProcessId(self, hwnd, _pid):
        return 100 if hwnd == self._hwnd else 200   # 目標 thread=100、前景 thread=200

    def AttachThreadInput(self, cur, tid, attach):
        self.calls.append(("Attach", cur, tid, attach))
        if attach:
            self.attached.append(tid)
        return 1

    def BringWindowToTop(self, hwnd):
        self.calls.append(("BringWindowToTop", hwnd))

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        if self._activate_ok:
            self.fg = hwnd                # 切成功

    def IsIconic(self, hwnd):
        return self._iconic


class FakeK32:
    def GetCurrentThreadId(self):
        return 1


def test_force_foreground_attaches_sets_and_detaches():
    u = FakeU32(hwnd=42)
    assert force_foreground(42, user32=u, kernel32=FakeK32()) is True
    assert ("SetForegroundWindow", 42) in u.calls
    assert 200 in u.attached and 100 in u.attached      # 前景 thread 與目標 thread 都附接
    assert ("Attach", 1, 200, False) in u.calls         # 用完有 detach
    assert ("Attach", 1, 100, False) in u.calls


def test_force_foreground_true_when_already_foreground():
    u = FakeU32(hwnd=42)
    u.fg = 42                                            # 已是前景
    assert force_foreground(42, user32=u, kernel32=FakeK32()) is True
    assert all(c[0] != "SetForegroundWindow" for c in u.calls)   # 不必再切


def test_force_foreground_false_on_error():
    class Boom:
        def IsIconic(self, *a):
            raise RuntimeError("壞了")
    assert force_foreground(42, user32=Boom(), kernel32=FakeK32()) is False


def test_force_foreground_restores_only_when_minimized():
    u = FakeU32(hwnd=42, iconic=True)
    force_foreground(42, user32=u, kernel32=FakeK32())
    assert ("ShowWindow", 42, 9) in u.calls          # 最小化 → 還原（SW_RESTORE=9）


def test_force_foreground_does_not_restore_when_not_minimized():
    u = FakeU32(hwnd=42, iconic=False)
    force_foreground(42, user32=u, kernel32=FakeK32())
    assert all(c[0] != "ShowWindow" for c in u.calls)  # 非最小化 → 不動視窗大小
