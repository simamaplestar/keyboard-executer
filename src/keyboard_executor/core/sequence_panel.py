"""Immutable observations for OCR-gated full-panel recognition."""
from collections import Counter
from dataclasses import dataclass
import math
import numpy as np
from keyboard_executor.core.sequence_input import SequenceRound, TERMINAL, valid_reading
from keyboard_executor.core.sequence_prompt import PromptState


@dataclass(frozen=True)
class PanelReading:
    sample_id: int
    state: PromptState
    index: int | None
    char: str | None
    input_box: tuple[int, int, int, int] | None
    confirm_box: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class PanelFrame:
    sample_id: int
    captured_at: float
    image: np.ndarray
    window_geometry: tuple[int, int, int, int]
    generation: int


@dataclass(frozen=True)
class PanelTarget:
    round_id: int
    window_geometry: tuple[int, int, int, int]
    input_point: tuple[int, int]
    confirm_point: tuple[int, int]
    captured_at: float
    sample_id: int


def _intersection(a, b):
    if a is None or b is None:
        raise ValueError('未辨識出輸入框或確認按鈕')
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    area = max(0, right-left) * max(0, bottom-top)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area
    if union <= 0 or area / union < .8:
        raise ValueError('面板控制項定位不穩定')
    return left, top, right, bottom


def _inside(lo, hi):
    lower, upper = math.floor(lo)+1, math.ceil(hi)-1
    if lower > upper:
        raise ValueError('控制項太小，無安全點擊位置')
    return min(upper, max(lower, round((lo+hi)/2)))


def resolve_panel_points(first, second, region):
    x, y, width, height = region
    result = []
    for a, b in ((first.input_box, second.input_box), (first.confirm_box, second.confirm_box)):
        l, t, r, bottom = _intersection(a, b)
        if not (0 <= l < r <= 1000 and 0 <= t < bottom <= 1000):
            raise ValueError('控制項超出面板')
        result.append((_inside(x+l*width/1000, x+r*width/1000),
                       _inside(y+t*height/1000, y+bottom*height/1000)))
    return tuple(result)


class PanelRound:
    """Caller serializes mutations. No I/O, threads or input ownership here."""
    def __init__(self, round_id, trigger, panel_region):
        self.base = SequenceRound(round_id, trigger.captured_at)
        self.geometry = trigger.window_geometry
        self.generation = trigger.generation
        self.region = panel_region
        self._frames = {}
        self._applied = set()
        # 同編號字元投票：扭曲字元單次誤讀不應立刻失敗，也不應一票就鎖定。
        self._votes = {1: Counter(), 2: Counter(), 3: Counter()}
        self._locked = {}
        self._latest_prompt = -1
        self._latest_prompt_state = 'unknown'
        self._previous_layout = None
        self._target = None
        self._pinned_target = None
        self._last_ai = -1

    def observe_prompt(self, frame, state, now):
        self.base.check_time(now)
        if self.base.phase in TERMINAL or frame.sample_id <= self._latest_prompt:
            return
        if (frame.generation != self.generation or frame.window_geometry != self.geometry
                or not self.base.started_at <= frame.captured_at <= now):
            self.base.fail('OCR 影像或視窗狀態失效')
            return
        self._latest_prompt = frame.sample_id
        self._latest_prompt_state = state
        if self.base.phase == 'VERIFYING':
            self.base.observe_absence(frame.captured_at, now, valid=state != 'unknown', absent=state == 'absent')
        elif state == 'absent' or state == 'unknown' and self.base.phase == 'SUBMITTING':
            self.base.fail('確認前提示消失或無法確認，已停止')
        if state != 'present':
            self._target = None

    def register(self, frame):
        if (self.base.phase not in {'COLLECTING', 'READY', 'SUBMITTING'}
                or self._latest_prompt_state != 'present' or frame.sample_id != self._latest_prompt
                or frame.sample_id in self._frames):
            return
        if len(self._frames) >= 30:
            self.base.fail('面板取樣超過上限')
            return
        self._frames[frame.sample_id] = frame
        self.base.register(frame.sample_id, f'panel-{frame.generation}-{frame.sample_id}', frame.captured_at)

    def apply(self, frame, reading, now):
        self.base.check_time(now)
        sid = frame.sample_id
        if (self.base.phase in TERMINAL or self.base.phase == 'VERIFYING'
                or self._frames.get(sid) is not frame or sid in self._applied
                or sid != reading.sample_id):
            return
        self._applied.add(sid)
        if reading.state == 'absent':
            self.base.fail('AI 與 OCR 面板判斷不一致')
            return
        if (self.base.phase == 'COLLECTING' and valid_reading(reading.index, reading.char)
                and reading.index not in self._locked):
            char = reading.char.upper()
            votes = self._votes[reading.index]
            votes[char] += 1
            top = votes.most_common(2)
            if top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
                self._locked[reading.index] = char
                self.base.apply(self.base.round_id, sid, reading.index, char, now)
            else:
                self.base.apply(self.base.round_id, sid, None, None, now)
        else:
            self.base.apply(self.base.round_id, sid, None, None, now)
        if sid <= self._last_ai:
            return
        self._last_ai = sid
        previous = self._previous_layout
        if reading.state != 'present' or reading.input_box is None or reading.confirm_box is None:
            self._target = self._previous_layout = None
            if self.base.phase == 'SUBMITTING':
                self.base.fail('輸入期間無法確認面板位置')
            return
        if (self.base.phase == 'SUBMITTING' and self._pinned_target is not None
                and not self._supports_target(self._pinned_target, reading)):
            self.base.fail('控制項已移離原定點擊位置，停止後續輸入')
            return
        self._previous_layout = (frame, reading)
        if previous is None or frame.captured_at - previous[0].captured_at < 1:
            return
        try:
            points = resolve_panel_points(previous[1], reading, self.region)
        except ValueError:
            self._target = None
            self.base.fail('面板控制項位置改變或無法安全點擊')
            return
        self._target = PanelTarget(self.base.round_id, self.geometry, *points, frame.captured_at, sid)

    def _supports_target(self, target, reading):
        x, y, width, height = self.region
        for point, box in ((target.input_point, reading.input_box),
                           (target.confirm_point, reading.confirm_box)):
            if (box is None or not x+box[0]*width/1000 < point[0] < x+box[2]*width/1000
                    or not y+box[1]*height/1000 < point[1] < y+box[3]*height/1000):
                return False
        return True

    def begin_submit(self, now, target=None):
        current = self.target(now)
        target = target or current
        if (current is None or target is None or self._previous_layout is None
                or target.round_id != self.base.round_id or target.window_geometry != self.geometry
                or not 0 <= now-target.captured_at <= 2
                or not self._supports_target(target, self._previous_layout[1])):
            return False
        if not self.base.begin_submit(now):
            return False
        # Keep the exact points that the submitter will use, not a moving average.
        self._pinned_target = target
        return True

    def target(self, now):
        self.base.check_time(now)
        if (self.base.phase not in {'READY', 'SUBMITTING'} or self._latest_prompt_state != 'present'
                or self._target is None or not 0 <= now-self._target.captured_at <= 2
                or now >= self.base.deadline):
            return None
        return self._target
