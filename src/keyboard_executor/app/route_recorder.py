"""小地圖路線錄製（無 Qt）：收按鍵事件＋背景讀取黃點，錄完交給 route_learn。"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2

from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.minimap import find_player_dot
from keyboard_executor.core.models import action_from_dict
from keyboard_executor.core.route_learn import (
    DotSample, KeyEvent, learn_route, route_actions, summarize,
)
from keyboard_executor.core.route_map import analyze, describe, patrol_actions
from keyboard_executor.platforms.base import EventKind

logger = logging.getLogger(__name__)

_SAMPLE_SEC = .04


def read_dot_with_image(capture, window_manager, win, region):
    """截小地圖範圍並找黃點；回傳 (視窗相對座標 | None, 小地圖影像)。"""
    win = window_manager.refresh(win) or win
    rx, ry, rw, rh = region
    scale = capture.scale_factor()
    image = capture.capture(Rect(round((win.x + rx) * scale), round((win.y + ry) * scale),
                                 round(rw * scale), round(rh * scale)))
    dot = find_player_dot(image, scale)
    return (None if dot is None else (rx + dot[0] / scale, ry + dot[1] / scale)), image


class RouteEventLog:
    """RecorderSession 的 recorder_factory：只記鍵盤 down/up 與時間（秒）。"""

    def __init__(self, origin=None, mode: str = "simplified"):
        self._events: list[KeyEvent] = []

    def feed(self, event) -> None:
        if event.kind in (EventKind.KEY_DOWN, EventKind.KEY_UP) and event.key:
            self._events.append(KeyEvent(event.timestamp_ms / 1000, event.key,
                                         event.kind is EventKind.KEY_DOWN))

    def finish(self) -> list[KeyEvent]:
        return list(self._events)


class MinimapSampler:
    """背景執行緒定時讀小地圖黃點（視窗相對座標，時鐘與輸入監聽相同）。"""

    def __init__(self, capture_factory, window_manager, win, region, *,
                 clock=time.monotonic, interval=_SAMPLE_SEC):
        self._capture_factory = capture_factory
        self._wm = window_manager
        self._win = win
        self._region = list(region)
        self._clock = clock
        self._interval = interval
        self._samples: list[DotSample] = []
        self._stop = threading.Event()
        self._thread = None
        self.misses = 0
        self.last_image = None          # 最後一張小地圖（給 AI 看地形）

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="minimap-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> list[DotSample]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return list(self._samples)

    def read_once(self, capture):
        pos, self.last_image = read_dot_with_image(capture, self._wm, self._win, self._region)
        return pos

    def _run(self) -> None:
        capture = self._capture_factory()
        try:
            while not self._stop.is_set():
                started = self._clock()
                try:
                    pos = self.read_once(capture)
                except Exception as e:      # 擷取偶發失敗：略過這一次
                    logger.warning("路線錄製讀取小地圖失敗：%s", e)
                    pos = None
                if pos is None:
                    self.misses += 1
                else:
                    self._samples.append(DotSample(started, pos[0], pos[1]))
                self._stop.wait(max(0.0, self._interval - (self._clock() - started)))
        finally:
            close = getattr(capture, "close_current_thread", None)
            if close is not None:
                close()


@dataclass
class RouteResult:
    steps: list
    actions: list               # Action
    summary: str
    analysis: str = ""
    missing: list = field(default_factory=list)
    patrol: bool = False
    sidecar: dict = field(default_factory=dict)


def build_route(events, samples, region, *, jump_key="space", loop_count=100,
                start=None, end=None, replay=False, sweeps=1) -> RouteResult:
    """錄製結果 → 腳本。預設先做小地圖分析，整理成「每層左右掃、換層照錄」的走法；
    找不到打怪平台或指定 replay 時照錄製一步一步重播。"""
    if start is not None:
        samples = [s for s in samples if s.t >= start - .5]
    if end is not None:
        samples = [s for s in samples if s.t <= end + 2.5]
    steps = learn_route(events, samples, jump_key=jump_key)
    model, analysis, missing, raw = None, "", [], None
    try:
        model = analyze(events, samples, steps, region, jump_key=jump_key)
        analysis = describe(model)
    except ValueError as e:
        analysis = f"無法分析地圖：{e}"
    patrol = model is not None and bool(model.cycle) and not replay
    if patrol:
        raw, missing = patrol_actions(model, loop_count=loop_count, sweeps=sweeps)
        floors = len(model.cycle)
        if model.dash and model.lap:
            summary = (f"照錄製中的一圈走：{floors} 層循環，"
                       f"{summarize(model.lap)}")
        else:
            summary = f"整理成 {floors} 個打怪平台循環，每層左右掃 {sweeps} 趟"
        if missing:
            summary += "；沒錄到 " + "、".join(f"平台 {a}→{b}" for a, b in missing) + " 的走法"
    else:
        raw = route_actions(steps, region, jump_key=jump_key, loop_count=loop_count)
        summary = f"照錄製重播 {len(steps)} 步（{summarize(steps)}）"
    actions = [action_from_dict(a) for a in raw]
    sidecar = {
        "analysis": analysis,
        "map": model.to_dict() if model is not None else None,
        "recording": {
            "jump_key": jump_key, "region": list(region),
            "events": [[round(e.t, 3), e.key, e.down] for e in events],
            "samples": [[round(s.t, 3), round(s.x, 2), round(s.y, 2)] for s in samples],
        },
    }
    return RouteResult(steps, actions, summary, analysis, missing, patrol, sidecar)


def minimap_png(image) -> bytes | None:
    if image is None:
        return None
    ok, data = cv2.imencode(".png", image)
    return data.tobytes() if ok else None
