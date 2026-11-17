"""顏色條件的純幾何（無 cv2）：OpenCV 色相環（0–179）的比對區間計算。"""
from __future__ import annotations


def hue_ranges(hue: int, tol: int) -> list[tuple[int, int]]:
    """回傳涵蓋 hue±tol 的 OpenCV 色相 (0–179) 閉區間清單。
    色相是環狀（179 接回 0），故跨邊界時回兩段；tol >= 90 已覆蓋整環。"""
    if tol >= 90:
        return [(0, 179)]
    lo = hue - tol
    hi = hue + tol
    if lo < 0:
        return [(180 + lo, 179), (0, hi)]
    if hi > 179:
        return [(lo, 179), (0, hi - 180)]
    return [(lo, hi)]
