"""Pure, clock-driven round state. Caller serializes mutations; no I/O here."""
import re
from keyboard_executor.core.sequence_input_config import (
    MAX_FRAMES, SAMPLE_INTERVAL_SEC, SUBMIT_CUTOFF_SEC, CONFIRM_CUTOFF_SEC, TOTAL_TIMEOUT_SEC,
)

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "STOPPED"})


def valid_reading(index, char):
    return (type(index) is int and index in (1, 2, 3) and isinstance(char, str)
            and re.fullmatch(r"[A-Za-z0-9]", char, flags=re.ASCII) is not None)


class SequenceRound:
    def __init__(self, round_id: int, captured_at: float):
        self.round_id = round_id
        self.started_at = captured_at
        self.deadline = captured_at + TOTAL_TIMEOUT_SEC
        self.prepare_deadline = captured_at + SUBMIT_CUTOFF_SEC
        self.confirm_deadline = captured_at + CONFIRM_CUTOFF_SEC
        self.phase = "COLLECTING"
        self.failure = None
        self.answer = None
        self._samples = {}
        self._fingerprints = set()
        self._pending = set()
        self._chars = {}
        self._frozen = False
        self._clicked_at = None
        self._absence_at = None
        self._last_observation = float("-inf")

    @property
    def collected_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self._chars))

    def fail(self, reason: str):
        if self.phase not in TERMINAL:
            self.phase, self.failure = "FAILED", reason

    def stop(self):
        if self.phase not in TERMINAL:
            self.phase = "STOPPED"

    def check_time(self, now: float):
        if now >= self.deadline:
            self.fail("圖片順序輸入超過總時限 30 秒")
        elif now >= self.prepare_deadline and self.phase in {"COLLECTING", "READY"}:
            self.fail("未能在 18 秒內完成辨識與安全定位，已停止")
        elif now >= self.confirm_deadline and self.phase == "SUBMITTING":
            self.fail("未能在 20 秒內按下確認，已停止且不補送")

    def register(self, sample_id: int, fingerprint: str, captured_at: float) -> bool:
        self.check_time(captured_at)
        if (self.phase != "COLLECTING" or self._frozen or captured_at < self.started_at
                or sample_id in self._samples or fingerprint in self._fingerprints
                or len(self._samples) >= MAX_FRAMES):
            return False
        self._samples[sample_id] = fingerprint
        self._fingerprints.add(fingerprint)
        self._pending.add(sample_id)
        return True

    def apply(self, round_id, sample_id, index, char, now):
        if round_id != self.round_id:
            return
        self.check_time(now)
        if self.phase != "COLLECTING" or sample_id not in self._pending:
            return
        self._pending.remove(sample_id)
        if valid_reading(index, char):
            char = char.upper()
            if index in self._chars and self._chars[index] != char:
                self.fail(f"編號 {index} 辨識結果衝突，未送出")
                return
            self._chars[index] = char
        if len(self._chars) == 3:
            self._frozen = True
            if not self._pending:
                self.answer = "".join(self._chars[i] for i in (1, 2, 3))
                self.phase = "READY"

    @property
    def frozen(self) -> bool:
        return self._frozen

    def abandon(self, sample_ids, now: float):
        """三個字已定案後，放棄還沒回來的取樣（AI 請求卡住）。"""
        self.check_time(now)
        if self.phase != "COLLECTING" or not self._frozen:
            return
        self._pending.difference_update(sample_ids)
        if not self._pending:
            self.answer = "".join(self._chars[i] for i in (1, 2, 3))
            self.phase = "READY"

    def begin_submit(self, now: float) -> bool:
        self.check_time(now)
        if self.phase != "READY":
            return False
        self.phase = "SUBMITTING"
        return True

    def mark_clicked(self, now: float):
        self.check_time(now)
        if self.phase == "SUBMITTING":
            self.phase = "VERIFYING"
            self._clicked_at = now

    def observe_absence(self, captured_at: float, now: float, *, valid: bool, absent: bool):
        self.check_time(now)
        if (self.phase != "VERIFYING" or captured_at <= self._clicked_at
                or captured_at <= self._last_observation or captured_at > now):
            return
        self._last_observation = captured_at
        if not valid or not absent:
            self._absence_at = None
        elif self._absence_at is None:
            self._absence_at = captured_at
        elif captured_at - self._absence_at >= SAMPLE_INTERVAL_SEC:
            self.phase = "SUCCEEDED"
