"""Serialize visual interventions on the player's thread; sequence takes priority."""
import logging

logger = logging.getLogger(__name__)


class VisualIntervention:
    supports_sequence_input = True

    def __init__(self, watcher, submitter, chat=None, *, owned_ocr=None):
        self.watcher, self.submitter, self.chat = watcher, submitter, chat
        self._owned_ocr = owned_ocr
        self._window = None
        self._closed = False
        self.sequence_epoch = 0
        self._resume_guard = None
        gate = getattr(watcher, 'require_input_release', None)
        if gate:
            gate()
        if chat:
            chat.set_input_preempted(watcher.requested.is_set)

    def __call__(self, script, win):
        if self._closed:
            return
        if self._window is None:
            self._window = win
            self.watcher.start(win)
        if win.handle != self._window.handle:
            return
        if not self.watcher.requested.is_set() and self.chat:
            self.chat(script, win)
        # Check again: detection may have preempted a chat operation above.
        if self.watcher.requested.is_set():
            self.pause_for_sequence(script, win)

    def sequence_pending(self):
        return not self._closed and self.watcher.requested.is_set()

    def resume_allowed(self):
        return not self._closed and (self._resume_guard is None or self._resume_guard())

    def pause_for_sequence(self, script, win):
        """Player calls only after releasing its held input; never invokes chat."""
        if self._closed:
            return False
        if not self.watcher.requested.is_set():
            return True
        if self._window is None or win.handle != self._window.handle:
            self.watcher.fail('圖片提示與目前腳本視窗不一致，已停止')
            return False
        self.sequence_epoch += 1
        self._resume_guard = None
        if self.chat:
            self.chat.suspend()
        rid = self.watcher.snapshot().round_id
        acknowledge = getattr(self.watcher, 'acknowledge_pause', None)
        if acknowledge and not acknowledge(rid):
            self.watcher.fail('圖片順序輸入交接失效或逾時，已停止')
            return False
        logger.info('圖片順序輸入：腳本已暫停、按鍵已放開，開始 AI 辨識')
        if not self.submitter.run(win):
            return False
        if self.chat and not getattr(self.chat, 'can_resume_after_intervention', True):
            self.watcher.fail('提示已消失，但聊天輸入曾被中斷；保留草稿並停止，請確認焦點後再執行')
            return False
        snap = self.watcher.snapshot()
        guard = getattr(self.watcher, 'resume_allowed', None)
        if guard:
            self._resume_guard = lambda: guard(rid, snap.deadline)
        if self.chat:
            self.chat.resume()
        self.watcher.rearm(rid)
        return not self.watcher.requested.is_set()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.watcher.close()
        finally:
            try:
                if self.chat:
                    self.chat.close()
            finally:
                close = getattr(self._owned_ocr, "close", None)
                if close:
                    close()
