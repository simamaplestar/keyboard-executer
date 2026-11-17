"""AI 示範錄製對話框：選視窗、框小地圖、錄一圈示範（按鍵＋每 500ms 截圖）。

錄完發出 recorded(DemoRecording, WindowInfo, session 路徑)，由主視窗交給 AiDemoController。
F9 開始/停止、F10 放棄沿用 RecorderSession。"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from keyboard_executor.app.ai_demo_capture import FrameSampler, read_dot
from keyboard_executor.app.key_overlay import KeyOverlay, describe_event
from keyboard_executor.app.recorder_session import RecorderSession
from keyboard_executor.core.ai_demo.prompt import DemoRecording
from keyboard_executor.core.ai_demo.timeline import DemoEventLog
from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook

LONG_DEMO_SEC = 180


class AiDemoDialog(QDialog):
    recorded = Signal(object, object, object)
    state_changed = Signal(str)
    key_observed = Signal(str)

    def __init__(self, window_manager, sessions, *, hook_factory=PynputInputHook,
                 session_factory=RecorderSession, sampler_factory=FrameSampler,
                 capture_factory=None, dot_reader=read_dot, overlay_factory=KeyOverlay,
                 toggle_key: str = "f9", stop_key: str = "f10", parent=None):
        super().__init__(parent)
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._wm = window_manager
        self._sessions = sessions
        self._hook_factory = hook_factory
        self._session_factory = session_factory
        self._sampler_factory = sampler_factory
        self._capture_factory = capture_factory
        self._dot_reader = dot_reader
        self._overlay_factory = overlay_factory
        self._overlay = None
        self._toggle_key = toggle_key
        self._stop_key = stop_key
        self._windows = []
        self._win = None
        self._session = None
        self._log: DemoEventLog | None = None
        self._sampler = None
        self._session_dir = None
        self._region = None
        self._start_dot = None
        self._capture_scale = 1.0
        self._t0_ms = 0
        self._region_overlay = None
        self.setWindowTitle("AI 示範錄製")

        layout = QVBoxLayout(self)
        tip = QLabel("在遊戲裡照平常跑一圈練功，AI 會看你的按鍵和畫面產生練功腳本，"
                     "並自動試跑、修正。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.refresh_button = QPushButton("重新整理")
        row.addWidget(self.window_combo, stretch=1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("小地圖範圍"))
        self.region_edit = QLineEdit()
        self.region_edit.setPlaceholderText("x, y, w, h（按右邊按鈕框選）")
        self.pick_button = QPushButton("框選小地圖")
        region_row.addWidget(self.region_edit, stretch=1)
        region_row.addWidget(self.pick_button)
        layout.addLayout(region_row)
        self.goal_edit = QLineEdit()
        self.goal_edit.setPlaceholderText("想做什麼（選填），例如：左右打怪，跳上平台再下跳")
        layout.addWidget(self.goal_edit)
        self.toggle_button = QPushButton(f"開始示範（{toggle_key.upper()}）")
        self.toggle_button.setProperty("variant", "primary")
        layout.addWidget(self.toggle_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(1000)
        self._elapsed.timeout.connect(self._tick)

        self.refresh_button.clicked.connect(self.refresh_windows)
        self.pick_button.clicked.connect(self._pick_region)
        self.toggle_button.clicked.connect(self._on_toggle_clicked)
        self.state_changed.connect(self._on_state)
        self.key_observed.connect(self._on_key_observed)
        self.refresh_windows()

    def refresh_windows(self) -> None:
        self._windows = [w for w in self._wm.list_all() if w.title.strip()]
        self.window_combo.clear()
        self.window_combo.addItems([f"{w.title}（{w.app_name}）" for w in self._windows])

    def _selected_window(self):
        index = self.window_combo.currentIndex()
        if index < 0 or index >= len(self._windows):
            self.status_label.setText("請先選擇目標視窗")
            return None
        return self._wm.refresh(self._windows[index]) or self._windows[index]

    def _parse_region(self):
        from keyboard_executor.app.action_fields import parse_int_list
        raw = self.region_edit.text().strip()
        if not raw:
            self.status_label.setText("請先框選小地圖範圍")
            return None
        try:
            region = parse_int_list("小地圖範圍", raw, 4)
        except ScriptValidationError as exc:
            self.status_label.setText(str(exc))
            return None
        if region[2] <= 0 or region[3] <= 0:
            self.status_label.setText("小地圖範圍的寬高必須大於 0")
            return None
        return tuple(region)

    def _pick_region(self) -> None:
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale

        win = self._selected_window()
        if win is None:
            return
        overlay = RegionPickerOverlay(self, capture_factory=self._capture_factory)
        self._region_overlay = overlay

        def on_selected(rect) -> None:
            try:
                region = screen_rect_to_window_region(
                    rect, Point(win.x, win.y), drag_scale(overlay.devicePixelRatio()))
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self.region_edit.setText(", ".join(str(v) for v in region))
            self.status_label.setText("已框選小地圖，站到起點後按開始示範")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()

    def _on_toggle_clicked(self) -> None:
        if self._session is not None:
            self._session.toggle()
            return
        win = self._selected_window()
        if win is None:
            return
        region = self._parse_region()
        if region is None:
            return
        capture = self._capture_factory()
        try:
            self._capture_scale = capture.scale_factor()
            dot = self._dot_reader(capture, self._wm, win, region)
        except Exception as exc:
            self.status_label.setText(f"無法擷取畫面：{exc}")
            return
        finally:
            close = getattr(capture, "close_current_thread", None)
            if close is not None:
                close()
        if dot is None:
            self.status_label.setText("小地圖範圍內找不到角色黃點，請重新框選小地圖")
            return
        self._win, self._region, self._start_dot = win, region, dot

        def recorder_factory(origin, mode="simplified"):
            self._log = DemoEventLog(origin, mode)
            return self._log

        session = self._session_factory(
            self._hook_factory(), Point(win.x, win.y), recorder_factory=recorder_factory,
            toggle_key=self._toggle_key, stop_key=self._stop_key,
            on_state=self.state_changed.emit, on_event=self._emit_key_observed)
        try:
            session.start()
        except Exception as exc:
            self.status_label.setText(f"無法啟動輸入監聽（可能缺輸入監控權限）：{exc}")
            return
        self._session = session
        self._session_dir = self._sessions.create()
        session.toggle()

    def _emit_key_observed(self, event) -> None:
        text = describe_event(event)
        if text:
            self.key_observed.emit(text)

    def _on_key_observed(self, text: str) -> None:
        if self._overlay is not None:
            self._overlay.push(text)

    def _tick(self) -> None:
        sec = int(time.monotonic() - self._t0_ms / 1000)
        msg = f"示範中……{sec} 秒，再按 {self._toggle_key.upper()} 停止，" \
              f"{self._stop_key.upper()} 放棄"
        if sec >= LONG_DEMO_SEC:
            msg += "\n錄製越長，挑出給 AI 的畫面越稀疏，一圈就夠了"
        self.status_label.setText(msg)

    def _on_state(self, state: str) -> None:
        if state == "recording":
            self._t0_ms = int(time.monotonic() * 1000)
            if self._log is not None:
                self._log.start(self._t0_ms)
            self._sampler = self._sampler_factory(
                self._capture_factory, self._wm, self._win, self._region,
                self._session_dir / "frames", "D", t0_ms=self._t0_ms)
            self._sampler.start()
            self.toggle_button.setText(f"停止示範（{self._toggle_key.upper()}）")
            self._tick()
            self._elapsed.start()
            if self._overlay_factory is not None:
                if self._overlay is None:
                    self._overlay = self._overlay_factory(self)
                self._overlay.show_at_top()
            return
        self._elapsed.stop()
        if self._overlay is not None:
            self._overlay.hide()
        frames = self._sampler.stop() if self._sampler is not None else []
        self._sampler = None
        session, self._session = self._session, None
        result = session.finish() if session is not None else None
        self.toggle_button.setText(f"開始示範（{self._toggle_key.upper()}）")
        if state == "aborted" or result is None:
            self.status_label.setText("已放棄示範")
            return
        if not frames:
            self.status_label.setText("沒有截到任何畫面，請確認遊戲視窗沒有被遮住後重試")
            return
        holds, mouse = result
        duration = max([frames[-1].t_ms] + [h.end_ms for h in holds] + [m.t_ms for m in mouse])
        rec = DemoRecording(frames=frames, holds=holds, mouse=mouse,
                            event_times_ms=self._log.event_times_ms(),
                            duration_ms=max(duration, 500), start_dot=self._start_dot,
                            minimap_region=self._region, window_title=self._win.title,
                            goal_text=self.goal_edit.text().strip(),
                            capture_scale=self._capture_scale)
        self._sessions.save_timeline(self._session_dir, {
            "window_title": rec.window_title, "duration_ms": rec.duration_ms,
            "start_dot": list(rec.start_dot), "minimap_region": list(rec.minimap_region),
            "capture_scale": rec.capture_scale, "goal_text": rec.goal_text,
            "holds": [[h.key, h.start_ms, h.end_ms] for h in holds],
            "mouse": [[m.kind, m.t_ms, m.x, m.y, m.button, m.to, m.dy] for m in mouse],
            "frames": [{"id": f.id, "t_ms": f.t_ms, "size": list(f.size),
                        "dot": None if f.dot is None else list(f.dot)} for f in frames],
        })
        self.status_label.setText(f"示範完成（{rec.duration_ms / 1000:.1f} 秒、"
                                  f"{len(frames)} 張截圖），交給 AI 產生腳本")
        self.recorded.emit(rec, self._win, self._session_dir)
        self.accept()

    def _abort_recording(self) -> None:
        if self._session is not None:      # 錄到一半關掉視窗＝放棄
            stop_event = getattr(self._session, "stop_event", None)
            if stop_event is not None:
                stop_event.set()
            self._on_state("aborted")

    def reject(self) -> None:              # Esc 走這裡，不會經過 closeEvent
        self._abort_recording()
        super().reject()

    def closeEvent(self, event):     # noqa: N802 - Qt 命名
        self._abort_recording()
        super().closeEvent(event)
