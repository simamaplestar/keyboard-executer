"""GUI 錄製會話（純 Python，無 Qt import）——把 cli.run_record 的核心編排
（dispatch 加鎖、控制鍵自我過濾、F9 切換、F10/滑鼠角落放棄）改為事件驅動
供錄製面板使用（spec §6/§9）。

狀態機：idle →（F9/toggle()）recording →（F9/toggle()）done；
stop_event（F10/角落）→ aborted，finish() 回傳 None。
on_state("recording"/"done"/"aborted") 供面板更新按鈕與狀態文字——注意
呼叫發生在 hook 的 listener 執行緒，Qt 面板必須經 signal 轉回 GUI 執行緒。"""
from __future__ import annotations

import re
import threading

from keyboard_executor.core.geometry import Point
from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.core.models import (
    Script,
    ScriptSettings,
    ScriptValidationError,
    TargetWindow,
)
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.platforms.base import EventKind


class RecorderSession:
    def __init__(self, hook, origin: Point, *, mode: str = "simplified",
                 guard_factory=SessionGuard, recorder_factory=Recorder,
                 toggle_key: str = "f9", stop_key: str = "f10", on_state=None,
                 on_event=None):
        self._hook = hook
        self._recorder = recorder_factory(origin, mode=mode)
        self.stop_event = threading.Event()
        self._done = threading.Event()
        self._recording = False
        self._aborted_notified = False
        self._suppress_stop_click = False
        self._on_state = on_state
        self._on_event = on_event   # 每筆真正錄進腳本的事件（供即時顯示）
        self._guard = guard_factory(hook, self.stop_event, on_toggle=self.toggle,
                                    toggle_key=toggle_key, stop_key=stop_key)
        self._lock = threading.Lock()

    def start(self) -> None:
        """啟動監聽（同一 hook 只能 start 一次——控制與轉送共用同一條事件流）。
        缺輸入監控權限時 hook.start 可能拋例外，由面板顯示繁中提示。"""
        self._hook.start(self._dispatch)

    def toggle(self) -> None:
        """F9 或面板按鈕：開始/停止錄製。"""
        if self._done.is_set() or self.stop_event.is_set():
            return
        if self._recording:
            self._done.set()
            self._notify("done")
        else:
            self._recording = True
            self._notify("recording")

    def finish(self):
        """停止監聽並取回動作序列；放棄（stop_event）時回傳 None。"""
        self._hook.stop()
        if self.stop_event.is_set():
            return None
        return self._recorder.finish()

    def mark_stop_button_pressed(self) -> None:
        """面板 STOP 按鈕的 `pressed` 訊號（早於 `clicked`，要放開才觸發 toggle()）
        呼叫：這次實體點擊的 mouse_down/mouse_up 可能已被 pynput hook 搶先送進
        _dispatch，設旗標讓後續滑鼠事件不進 Recorder，避免停止錄製的那次點擊
        被誤錄成腳本尾端多出來的 mouse_click（GUI-only；F9 停止走鍵盤事件，
        已由 is_control_event 自我過濾，不受影響）。"""
        self._suppress_stop_click = True

    def _dispatch(self, event) -> None:
        with self._lock:   # keyboard/mouse listener 各一執行緒，序列化進 Recorder
            self._guard.handle(event)   # 控制語義優先（F9 切換、F10/角落停止）
            if self.stop_event.is_set():
                if not self._aborted_notified:
                    self._aborted_notified = True
                    self._notify("aborted")
                return
            if self._suppress_stop_click and event.kind in (
                    EventKind.MOUSE_DOWN, EventKind.MOUSE_UP):
                # 面板 STOP 鈕本身的點擊事件：忽略，不進 Recorder。抑制只涵蓋這一次
                # 點擊——放開（MOUSE_UP）後即解除，避免「按下後拖離取消」使旗標卡住、
                # 之後所有正常點擊被靜默丟棄（M4 最終審查 re-review 發現的邊界）。
                if event.kind == EventKind.MOUSE_UP:
                    self._suppress_stop_click = False
                return
            if (self._recording and not self._done.is_set()
                    and not self._guard.is_control_event(event)):
                self._recorder.feed(event)   # 自我過濾：控制鍵不錄進腳本
                self._notify_event(event)

    def _notify(self, state: str) -> None:
        if self._on_state is not None:
            self._on_state(state)

    def _notify_event(self, event) -> None:
        """回報「已錄進腳本」的事件——時機刻意放在 feed 之後，浮動窗顯示的就是
        真的進了腳本的那些（控制鍵 F9/F10 與 STOP 鈕點擊都已在上面被濾掉）。
        呼叫發生在 listener 執行緒，接收端必須自行轉回 GUI 執行緒。"""
        if self._on_event is not None:
            self._on_event(event)


def script_from_recording(name: str, win, actions) -> Script:
    """鏡射 cli.run_record 的目標視窗策略：優先 re.escape(標題) 精確比對；
    標題與應用程式名稱皆空時拋 ScriptValidationError（繁中）。"""
    title = re.escape(win.title) if win.title.strip() else None
    app = win.app_name if win.app_name.strip() else None
    if title is None and app is None:
        raise ScriptValidationError("目標視窗沒有標題與應用程式名稱，無法建立腳本")
    target = TargetWindow(title_pattern=title, app_name=None if title else app)
    return Script(name=name, target_window=target, actions=tuple(actions),
                  settings=ScriptSettings())
