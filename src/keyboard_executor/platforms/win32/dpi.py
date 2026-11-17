"""Windows 高 DPI 宣告。不宣告的話，系統縮放 ≠ 100% 時座標會整體偏移。"""
from __future__ import annotations


def ensure_dpi_awareness() -> None:
    import ctypes

    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE（Windows 8.1+）
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass  # 已由外部設定過或極舊版 Windows；寧可繼續也不要在啟動即崩潰
