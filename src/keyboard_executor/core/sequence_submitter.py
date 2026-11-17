"""One-shot foreground input, called only from the player's action boundary."""
import time
from keyboard_executor.core.sequence_watcher import geometry
from keyboard_executor.platforms.base import MouseButton


class SequenceSubmitter:
    def __init__(self, platform, config, watcher, stop_event, *, clock=time.monotonic, target_provider=None):
        self._platform, self._config, self._watcher = platform, config, watcher
        self._stop, self._clock = stop_event, clock
        self._target_provider = target_provider

    def _check(self, win, rid, expected_geometry):
        snap = self._watcher.snapshot()
        if (self._stop.is_set() or snap.round_id != rid or snap.phase != "SUBMITTING"
                or self._clock() >= snap.confirm_deadline):
            raise RuntimeError("操作已停止或超過 20 秒確認期限")
        fresh = self._platform.window_manager.refresh(win)
        if fresh is None or not fresh.is_active or geometry(fresh) != expected_geometry:
            raise RuntimeError("目標視窗已移動、關閉或失去焦點")
        # OCR may invalidate the round while the native query blocks, before
        # the supervisor has propagated that failure to stop_event.
        after = self._watcher.snapshot()
        if (self._stop.is_set() or after.round_id != rid or after.phase != "SUBMITTING"
                or self._clock() >= after.confirm_deadline):
            raise RuntimeError("操作已停止或超過 20 秒確認期限")
        return fresh

    def run(self, win):
        snap = self._watcher.wait_ready()
        if snap.phase != "READY":
            return False
        rid = snap.round_id
        try:
            if (self._stop.is_set() or self._clock() >= snap.prepare_deadline
                    or not self._watcher.validate_prompt(rid)):
                raise RuntimeError("未能在 18 秒內確認提示與安全定位，未送出")
            fresh = self._platform.window_manager.refresh(win)
            if fresh is None:
                raise RuntimeError("目標視窗已關閉")
            if not fresh.is_active:
                # 背景偵測到的回合：輸入前先把目標視窗切回前景。
                if not self._platform.window_manager.activate(fresh):
                    raise RuntimeError("無法將目標視窗切回前景，未輸入")
                fresh = self._platform.window_manager.refresh(win)
                if fresh is None or not fresh.is_active:
                    raise RuntimeError("無法確認前景目標視窗")
            expected_geometry = getattr(snap, "window_geometry", None) or geometry(fresh)
            if geometry(fresh) != expected_geometry:
                raise RuntimeError("提示確認後視窗已改變，未輸入")
            target = self._target_provider(rid) if self._target_provider else None
            if target is not None:
                if (target.round_id != rid or target.window_geometry != expected_geometry
                        or not 0 <= self._clock() - target.captured_at <= 2):
                    raise RuntimeError("面板定位已失效，未輸入")
                input_point, confirm_point = target.input_point, target.confirm_point
            else:
                input_point, confirm_point = self._config.input_point, self._config.confirm_point
            for x, y in (input_point, confirm_point):
                if not (0 <= x < fresh.width and 0 <= y < fresh.height):
                    raise RuntimeError("輸入或確認位置超出目標視窗")
            answer = self._watcher.begin_submit(rid)
            if answer is None:
                raise RuntimeError("本回合已失效或超時")
            backend = self._platform.input_backend
            fresh = self._check(win, rid, expected_geometry)
            backend.set_target_window(fresh)
            self._check(win, rid, expected_geometry)
            x, y = input_point
            check = lambda: self._check(win, rid, expected_geometry)
            def input_check():
                check()
                if target is not None and not 0 <= self._clock() - target.captured_at <= 2:
                    raise RuntimeError("面板定位已過期，未點擊輸入框")
            backend.mouse_click_checked(fresh.x+x, fresh.y+y, MouseButton.LEFT, 1, check=input_check)
            pressed = []
            try:
                for key in ("ctrl", "a"):
                    self._check(win, rid, expected_geometry)
                    # Also release if a backend raises after issuing key-down.
                    pressed.append(key)
                    backend.key_down(key)
                self._stop.wait(.1)
            finally:
                for key in reversed(pressed):
                    backend.key_up(key)
            for char in answer:
                self._check(win, rid, expected_geometry)
                backend.type_text(char)
            fresh = self._check(win, rid, expected_geometry)
            x, y = confirm_point
            # Transition only after backend settle, immediately before dispatch.
            # No progress callbacks or other blocking work may run in this hook.
            def before_confirm():
                check()
                self._watcher.mark_clicked(rid)
                current = self._watcher.snapshot()
                if (self._stop.is_set() or current.phase != "VERIFYING"
                        or self._clock() >= current.confirm_deadline):
                    raise RuntimeError("確認已取消或超過 20 秒期限")
            backend.mouse_click_checked(fresh.x+x, fresh.y+y, MouseButton.LEFT, 1,
                                        check=check, before_click=before_confirm)
            if not self._watcher.wait_complete(rid):
                raise RuntimeError("未在總時限內確認提示消失，已停止且不重試")
            return True
        except Exception as exc:
            self._watcher.fail(str(exc))
            self._stop.set()
            return False
