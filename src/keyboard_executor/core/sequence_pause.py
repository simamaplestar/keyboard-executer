"""Cooperative, sequence-only pause on the Player's input-owning thread."""
import logging

logger = logging.getLogger(__name__)
_QUANTUM = .02


class SequencePauseError(RuntimeError):
    """Fail closed rather than resume an uncertain script input state."""


class SequencePause:
    def __init__(self, runtime, stop, clock, sleep, *, validate):
        self.runtime, self.stop, self.clock, self.sleep = runtime, stop, clock, sleep
        self.validate = validate
        self.paused_seconds = 0.
        self.count = 0
        self._holding = None
        self._handling = False

    @property
    def pending(self):
        return not self._handling and self.runtime.sequence_pending()

    def check_stop(self):
        if self.stop.is_set():
            raise SequencePauseError('已手動停止')

    def check_resume(self):
        guard = getattr(self.runtime, 'resume_allowed', None)
        if guard and not guard():
            raise SequencePauseError('接續腳本前圖片回合已失效或超時，已停止')

    def action_time(self):
        return self.clock() - self.paused_seconds

    def checkpoint(self, script, win):
        self.check_stop()
        if not self.pending:
            return False
        if self._holding:
            self._holding[0]()
        started = self.clock()
        self._handling = True
        try:
            before = self.validate(win)
            self.check_stop()
            if not self.runtime.pause_for_sequence(script, win):
                raise SequencePauseError('圖片順序輸入未完成，已停止，不恢復原動作')
            self.check_stop()
            logger.info('圖片順序輸入：提示已消失，正在確認能否接續原動作剩餘部分')
            after = self.validate(win)
            self.check_stop()
            if after != before or self.runtime.sequence_pending():
                raise SequencePauseError('接續腳本前視窗或圖片回合已改變，已停止')
            self.check_resume()
            if self._holding and self._holding[1]:
                self._holding[1]()
            self.count += 1
            return True
        except BaseException:
            self.stop.set()
            raise
        finally:
            self.paused_seconds += max(0., self.clock() - started)
            self._handling = False

    def wait(self, seconds, script, win):
        deadline = self.action_time() + seconds
        while True:
            self.checkpoint(script, win)
            remaining = deadline - self.action_time()
            if remaining <= 1e-9:
                return
            self.sleep(min(_QUANTUM, remaining))

    def _settle(self, seconds):
        # 方向鍵前後的短暫停留；只檢查停止，提示留到按住段或下一個動作處理。
        deadline = self.clock() + seconds
        while (remaining := deadline - self.clock()) > 1e-9:
            self.check_stop()
            self.sleep(min(_QUANTUM, remaining))
        self.check_stop()

    def hold(self, keys, seconds, script, win, backend, *, repeat=False, restore=True,
             lead_keys=0, lead=0., trail=0.):
        pressed = []
        def release():
            error = None
            while pressed:
                try:
                    backend.key_up(pressed.pop())
                except Exception as exc:
                    error = error or exc
            if error:
                self.stop.set()
                raise error
        def press():
            for index, key in enumerate(keys):
                if index and index == lead_keys and lead:
                    self._settle(lead)
                self.check_stop()
                if self._handling:
                    self.check_resume()
                    if self.runtime.sequence_pending():
                        raise SequencePauseError('恢復組合鍵途中收到新提示，已停止')
                elif self.pending:
                    # checkpoint releases the partial combo and either restores
                    # the full long hold or consumes this interrupted short tap.
                    self.checkpoint(script, win)
                    return
                # Include the attempted key in cleanup even if its native press fails.
                pressed.append(key)
                backend.key_down(key)
        previous = self._holding
        self._holding = (release, press if restore else None)
        try:
            self.check_stop()
            press()
            deadline = self.action_time() + seconds
            interval = backend.key_repeat_interval(keys[0]) if repeat else None
            next_repeat = self.action_time() + interval if interval else None
            while pressed:
                resumed = self.checkpoint(script, win)
                if not pressed:  # a short tap was already sent; never replay it
                    break
                now = self.action_time()
                remaining = deadline - now
                if remaining <= 1e-9:
                    break
                if interval:
                    if resumed:
                        next_repeat = now + interval
                    if now + 1e-9 >= next_repeat:
                        backend.key_repeat(keys[0])
                        next_repeat = self.action_time() + interval
                        continue
                    remaining = min(remaining, next_repeat - now)
                self.sleep(min(_QUANTUM, remaining))
            if trail and 0 < lead_keys < len(pressed):
                while len(pressed) > lead_keys:
                    backend.key_up(pressed.pop())
                self._settle(trail)
        finally:
            try:
                release()
            finally:
                self._holding = previous
