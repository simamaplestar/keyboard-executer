"""示範事件時間軸：保留按鍵按住區間與滑鼠動作，給 AI 對照截圖。

不重用 core.recorder.Recorder：它會把按鍵記成 hold_ms=0、丟掉 KEY_UP，長按資訊會消失。
時間一律是相對錄製開始（start(t0_ms)，未呼叫則為第一個事件）的毫秒。
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from keyboard_executor.core.geometry import Point
from keyboard_executor.platforms.base import EventKind, InputEvent

_CLICK_TOLERANCE_PX = 5


@dataclass(frozen=True)
class KeyHold:
    key: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class MouseAct:
    kind: str            # "click" | "drag" | "scroll"
    t_ms: int
    x: int
    y: int
    button: str = ""
    to: tuple[int, int] | None = None
    dy: int = 0


class DemoEventLog:
    """RecorderSession 的 recorder_factory（簽名同 Recorder）。非執行緒安全，
    RecorderSession 已序列化 feed()。"""

    def __init__(self, origin: Point, mode: str = "simplified"):
        self._origin = origin
        self._t0: int | None = None
        self._held: dict[str, int] = {}
        self._holds: list[KeyHold] = []
        self._acts: list[MouseAct] = []
        self._mouse_down: tuple[int, int, int, str] | None = None
        self._event_times: list[int] = []
        self._last_ms = 0

    def start(self, t0_ms: int) -> None:
        self._t0 = t0_ms

    def _rel_ms(self, event: InputEvent) -> int:
        if self._t0 is None:
            self._t0 = event.timestamp_ms
        ms = max(0, event.timestamp_ms - self._t0)
        self._last_ms = max(self._last_ms, ms)
        return ms

    def _rel_pt(self, event: InputEvent) -> tuple[int, int]:
        return event.x - self._origin.x, event.y - self._origin.y

    def feed(self, event: InputEvent) -> None:
        kind = event.kind
        if kind is EventKind.KEY_DOWN and event.key:
            ms = self._rel_ms(event)
            if event.key not in self._held:      # 自動重複的 down 忽略
                self._held[event.key] = ms
                self._event_times.append(ms)
        elif kind is EventKind.KEY_UP and event.key:
            ms = self._rel_ms(event)
            start = self._held.pop(event.key, None)
            if start is not None:
                self._holds.append(KeyHold(event.key, start, ms))
        elif kind is EventKind.MOUSE_DOWN and event.x is not None:
            ms = self._rel_ms(event)
            x, y = self._rel_pt(event)
            button = str(event.button) if event.button is not None else ""
            self._mouse_down = (ms, x, y, button)
            self._event_times.append(ms)
        elif kind is EventKind.MOUSE_UP and event.x is not None:
            self._rel_ms(event)
            if self._mouse_down is None:
                return
            ms, x, y, button = self._mouse_down
            self._mouse_down = None
            ux, uy = self._rel_pt(event)
            if max(abs(ux - x), abs(uy - y)) <= _CLICK_TOLERANCE_PX:
                self._acts.append(MouseAct("click", ms, x, y, button))
            else:
                self._acts.append(MouseAct("drag", ms, x, y, button, to=(ux, uy)))
        elif kind is EventKind.SCROLL and event.x is not None:
            ms = self._rel_ms(event)
            x, y = self._rel_pt(event)
            self._acts.append(MouseAct("scroll", ms, x, y, dy=event.dy))
            self._event_times.append(ms)

    def event_times_ms(self) -> list[int]:
        return sorted(self._event_times)

    def finish(self) -> tuple[list[KeyHold], list[MouseAct]]:
        holds = list(self._holds)
        for key, start in self._held.items():     # 停止時還按著的鍵
            holds.append(KeyHold(key, start, self._last_ms))
        holds.sort(key=lambda h: h.start_ms)
        return holds, list(self._acts)


def _at_or_before(times: list[int], t: int) -> int | None:
    i = bisect.bisect_right(times, t) - 1
    return i if i >= 0 else None


def _sec(ms: int) -> str:
    return f"{ms / 1000:.2f}s"


def format_timeline(holds: list[KeyHold], mouse: list[MouseAct],
                    dots: list[tuple[int, tuple[float, float] | None]],
                    frame_ids: list[tuple[int, str]]) -> str:
    """每行一筆事件，附當下（之前最近一張）截圖編號與小地圖黃點座標。"""
    dot_times = [t for t, _ in dots]
    frame_times = [t for t, _ in frame_ids]

    def suffix(t: int) -> str:
        parts = []
        fi = _at_or_before(frame_times, t)
        if fi is not None:
            parts.append(f"[{frame_ids[fi][1]}]")
        di = _at_or_before(dot_times, t)
        dot = dots[di][1] if di is not None else None
        parts.append("黃點(?)" if dot is None else f"黃點({dot[0]:.0f},{dot[1]:.0f})")
        return " ".join(parts)

    rows: list[tuple[int, str]] = []
    for h in holds:
        rows.append((h.start_ms,
                     f"{_sec(h.start_ms)}–{_sec(h.end_ms)} 按住 {h.key}"
                     f"（{(h.end_ms - h.start_ms) / 1000:.2f}s） {suffix(h.start_ms)}"))
    for m in mouse:
        if m.kind == "click":
            text = f"{_sec(m.t_ms)} 點擊 {m.button} ({m.x},{m.y})"
        elif m.kind == "drag":
            text = f"{_sec(m.t_ms)} 拖曳 {m.button} ({m.x},{m.y})→({m.to[0]},{m.to[1]})"
        else:
            text = f"{_sec(m.t_ms)} 捲動 dy={m.dy} ({m.x},{m.y})"
        rows.append((m.t_ms, f"{text} {suffix(m.t_ms)}"))
    rows.sort(key=lambda r: r[0])
    return "\n".join(text for _, text in rows)
