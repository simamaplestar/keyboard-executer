"""OCR-gated, bounded full-panel monitoring. Workers never issue native input."""
from collections import deque
import logging
import threading
import time
from keyboard_executor.core.ai.provider import AiAborted
from keyboard_executor.core.ai.sequence_recognizer import SequenceSample
from keyboard_executor.core.sequence_input import TERMINAL
from keyboard_executor.core.sequence_panel import PanelFrame, PanelReading, PanelRound
from keyboard_executor.core.sequence_panel_vision import analyze_panel, crop_fingerprint

# 同一張輪播圖跨帧的 ahash 漢明距離上限（實測同圖 ≲25、不同圖 ≳100）
_GROUP_DISTANCE = 30
# 實機 2026-10-30：一次 AI 請求卡住超過 18 秒，整回合失敗。
# 同時最多 3 個 AI 請求；三個字都定案後，還在跑超過 6 秒的請求直接放棄。
_AI_PARALLEL = 3
_AI_STALL_SEC = 6.0


class _ImageGroup:
    """同一張輪播圖的跨帧群組：本地 OCR 讀不出編號時，用 AI 編號後援投票解析。"""
    __slots__ = ('fp', 'index', 'digit_votes', 'blocked')

    def __init__(self, fp):
        self.fp = fp
        self.index = None        # 本地 OCR 或 AI 後援解析出的編號
        self.digit_votes = {}    # AI 後援：digit -> 票數
        self.blocked = False     # 編號與其他群組衝突，永不解析
from keyboard_executor.core.sequence_prompt import classify_sequence_prompt
from keyboard_executor.core.sequence_watcher import SequenceSnapshot, capture_region, geometry

logger = logging.getLogger(__name__)


