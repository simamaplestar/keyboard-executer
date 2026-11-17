"""Bounded background capture/OCR/AI workers. This module never sends input."""
from dataclasses import dataclass
import hashlib
import logging
import threading
import time

import numpy as np
from keyboard_executor.core.ai.sequence_recognizer import SequenceReading, SequenceSample
from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.sequence_input import SequenceRound, TERMINAL
from keyboard_executor.core.sequence_input_config import (
    normalize_prompt, SUBMIT_CUTOFF_SEC, CONFIRM_CUTOFF_SEC, TOTAL_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


def geometry(win):
    return win.x, win.y, win.width, win.height


def capture_region(platform, win, region):
    wm, cap = platform.window_manager, platform.screen_capture
    fresh = wm.refresh(win)
    # 偵測不要求前景：視窗在背景但可見時 mss 仍取得到畫面，
    # 輸入安全由 submitter 的前景與幾何檢查把關。
    if fresh is None or fresh.width <= 0 or fresh.height <= 0:
        return None
    if fresh.x <= -30000 and fresh.y <= -30000:
        return None  # Windows 最小化哨兵座標：略過本幀，不當作設定錯誤
    x, y, w, h = region
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > fresh.width or y+h > fresh.height:
        raise ValueError("圖片順序輸入區域超出視窗，請重新框選")
    scale = cap.scale_factor()
    image = cap.capture(Rect(round((fresh.x+x)*scale), round((fresh.y+y)*scale), round(w*scale), round(h*scale)))
    after = wm.refresh(win)
    if after is None or geometry(after) != geometry(fresh):
        return None
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError("圖片順序輸入擷取失敗")
    return image.copy()


@dataclass(frozen=True)
class SequenceSnapshot:
    round_id: int | None
    phase: str
    answer: str | None
    deadline: float | None
    failure: str | None
    window_geometry: tuple[int, int, int, int] | None = None

    @property
    def prepare_deadline(self):
        return None if self.deadline is None else self.deadline - TOTAL_TIMEOUT_SEC + SUBMIT_CUTOFF_SEC

    @property
    def confirm_deadline(self):
        return None if self.deadline is None else self.deadline - TOTAL_TIMEOUT_SEC + CONFIRM_CUTOFF_SEC


class SequenceWatcher:
    def __init__(self, platform, config, recognizer, stop_event, on_progress=None, *, clock=time.monotonic):
        self._platform, self._config, self._recognizer = platform, config, recognizer
        self._stop, self._progress, self._clock = stop_event, on_progress, clock
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self.requested = threading.Event()
        self._window = None
        self._round = None
        self._round_geometry = None
        self._generation = 0
        self._serial = 0
        self._round_serial = 0
        self._next_capture = 0.0
        self._capture_busy = self._ocr_busy = self._ai_busy = False
        self._prompt_pending = None
        self._samples = []
        self._last_prompt = None
        self._ocr_cache = None
        self._notified_failure = False
        self._release_required = False
        self._input_released_round = None

    def _notify(self, text):
        message = f"圖片順序輸入：{text}"
        logger.info(message)
        if self._progress:
            try:
                self._progress({"kind": "notify", "message": message})
            except Exception:
                logger.exception("圖片順序輸入日誌回呼失敗")

    def _aborted(self, generation=None):
        return (self._closed.is_set() or self._stop.is_set()
                or generation is not None and generation != self._generation)

    def require_input_release(self):
        with self._lock:
            self._release_required = True
            self._input_released_round = None

    def acknowledge_pause(self, round_id):
        fresh = self._platform.window_manager.refresh(self._window)
        with self._lock:
            if self._round:
                self._round.check_time(self._clock())
            snap = self.snapshot()
            if (self._aborted() or round_id is None or snap.round_id != round_id
                    or snap.phase not in {'COLLECTING', 'READY'} or fresh is None
                    or geometry(fresh) != snap.window_geometry):
                return False
            self._input_released_round = round_id
            return True

    def resume_allowed(self, round_id, deadline):
        with self._lock:
            return (not self._aborted() and self._clock() < deadline
                    and not self.requested.is_set() and self._round is None
                    and self._round_serial == round_id)

    def start(self, win):
        with self._lock:
            if self._window is not None or self._aborted():
                return
            self._window = win
        def supervise():
            while not self._aborted():
                self.tick()
                self._closed.wait(.05)
        threading.Thread(target=supervise, name="sequence-watch", daemon=True).start()
        logger.info('圖片順序輸入：監看已啟動，每秒 OCR 檢查，等待提示出現；提示區域=%s（舊版設定）；18秒準備／20秒確認／30秒驗證上限',
                    self._config.prompt_region)

    def close(self):
        self._closed.set()
        with self._lock:
            self._generation += 1
            self._samples.clear()
            self._prompt_pending = None
            if self._round:
                self._round.stop()

    def snapshot(self):
        with self._lock:
            r = self._round
            if r:
                r.check_time(self._clock())
            return SequenceSnapshot(r.round_id, r.phase, r.answer, r.deadline, r.failure, self._round_geometry) if r else SequenceSnapshot(None, "WATCHING", None, None, None)

    def fail(self, reason):
        with self._lock:
            if self._round:
                self._round.fail(reason)
            notify = not self._notified_failure
            self._notified_failure = True
            self._stop.set()
        if notify:
            self._notify(reason)

    def _spawn(self, name, job):
        threading.Thread(target=job, name=name, daemon=True).start()

    def tick(self):
        failure = None
        with self._lock:
            if self._aborted() or self._window is None:
                return
            if self._round:
                self._round.check_time(self._clock())
                if self._round.phase == "FAILED":
                    failure = self._round.failure
                elif self._round.phase in TERMINAL:
                    return
            if failure is None:
                generation = self._generation
                if not self._capture_busy and self._clock() >= self._next_capture:
                    self._next_capture = self._clock() + 1.0
                    self._capture_busy = True
                    self._spawn("sequence-capture", lambda: self._capture(generation))
                if not self._ocr_busy and self._prompt_pending is not None:
                    frame, self._prompt_pending = self._prompt_pending, None
                    self._ocr_busy = True
                    self._spawn("sequence-ocr", lambda: self._ocr(generation, frame))
                if (not self._ai_busy and self._samples and self._round
                        and self._round.phase in {'COLLECTING', 'READY', 'SUBMITTING'}
                        and (not self._release_required
                             or self._input_released_round == self._round.round_id)):
                    batch, self._samples = self._samples, []
                    rid = self._round.round_id
                    self._ai_busy = True
                    self._spawn("sequence-ai", lambda: self._recognize(generation, rid, batch))
        if failure:
            self.fail(failure)

    def _capture(self, generation):
        try:
            stamp = self._clock()
            before = self._platform.window_manager.refresh(self._window)
            prompt = capture_region(self._platform, self._window, self._config.prompt_region)
            with self._lock:
                active = self._round is not None
            image = capture_region(self._platform, self._window, self._config.image_region) if active else None
            after = self._platform.window_manager.refresh(self._window)
            valid = (prompt is not None and before is not None and after is not None
                     and geometry(before) == geometry(after))
            fingerprint = hashlib.sha256(image.tobytes() + str(image.shape).encode()).hexdigest() if image is not None else None
            with self._lock:
                if self._aborted(generation):
                    return
                if (not valid or active and image is None
                        or self._round and geometry(after) != self._round_geometry):
                    if self._round:
                        self._round.fail("目標視窗不可確認，已停止")
                    return
                self._serial += 1
                serial = self._serial
                self._prompt_pending = (serial, stamp, prompt, geometry(after))
                if self._round and image is not None and self._round.register(serial, fingerprint, stamp):
                    self._samples.append(SequenceSample(serial, image))
        except Exception as exc:
            if not self._aborted(generation):
                self.fail(f"擷取失敗：{exc}")
        finally:
            with self._lock:
                self._capture_busy = False
            close = getattr(self._platform.screen_capture, "close_current_thread", None)
            if close:
                close()

    def _ocr(self, generation, frame):
        serial, stamp, image, geo = frame
        triggered = False
        try:
            cached = self._ocr_cache
            if cached is not None and np.array_equal(image, cached[0]):
                boxes = cached[1]
            else:
                boxes = self._platform.ocr_engine.recognize(image)
            present = normalize_prompt(self._config.prompt_text) in normalize_prompt("".join(b.text for b in boxes))
            fresh = self._platform.window_manager.refresh(self._window)
            frame_valid = fresh is not None and geometry(fresh) == geo
            # 確認後的消失判定只信任前景畫面：背景或被遮擋時
            # mss 取到的不是遊戲像素，不能當作提示已消失。
            foreground = fresh is not None and fresh.is_active
            with self._lock:
                if self._aborted(generation):
                    return
                if not frame_valid or self._round and geo != self._round_geometry:
                    self._last_prompt = None
                    self._ocr_cache = None
                    if self._round:
                        self._round.fail("OCR 完成時目標視窗已改變，已停止")
                    return
                self._ocr_cache = (image, boxes) if boxes else None
                self._last_prompt = (serial, stamp, present, geo)
                if self._round is None and present:
                    self._round_serial += 1
                    self._round = SequenceRound(self._round_serial, stamp)
                    self._round_geometry = geo
                    self._round.check_time(self._clock())
                    self.requested.set()
                    self._next_capture = 0.0
                    triggered = True
                elif self._round:
                    r = self._round
                    if r.phase == "VERIFYING":
                        r.observe_absence(stamp, self._clock(), valid=foreground, absent=not present)
                    elif r.phase in {"COLLECTING", "READY", "SUBMITTING"} and not present:
                        r.fail("確認前提示消失，停止後續輸入")
            if triggered:
                self._notify("偵測到提示：18 秒前準備輸入、20 秒前確認；驗證消失總上限 30 秒")
        except Exception as exc:
            if not self._aborted(generation):
                self.fail(f"提示文字辨識失敗：{exc}")
        finally:
            with self._lock:
                self._ocr_busy = False

    def _recognize(self, generation, rid, batch):
        started = self._clock()
        try:
            def aborted():
                snap = self.snapshot()
                return (self._aborted(generation) or snap.round_id != rid
                        or snap.phase in TERMINAL | {'VERIFYING'} or self._clock() >= snap.confirm_deadline)
            try:
                readings = self._recognizer.recognize(batch, should_abort=aborted)
            except ValueError:
                readings = [SequenceReading(s.sample_id, None, None) for s in batch]
            with self._lock:
                if self._aborted(generation) or self._round is None or self._round.round_id != rid:
                    return
                # Missing rows from a custom adapter are also unknown, never guessed.
                rows = {r.sample_id: r for r in readings}
                for sample in batch:
                    row = rows.get(sample.sample_id, SequenceReading(sample.sample_id, None, None))
                    self._round.apply(rid, row.sample_id, row.index, row.char, self._clock())
                indices = self._round.collected_indices
                remaining = max(0, self._round.deadline - self._clock())
                phase = self._round.phase
            self._notify(f"回合 {rid}／{phase}；已收集編號：{','.join(map(str, indices)) or '無'}；"
                         f"AI 耗時 {self._clock()-started:.1f} 秒，剩餘 {remaining:.1f} 秒")
        except Exception as exc:
            if not aborted():
                self.fail(f"AI 辨識失敗：{exc}")
        finally:
            with self._lock:
                self._ai_busy = False

    def wait_ready(self):
        while not self._aborted():
            snap = self.snapshot()
            if snap.phase != "COLLECTING":
                return snap
            self.tick()
            self._stop.wait(.05)
        return self.snapshot()

    def validate_prompt(self, round_id):
        with self._lock:
            target_serial = self._serial
            self._next_capture = 0.0
        while not self._aborted():
            self.tick()
            with self._lock:
                if not self._round or self._round.round_id != round_id or self._round.phase != "READY":
                    return False
                last = self._last_prompt
                if last and last[0] > target_serial:
                    return last[2]
            self._stop.wait(.05)
        return False

    def begin_submit(self, round_id):
        with self._lock:
            if (not self._aborted() and self._round and self._round.round_id == round_id
                    and self._round.begin_submit(self._clock())):
                return self._round.answer
        return None

    def mark_clicked(self, round_id):
        with self._lock:
            if self._round and self._round.round_id == round_id:
                self._round.mark_clicked(self._clock())
                self._next_capture = self._clock() + 1.0

    def wait_complete(self, round_id):
        while not self._aborted():
            self.tick()
            snap = self.snapshot()
            if snap.round_id != round_id:
                return False
            if snap.phase in TERMINAL:
                if snap.phase != "SUCCEEDED":
                    return False
                fresh = self._platform.window_manager.refresh(self._window)
                if (self._aborted() or fresh is None or not fresh.is_active
                        or geometry(fresh) != snap.window_geometry or self._clock() >= snap.deadline):
                    self.fail("接續腳本前視窗失效或超時，已停止")
                    return False
                return True
            self._stop.wait(.05)
        return False

    def rearm(self, round_id):
        with self._lock:
            if not self._round or self._round.round_id != round_id or self._round.phase != "SUCCEEDED":
                return
            elapsed = self._clock() - self._round.started_at
            deadline, expected = self._round.deadline, self._round_geometry
        self._notify(f"提示已消失，耗時 {elapsed:.1f} 秒，準備接續腳本")
        # Progress callbacks may block or switch focus. Check after all callbacks
        # and before returning input ownership to Player.
        fresh = self._platform.window_manager.refresh(self._window)
        if (self._aborted() or fresh is None or not fresh.is_active
                or geometry(fresh) != expected or self._clock() >= deadline):
            self.fail("接續腳本前視窗失效或超時，已停止")
            return
        with self._lock:
            self._generation += 1
            self._round = None
            self._round_geometry = None
            self._samples.clear()
            self._prompt_pending = self._last_prompt = self._ocr_cache = None
            self.requested.clear()
            self._input_released_round = None
            self._next_capture = self._clock() + 1.0
