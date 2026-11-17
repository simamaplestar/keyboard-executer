"""pywinctl 視窗控制：Windows 與 macOS 共用。"""
from __future__ import annotations

import re
import time

from keyboard_executor.platforms.base import WindowInfo, WindowManager

_POLL_INTERVAL = 0.05  # activate 後輪詢焦點的間隔（秒）
_FORCE_GRACE = 0.3  # 先讓 pywinctl 自行 activate 這麼久，grace 過才強制前景


class PywinctlWindowManager(WindowManager):
    def __init__(self, pwc=None, sleep=time.sleep, clock=time.monotonic,
                 force_foreground=None):
        if pwc is None:
            import pywinctl as pwc
        self._pwc = pwc
        self._sleep = sleep
        self._clock = clock
        self._force_foreground = force_foreground

    def list_all(self) -> list[WindowInfo]:
        infos = []
        for w in self._pwc.getAllWindows():
            try:
                infos.append(self._to_info(w))
            except Exception:
                continue   # 視窗在列舉期間關閉（GetWindowRect 等丟無效 handle）→ 略過
        return infos

    def find_windows(
        self, title_pattern: str | None = None, app_name: str | None = None
    ) -> list[WindowInfo]:
        result = []
        for w in self._pwc.getAllWindows():
            # 效能（M1 筆記／M3 審查待辦 5）：先以原生 title 過濾才做 _to_info——
            # macOS 的 getAppName() 是百 ms 級 AppleScript，watcher 每 tick 對每個
            # 不相干視窗都付此成本會把多規則監看拖到秒級延遲。
            if title_pattern and not re.search(title_pattern, w.title):
                continue
            info = self._to_info(w)
            if app_name and info.app_name.lower() != app_name.lower():
                continue
            result.append(info)
        return result

    def activate(self, window: WindowInfo, timeout_ms: int = 3000) -> bool:
        w = window.handle
        if getattr(w, "isMinimized", False):
            try:
                w.restore()          # 最小化先還原，否則切前景常無效
            except Exception:
                pass
        deadline = self._clock() + timeout_ms / 1000
        force_at = self._clock() + _FORCE_GRACE   # 先讓 pywinctl 試，grace 過才強切
        forced = False
        while True:
            if w.isActive:
                return True
            try:
                w.activate()          # 重試（不再只呼叫一次）
            except Exception:
                pass
            if (not forced and self._force_foreground is not None
                    and self._clock() >= force_at):
                forced = True
                try:
                    self._force_foreground(w.getHandle())   # Windows：AttachThreadInput 強切
                except Exception:
                    pass
            if self._clock() >= deadline:
                return bool(w.isActive)
            self._sleep(_POLL_INTERVAL)

    def refresh(self, window: WindowInfo) -> WindowInfo | None:
        w = window.handle
        try:
            if not w.isAlive:
                return None
            return self._to_info(w)
        except Exception:
            # 視窗物件失效（已關閉）時 pywinctl 可能丟平台相依例外
            return None

    def is_alive(self, window: WindowInfo) -> bool:
        try:
            return bool(window.handle.isAlive)
        except Exception:
            # 視窗物件失效（已關閉）時 pywinctl 可能丟平台相依例外
            return False

    def _to_info(self, w) -> WindowInfo:
        box = w.box
        return WindowInfo(
            handle=w, title=w.title, app_name=self._app_name(w),
            x=box.left, y=box.top, width=box.width, height=box.height,
            is_active=bool(w.isActive),
        )

    def _app_name(self, w) -> str:
        """視窗所屬程序名稱。pywinctl 的 getAppName() 會對「每個視窗」重新列舉所有
        執行中程式來比對 PID（單一視窗約 300ms，列全部視窗累積到十幾秒——這是開啟
        視窗選單很慢的元凶）；改以視窗 PID 直接查 psutil（sub-ms）。取不到時回退
        getAppName、再回退空字串。"""
        try:
            pid = w.getPID()
            if pid:
                import psutil
                return psutil.Process(int(pid)).name()
        except Exception:
            pass
        try:
            return w.getAppName() or ""
        except Exception:
            return ""