class PanelWatcher:
    def __init__(self, platform, config, recognizer, stop_event, on_progress=None, *,
                 clock=time.monotonic, on_detected=None, discord_configured=False, vision=None,
                 on_outcome=None):
        self._platform, self._config, self._recognizer = platform, config, recognizer
        # 本地 CV 定位（輸入框／確認鈕／輪播與編號）；測試可注入假的 vision。
        self._vision = vision or analyze_panel
        self._stop, self._progress, self._clock = stop_event, on_progress, clock
        self._on_detected = on_detected
        self._on_outcome = on_outcome   # (round_id, 成功?, 訊息) → Discord 結果通知
        self._discord_configured = bool(discord_configured)
        self._release_required = False
        self._input_released_round = None
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self.requested = threading.Event()
        self._window = self._round = None
        self._generation = self._serial = self._round_serial = 0
        self._last_ocr_serial = 0
        self._next_capture = 0.0
        self._capture_busy = self._ocr_busy = False
        self._report_busy = self._notice_busy = False
        self._ocr_pending, self._ai_pending = deque(), deque()
        self._ai_tokens = {}   # token -> (開始時間, 取樣編號)
        self._validated_target = None
        self._notified_failure = False
        self._groups = []

    def _spawn(self, name, job):
        threading.Thread(target=job, name=name, daemon=True).start()

    def _aborted(self, generation=None):
        return (self._closed.is_set() or self._stop.is_set()
                or generation is not None and generation != self._generation)

    @property
    def _ai_busy(self):
        return len(self._ai_tokens) >= _AI_PARALLEL

    @property
    def _ai_running(self):
        return bool(self._ai_tokens)

    def _cancel_ai(self):
        for token in self._ai_tokens:
            token[2].set()

    def _outcome(self, round_id, ok, message):
        if self._on_outcome is None or round_id is None:
            return
        def send():
            try:
                self._on_outcome(round_id, ok, message)
            except Exception:
                logger.warning('圖片順序輸入結果通知失敗')
        self._spawn('panel-outcome', send)

    def _report(self, message):
        # Progress/UI callbacks cannot hold the watchdog or any pipeline worker.
        with self._lock:
            if self._report_busy:
                return
            self._report_busy = True
        def send():
            try:
                logger.info('圖片順序輸入：%s', message)
                if self._progress:
                    self._progress(dict(kind='notify', message=f'圖片順序輸入：{message}'))
            except Exception:
                logger.warning('圖片順序輸入狀態回呼失敗')
            finally:
                with self._lock:
                    self._report_busy = False
        self._spawn('panel-progress', send)

    def _notice(self, rid, generation):
        with self._lock:
            if self._on_detected is None or self._notice_busy or self._aborted(generation):
                return
            self._notice_busy = True
        def send():
            try:
                if not self._aborted(generation):
                    self._on_detected(rid)
            except Exception:
                logger.warning('面板通知回呼失敗')
            finally:
                with self._lock:
                    self._notice_busy = False
        self._spawn('panel-detected', send)

    def require_input_release(self):
        with self._lock:
            self._release_required = True
            self._input_released_round = None

    def acknowledge_pause(self, round_id):
        fresh = self._platform.window_manager.refresh(self._window)
        with self._lock:
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
                self._closed.wait(.02)
        self._spawn('panel-watch', supervise)
        logger.info('圖片順序輸入：監看已啟動，每秒 OCR 檢查，等待提示出現；區域=%s；Discord=%s；18秒準備／20秒確認／30秒驗證上限',
                    self._config.panel_region, '已設定' if self._discord_configured else '未設定')

    def close(self):
        self._closed.set()
        with self._lock:
            self._generation += 1
            self._ocr_pending.clear()
            self._ai_pending.clear()
            self._cancel_ai()
            if self._round:
                self._round.base.stop()
            self._validated_target = None

    def fail(self, reason):
        with self._lock:
            rid = self._round.base.round_id if self._round else None
            if self._round:
                self._round.base.fail(reason)
            self._stop.set()
            self._cancel_ai()
            notify = not self._notified_failure
            self._notified_failure = True
        if notify:
            self._report(reason)
            self._outcome(rid, False, reason)

    def snapshot(self):
        with self._lock:
            if self._round is None:
                return SequenceSnapshot(None, 'WATCHING', None, None, None)
            r = self._round.base
            r.check_time(self._clock())
            phase = r.phase
            if phase == 'READY' and self._round.target(self._clock()) is None:
                phase = 'COLLECTING'
            return SequenceSnapshot(r.round_id, phase, r.answer, r.deadline, r.failure, self._round.geometry)

    def tick(self):
        failure = None
        with self._lock:
            if self._aborted() or self._window is None:
                return
            now = self._clock()
            if self._round:
                self._round.base.check_time(now)
                if self._round.base.phase == 'FAILED':
                    failure = self._round.base.failure
                elif self._round.base.phase in TERMINAL:
                    return
            if failure is None and any(not token[2].is_set() and now >= token[3]
                                       for token in self._ai_tokens):
                failure = 'AI 面板辨識逾時，已停止'
            if failure is None and self._round and self._round.base.frozen:
                # 三個字都定案了：不再等卡住的請求，放棄它們的取樣。
                for token, (started, ids) in list(self._ai_tokens.items()):
                    if not token[2].is_set() and now - started >= _AI_STALL_SEC:
                        token[2].set()
                        self._round.base.abandon(ids, now)
                        logger.info('圖片順序輸入：AI 請求 %.1f 秒未回應，三個字已定案，放棄該請求',
                                    now - started)
            if failure is None:
                generation = self._generation
                if not self._capture_busy and now >= self._next_capture:
                    self._next_capture = now + 1.0
                    self._capture_busy = True
                    self._spawn('panel-capture', lambda: self._capture(generation))
                if not self._ocr_busy and self._ocr_pending:
                    frame = self._ocr_pending.popleft()
                    self._ocr_busy = True
                    self._spawn('panel-ocr', lambda: self._ocr(generation, frame))
                while (not self._ai_busy and self._ai_pending and self._round
                        and (not self._release_required
                             or self._input_released_round == self._round.base.round_id)
                        and self._round.base.phase in {'COLLECTING', 'READY', 'SUBMITTING'}):
                    batch = [self._ai_pending.popleft() for _ in range(min(3, len(self._ai_pending)))]
                    token = (generation, self._round.base.round_id, threading.Event(),
                             self._round.base.confirm_deadline)
                    self._ai_tokens[token] = (now, [f.sample_id for f in batch])
                    self._spawn('panel-ai', lambda token=token, batch=batch: self._recognize(token, batch))
        if failure:
            self.fail(failure)

    def _enqueue(self, queue, frame):
        if len(self._ocr_pending) + len(self._ai_pending) >= 30:
            if self._round:
                self._round.base.fail('面板待處理影像超過上限，已停止')
            return
        queue.append(frame)

    def _capture(self, generation):
        try:
            stamp = self._clock()
            wm = self._platform.window_manager
            before = wm.refresh(self._window)
            image = capture_region(self._platform, self._window, self._config.panel_region)
            after = wm.refresh(self._window)
            valid = (image is not None and before is not None and after is not None
                     and geometry(before) == geometry(after))
            with self._lock:
                if self._aborted(generation):
                    return
                if not valid or self._round and geometry(after) != self._round.geometry:
                    if self._round:
                        self._round.base.fail('目標視窗失效或已移動，已停止')
                    return
                self._serial += 1
                frame = PanelFrame(self._serial, stamp, image, geometry(after), generation)
                if self._round is None:
                    self._ocr_pending.clear()
                self._enqueue(self._ocr_pending, frame)
        except Exception:
            if not self._aborted(generation):
                self.fail('完整面板擷取失敗，請確認框選範圍')
        finally:
            with self._lock:
                self._capture_busy = False
            close = getattr(self._platform.screen_capture, 'close_current_thread', None)
            if close:
                close()

    def _ocr(self, generation, frame):
        triggered = None
        try:
            boxes = self._platform.ocr_engine.recognize(frame.image)
            state = classify_sequence_prompt(boxes)
            fresh = self._platform.window_manager.refresh(self._window)
            valid = fresh is not None and geometry(fresh) == frame.window_geometry
            # 消失判定只信任前景畫面（同 SequenceWatcher 的 VERIFYING 規則）。
            foreground = fresh is not None and fresh.is_active
            with self._lock:
                if self._aborted(generation):
                    return
                if not valid:
                    if self._round:
                        self._round.base.fail('OCR 完成時目標視窗已改變')
                    return
                self._last_ocr_serial = max(self._last_ocr_serial, frame.sample_id)
                if self._round is None and state == 'present':
                    self._round_serial += 1
                    self._groups = []
                    self._round = PanelRound(self._round_serial, frame, self._config.panel_region)
                    self._round.base.check_time(self._clock())
                    self.requested.set()
                    triggered = self._round_serial
                if self._round:
                    if self._round.base.phase == 'VERIFYING' and not foreground:
                        state = 'unknown'
                    self._round.observe_prompt(frame, state, self._clock())
                    if (state == 'present' and self._round.base.phase in {'COLLECTING', 'READY', 'SUBMITTING'}):
                        self._round.register(frame)
                        if self._round.base.phase not in TERMINAL:
                            self._enqueue(self._ai_pending, frame)
            if triggered is not None:
                self._notice(triggered, generation)
                self._report('OCR 偵測到順序輸入提示，正在暫停腳本（18秒準備／20秒確認／30秒驗證上限）')
        except Exception:
            if not self._aborted(generation):
                self.fail('面板 OCR 辨識失敗，未轉交 AI 猜測')
        finally:
            with self._lock:
                self._ocr_busy = False

    def _recognize(self, token, batch):
        generation, rid, cancelled, expires = token
        def aborted():
            with self._lock:
                if (self._aborted(generation) or cancelled.is_set()
                        or self._round is None or self._round.base.round_id != rid):
                    return True
                now = self._clock()
                # Preparation ends at 18s. An already-started submission can
                # still receive safety/layout observations until 20s, never later.
                self._round.base.check_time(now)
                return now >= expires or self._round.base.phase in TERMINAL | {'VERIFYING'}
        try:
            if aborted():
                return
            # 本地 CV 先做：輸入框／確認鈕定位、輪播裁切與編號 OCR。
            # 所有小圖都送 AI 辨識字元；讀不出本地編號的小圖另外送 AI 編號後援，
            # 同一張圖（ahash 群組）累積 2 票且嚴格多數才解析編號。
            visions = {}
            ai_samples = []
            digit_samples = []
            began = time.monotonic()
            for frame in batch:
                if aborted():
                    return
                vision = self._vision(frame.image, self._platform.ocr_engine.recognize)
                visions[frame.sample_id] = vision
                if vision.crop is None:
                    continue
                ai_samples.append(SequenceSample(frame.sample_id, vision.crop))
                if vision.index is None:
                    digit_samples.append(SequenceSample(frame.sample_id, vision.crop))
            vision_sec = time.monotonic() - began
            # 字元與編號後援兩個 AI 請求同時送，不要排隊。
            digits, digit_error, digit_sec = {}, [], [0.0]
            recognize_digits = getattr(self._recognizer, 'recognize_digits', None)
            digit_worker = None
            if digit_samples and recognize_digits is not None:
                def ask_digits():
                    start = time.monotonic()
                    try:
                        digits.update({row.sample_id: row.digit
                                       for row in recognize_digits(digit_samples, should_abort=aborted)})
                    except ValueError:
                        pass
                    except BaseException as exc:
                        digit_error.append(exc)
                    finally:
                        digit_sec[0] = time.monotonic() - start
                digit_worker = threading.Thread(target=ask_digits, name='panel-ai-digit', daemon=True)
                digit_worker.start()
            start = time.monotonic()
            try:
                rows = (self._recognizer.recognize(ai_samples, should_abort=aborted)
                        if ai_samples else [])
            except ValueError:
                rows = []
            finally:
                char_sec = time.monotonic() - start
                if digit_worker is not None:
                    digit_worker.join()
            logger.info('圖片順序輸入：%d 張取樣, 本地定位 %.2f 秒, AI 字元 %.2f 秒, AI 編號 %.2f 秒 (%d 張)',
                        len(batch), vision_sec, char_sec, digit_sec[0], len(digit_samples))
            if digit_error:
                raise digit_error[0]
            chars = {row.sample_id: row.char for row in rows}
            # Native window queries can block; never hold the watchdog lock here.
            fresh = self._platform.window_manager.refresh(self._window) if not aborted() else None
            with self._lock:
                if aborted():
                    if not self._aborted(generation) and not cancelled.is_set() and self._clock() >= expires:
                        self.fail(self._round.base.failure or 'AI 面板辨識逾時，已停止')
                    return
                if fresh is None or geometry(fresh) != self._round.geometry:
                    self._round.base.fail('AI 完成時目標視窗已改變')
                    return
                for frame in batch:
                    vision = visions[frame.sample_id]
                    index = vision.index
                    if vision.crop is not None:
                        index = self._group_index(vision, digits.get(frame.sample_id))
                    reading = PanelReading(frame.sample_id, 'present', index,
                                           chars.get(frame.sample_id), vision.input_box,
                                           vision.confirm_box)
                    self._round.apply(frame, reading, self._clock())
        except AiAborted:
            if not aborted():
                self.fail('AI 面板辨識中止，已停止')
        except Exception:
            logger.exception('面板 AI 辨識未預期失敗')
            if not aborted():
                self.fail('AI 面板辨識失敗，已停止')
        finally:
            with self._lock:
                # A cooperative provider may raise at exactly its deadline before
                # the supervisor ticks. Do not erase that timeout with the token.
                if (not self._aborted(generation) and not cancelled.is_set()
                        and self._round is not None and self._round.base.round_id == rid):
                    self._round.base.check_time(self._clock())
                    if self._round.base.phase == 'FAILED':
                        self.fail(self._round.base.failure)
                    elif (self._round.base.phase not in TERMINAL | {'VERIFYING'}
                          and self._clock() >= expires):
                        self.fail('AI 面板辨識逾時，已停止')
                self._ai_tokens.pop(token, None)

    def _group_index(self, vision, ai_digit):
        """同一張輪播圖（ahash 群組）的編號解析：本地 OCR 直接定；否則 AI 後援
        累積 2 票且嚴格多數、且不與其他群組編號衝突才採用；衝突永不解析。"""
        fp = crop_fingerprint(vision.crop)
        group = None
        for candidate in self._groups:
            if bin(candidate.fp ^ fp).count('1') <= _GROUP_DISTANCE:
                group = candidate
                break
        if group is None:
            group = _ImageGroup(fp)
            self._groups.append(group)
        if group.blocked:
            return None
        if vision.index is not None:
            # 本地 OCR 編號近乎必對，永遠直接採用；只在群組尚未有編號時
            # 順手登記，供同圖但本地讀不出的兄弟帧沿用。
            if group.index is None:
                group.index = vision.index
            return vision.index
        if group.index is not None:
            return group.index
        if ai_digit in (1, 2, 3):
            group.digit_votes[ai_digit] = group.digit_votes.get(ai_digit, 0) + 1
            ranked = sorted(group.digit_votes.items(), key=lambda kv: kv[1], reverse=True)
            top, votes = ranked[0]
            if votes >= 2 and (len(ranked) == 1 or votes > ranked[1][1]):
                if any(other is not group and other.index == top for other in self._groups):
                    group.blocked = True  # 編號與別張圖衝突：可能是分組誤判，不猜
                    return None
                group.index = top
        return group.index

    def wait_ready(self):
        while not self._aborted():
            snap = self.snapshot()
            if snap.phase != 'COLLECTING':
                return snap
            self.tick()
            self._stop.wait(.02)
        return self.snapshot()

    def validate_prompt(self, round_id):
        with self._lock:
            serial = self._serial
            self._next_capture = 0.0
            self._validated_target = None
        while not self._aborted():
            self.tick()
            with self._lock:
                if (not self._round or self._round.base.round_id != round_id
                        or self._round.base.phase != 'READY'):
                    return False
                target = self._round.target(self._clock())
                if target and target.sample_id > serial and self._last_ocr_serial >= target.sample_id:
                    self._validated_target = target
                    return True
            self._stop.wait(.02)
        return False

    def submission_target(self, round_id):
        with self._lock:
            if self._aborted() or not self._round or self._round.base.round_id != round_id:
                raise ValueError('面板回合已失效')
            target = self._round.target(self._clock())
            pinned = self._validated_target or target
            if target is None or pinned is None or not 0 <= self._clock()-pinned.captured_at <= 2:
                raise ValueError('無有效且穩定的面板位置')
            return pinned

    def begin_submit(self, round_id):
        with self._lock:
            if (not self._aborted() and self._round and self._round.base.round_id == round_id
                    and self._round.begin_submit(self._clock(), self._validated_target)):
                return self._round.base.answer
        return None

    def mark_clicked(self, round_id):
        with self._lock:
            if self._round and self._round.base.round_id == round_id:
                self._round.base.mark_clicked(self._clock())
                self._ai_pending.clear()
                self._ocr_pending.clear()
                self._cancel_ai()
                self._next_capture = self._clock()+1

    def _can_resume(self):
        fresh = self._platform.window_manager.refresh(self._window)
        return (not self._aborted() and self._round is not None and fresh is not None
                and fresh.is_active and geometry(fresh) == self._round.geometry
                and self._clock() < self._round.base.deadline)

    def wait_complete(self, round_id):
        while not self._aborted():
            self.tick()
            snap = self.snapshot()
            if snap.round_id != round_id:
                return False
            if snap.phase in TERMINAL:
                if snap.phase == 'SUCCEEDED' and self._can_resume():
                    elapsed = self._clock() - self._round.base.started_at if self._round else 0
                    logger.info('圖片順序輸入：已輸入 %s，提示已消失（%.1f 秒）', snap.answer, elapsed)
                    self._outcome(round_id, True,
                                  f'已輸入 {snap.answer}，提示已消失（{elapsed:.0f} 秒）')
                    return True
                self.fail('接續腳本前視窗失效或超時，已停止')
                return False
            self._stop.wait(.02)
        return False

    def rearm(self, round_id):
        with self._lock:
            if not self._round or self._round.base.round_id != round_id or self._round.base.phase != 'SUCCEEDED':
                return
        if not self._can_resume():
            self.fail('接續腳本前視窗失效或超時，已停止')
            return
        with self._lock:
            self._generation += 1
            self._round = self._validated_target = None
            self._groups = []
            self._ocr_pending.clear()
            self._ai_pending.clear()
            self.requested.clear()
            self._input_released_round = None
            self._next_capture = self._clock()+1
        self._report('提示已消失，接續腳本')
