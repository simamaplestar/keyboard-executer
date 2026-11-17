"""AI 示範錄製的截圖取樣（無 Qt）：背景執行緒每 500ms 截一次目標視窗並讀小地圖黃點。"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from keyboard_executor.app.route_recorder import read_dot_with_image
from keyboard_executor.core.ai_demo.frames import Frame, make_thumb, write_png
from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.minimap import find_player_dot

logger = logging.getLogger(__name__)


def read_dot(capture, window_manager, win, region) -> tuple[float, float] | None:
    """只截小地圖範圍讀黃點（視窗相對座標）；找不到回 None。"""
    return read_dot_with_image(capture, window_manager, win, region)[0]


class FrameSampler:
    """frames() 依時間排序；單次擷取失敗只記警告並略過該張。"""

    def __init__(self, capture_factory, window_manager, win, minimap_region, out_dir: Path,
                 prefix: str, *, t0_ms: int, interval: float = 0.5, clock=time.monotonic):
        self._capture_factory = capture_factory
        self._wm = window_manager
        self._win = win
        self._region = tuple(minimap_region)
        self._out_dir = Path(out_dir)
        self._prefix = prefix
        self._t0_ms = t0_ms
        self._interval = interval
        self._clock = clock
        self._frames: list[Frame] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def frames(self) -> list[Frame]:
        with self._lock:
            return list(self._frames)

    def sample_once(self, capture) -> Frame | None:
        now_ms = int(self._clock() * 1000)
        try:
            win = self._wm.refresh(self._win) or self._win
            scale = capture.scale_factor()
            image = capture.capture(Rect(round(win.x * scale), round(win.y * scale),
                                         round(win.width * scale), round(win.height * scale)))
            rx, ry, rw, rh = self._region
            sub = image[round(ry * scale):round((ry + rh) * scale),
                        round(rx * scale):round((rx + rw) * scale)]
            dot = find_player_dot(sub, scale) if sub.size else None
            pos = None if dot is None else (rx + dot[0] / scale, ry + dot[1] / scale)
            with self._lock:
                frame_id = f"{self._prefix}{len(self._frames) + 1}"
            self._out_dir.mkdir(parents=True, exist_ok=True)
            path = self._out_dir / f"{frame_id}.png"
            write_png(path, image)
        except Exception as exc:          # 擷取偶發失敗：略過這一張
            logger.warning("示範錄製截圖失敗：%s", exc)
            return None
        frame = Frame(id=frame_id, t_ms=max(0, now_ms - self._t0_ms), path=path,
                      size=(image.shape[1], image.shape[0]), dot=pos, thumb=make_thumb(image))
        with self._lock:
            self._frames.append(frame)
        return frame

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ai-demo-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> list[Frame]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        return self.frames()

    def _run(self) -> None:
        capture = self._capture_factory()
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                self.sample_once(capture)
                self._stop.wait(max(0.0, self._interval - (time.monotonic() - started)))
        finally:
            close = getattr(capture, "close_current_thread", None)
            if close is not None:
                close()
