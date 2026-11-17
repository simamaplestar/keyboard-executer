"""座標系統：所有腳本座標一律為「目標視窗左上角為原點」的相對座標。

單位為「平台輸入座標」：Windows 上是實體像素（已宣告 DPI aware）；macOS 上是
Cocoa 點（Retina 螢幕 1 點 = 2 實體像素）。M1/M2 內部（pywinctl 幾何、pynput
滑鼠）單位一致；M3 引入螢幕截圖（實體像素）時需在 ScreenCapture 層處理換算，
見 docs/superpowers/notes/2026-07-06-m1-final-review.md。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


def to_absolute(origin: Point, rel: Point) -> Point:
    """視窗相對座標 → 螢幕絕對座標。origin 為視窗左上角的螢幕座標。"""
    return Point(origin.x + rel.x, origin.y + rel.y)


def to_relative(origin: Point, abs_pt: Point) -> Point:
    """螢幕絕對座標 → 視窗相對座標。origin 為視窗左上角的螢幕座標。"""
    return Point(abs_pt.x - origin.x, abs_pt.y - origin.y)
