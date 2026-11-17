"""Windows 強制前景：用 AttachThreadInput 繞過 SetForegroundWindow 的前景鎖。

別的程式握有前景、且本程式不被允許搶前景時，一般 SetForegroundWindow 只會閃
工作列而不真的切換。把本執行緒的輸入佇列附接到前景與目標視窗的執行緒後再切，
可繞過此限制。純 best-effort：任何失敗都吞掉，最後以 GetForegroundWindow 判定。
僅 Windows 使用；把視窗叫到前景是通用視窗管理，非反偵測。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SW_RESTORE = 9


def force_foreground(hwnd: int, *, user32=None, kernel32=None) -> bool:
    """把 hwnd 硬切到前景，回傳是否成功（GetForegroundWindow == hwnd）。"""
    try:
        if user32 is None or kernel32 is None:
            import ctypes
            user32 = user32 or ctypes.windll.user32
            kernel32 = kernel32 or ctypes.windll.kernel32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)          # 只在最小化時還原，避免把最大化視窗縮小
        if user32.GetForegroundWindow() == hwnd:
            return True
        cur_tid = kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        attached = []
        for tid in (fg_tid, target_tid):
            if tid and tid != cur_tid and user32.AttachThreadInput(cur_tid, tid, True):
                attached.append(tid)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(cur_tid, tid, False)
        return bool(user32.GetForegroundWindow() == hwnd)
    except Exception:
        logger.warning("強制前景失敗", exc_info=True)
        return False
