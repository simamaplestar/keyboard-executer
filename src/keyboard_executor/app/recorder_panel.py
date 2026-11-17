"""錄製面板（spec §9）：目標視窗選擇（下拉＋重新整理）、軌跡模式切換、
開始/停止、錄後預覽動作數與命名存檔。

薄件：會話狀態機在 RecorderSession（純邏輯）。on_state 來自 pynput listener
執行緒，經 state_changed signal（queued）轉回 GUI 執行緒才碰 widget。
名稱不合法時錯誤顯示在 status_label、面板留著重試。版面列人工驗收。"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.key_overlay import KeyOverlay, describe_event
from keyboard_executor.app.recorder_session import RecorderSession, script_from_recording
from keyboard_executor.core.geometry import Point
from keyboard_executor.app.route_recorder import (
    MinimapSampler, RouteEventLog, build_route, minimap_png,
)
from keyboard_executor.core.keynames import is_valid_key
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook


class RecorderPanel(QDialog):
    state_changed = Signal(str)
    key_observed = Signal(str)     # listener 執行緒 → GUI 執行緒（浮動窗更新）

    def __init__(self, window_manager, storage, *, hook_factory=PynputInputHook,
                 session_factory=RecorderSession, overlay_factory=KeyOverlay,
                 toggle_key: str = "f9", stop_key: str = "f10", parent=None,
                 capture_factory=None, sampler_factory=MinimapSampler,
                 route_settle_ms: int = 1500, route_only: bool = False,
                 preset_region=None, preset_timed: str = "", preset_title: str = ""):
        super().__init__(parent)
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._capture_factory = capture_factory
        self._sampler_factory = sampler_factory
        self._route_settle_ms = route_settle_ms
        self._sampler = None
        self._route_window = (None, None)
        self._region_overlay = None
        self._timed = ()
        self._route_only = route_only
        self.learned_actions = None       # route_only：按「套用到腳本」後給編輯器
        self.learned_timed = ()
        self.learned_map = None           # 地圖分析 sidecar（dict）
        self.learned_png = None
        self._route_result = None
        self._route_png = None
        self._wm = window_manager
        self._storage = storage
        self._hook_factory = hook_factory
        self._session_factory = session_factory
        self._overlay_factory = overlay_factory
        self._overlay = None
        self._toggle_key = toggle_key
        self._stop_key = stop_key
        self._session = None
        self._windows = []
        self._win = None
        self._actions = None
        self.setWindowTitle("錄製面板")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.refresh_button = QPushButton("重新整理")
        row.addWidget(self.window_combo, stretch=1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.full_trajectory_check = QCheckBox("完整軌跡模式（保留滑鼠移動路徑）")
        layout.addWidget(self.full_trajectory_check)
        self.route_check = QCheckBox("學習小地圖路線（錄一圈，自動產生練功腳本）")
        layout.addWidget(self.route_check)
        self.route_box = QWidget()
        route_lay = QVBoxLayout(self.route_box)
        route_lay.setContentsMargins(16, 0, 0, 0)
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("小地圖範圍"))
        self.region_edit = QLineEdit()
        self.region_edit.setPlaceholderText("x, y, w, h（相對視窗）")
        region_row.addWidget(self.region_edit, stretch=1)
        self.region_button = QPushButton("框選")
        region_row.addWidget(self.region_button)
        route_lay.addLayout(region_row)
        option_row = QHBoxLayout()
        option_row.addWidget(QLabel("跳躍鍵"))
        self.jump_edit = QLineEdit("space")
        self.jump_edit.setMaximumWidth(80)
        option_row.addWidget(self.jump_edit)
        option_row.addWidget(QLabel("重複圈數"))
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 9999)
        self.loop_spin.setValue(100)
        option_row.addWidget(self.loop_spin)
        option_row.addStretch(1)
        route_lay.addLayout(option_row)
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("走法"))
        self.style_combo = QComboBox()
        self.style_combo.addItem("分析小地圖，整理成每層左右掃（建議）", "patrol")
        self.style_combo.addItem("照錄製一步一步重播", "replay")
        style_row.addWidget(self.style_combo, stretch=1)
        style_row.addWidget(QLabel("每層掃"))
        self.sweep_spin = QSpinBox()
        self.sweep_spin.setRange(1, 10)
        self.sweep_spin.setSuffix(" 趟")
        style_row.addWidget(self.sweep_spin)
        route_lay.addLayout(style_row)
        timed_row = QHBoxLayout()
        timed_row.addWidget(QLabel("定時技能"))
        from keyboard_executor.app.timed_keys_widget import TimedKeysWidget
        self.timed_edit = TimedKeysWidget()
        self.timed_edit.setToolTip("錄製時會忽略這些鍵；回放時每隔設定的秒數自動放一次")
        timed_row.addWidget(self.timed_edit, stretch=1)
        route_lay.addLayout(timed_row)
        tip = QLabel("錄製時照平常跑完整一圈並回到起點：在每個要打怪的平台按攻擊鍵，"
                     "換層的方式（爬繩、連跳、下跳、傳點）會照你錄的走。")
        tip.setWordWrap(True)
        route_lay.addWidget(tip)
        self.route_box.setVisible(False)
        layout.addWidget(self.route_box)
        self.toggle_button = QPushButton(f"開始錄製（{toggle_key.upper()}）")
        layout.addWidget(self.toggle_button)
        self.name_box = QWidget()
        name_row = QHBoxLayout(self.name_box)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(QLabel("腳本名稱"))
        self.name_edit = QLineEdit()
        name_row.addWidget(self.name_edit)
        layout.addWidget(self.name_box)
        self.save_button = QPushButton("儲存腳本")
        self.save_button.setProperty("variant", "primary")
        layout.addWidget(self.save_button)
        self.status_label = QLabel("選擇目標視窗後按開始錄製")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.refresh_button.clicked.connect(self.refresh_windows)
        self.toggle_button.pressed.connect(self._on_toggle_button_pressed)
        self.toggle_button.clicked.connect(self._on_toggle_clicked)
        self.save_button.clicked.connect(self._on_save_clicked)
        self.route_check.toggled.connect(self._on_route_toggled)
        self.region_button.clicked.connect(self._pick_region)
        self.state_changed.connect(self._on_state)   # listener 執行緒 → GUI 執行緒
        self.key_observed.connect(self._on_key_observed)
        self.refresh_windows()
        if route_only:
            self._setup_route_only(preset_region, preset_timed, preset_title)

    def refresh_windows(self) -> None:
        self._windows = [w for w in self._wm.list_all() if w.title.strip()]
        self.window_combo.clear()
        self.window_combo.addItems(
            [f"{w.title}（{w.app_name}）" for w in self._windows])

    def _on_toggle_button_pressed(self) -> None:
        """`pressed` 訊號在按下當下就觸發（比放開才觸發的 `clicked` 早）：
        錄製中按這顆鈕停止時，實體點擊可能被 pynput hook 搶先送進 Recorder，
        先告知 session 忽略，避免尾端多出一筆點擊（見 RecorderSession.
        mark_stop_button_pressed）。session 尚未建立（正要開始錄製那次按下）
        時是 no-op。"""
        if self._session is not None:
            self._session.mark_stop_button_pressed()

    def _on_toggle_clicked(self) -> None:
        if self._session is None:
            index = self.window_combo.currentIndex()
            if index < 0 or index >= len(self._windows):
                self.status_label.setText("請先選擇目標視窗")
                return
            self._win = self._windows[index]
            mode = ("full" if self.full_trajectory_check.isChecked()
                    else "simplified")
            extra = {}
            if self.route_check.isChecked():
                region = self._route_region()
                if (region is None or self._route_jump_key() is None
                        or self._route_timed() is None):
                    return
                extra["recorder_factory"] = RouteEventLog
                self._sampler = self._sampler_factory(self._capture_factory, self._wm,
                                                      self._win, region)
            self._session = self._session_factory(
                self._hook_factory(), Point(self._win.x, self._win.y), mode=mode,
                toggle_key=self._toggle_key, stop_key=self._stop_key,
                on_state=self.state_changed.emit,
                on_event=self._emit_key_observed, **extra)
            try:
                self._session.start()
            except Exception as e:
                self.status_label.setText(f"無法啟動輸入監聽（可能缺輸入監控權限）：{e}")
                self._session = None
                self._sampler = None
                return
            if self._sampler is not None:
                self._sampler.start()
        self._session.toggle()

    def _emit_key_observed(self, event) -> None:
        """listener 執行緒：先轉成短描述（純函式，執行緒安全）再經 signal 送回
        GUI 執行緒——widget 只能在 GUI 執行緒碰。"""
        text = describe_event(event)
        if text:
            self.key_observed.emit(text)

    def _on_key_observed(self, text: str) -> None:
        if self._overlay is not None:
            self._overlay.push(text)

    def _show_overlay(self) -> None:
        if self._overlay_factory is None:
            return
        if self._overlay is None:
            self._overlay = self._overlay_factory(self)
        self._overlay.show_at_top()

    def _hide_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()

    def closeEvent(self, event):     # noqa: N802 - Qt 命名
        self._hide_overlay()
        super().closeEvent(event)

    def _on_state(self, state: str) -> None:
        if state == "recording":
            self.toggle_button.setText(f"停止錄製（{self._toggle_key.upper()}）")
            self.status_label.setText(
                f"錄製中……再按 {self._toggle_key.upper()} 停止，"
                f"{self._stop_key.upper()} 放棄")
            self._route_window = (time.monotonic(), None)
            self._show_overlay()
            return
        self._hide_overlay()
        if self._sampler is not None:
            self._finish_route(state)
            return
        actions = self._session.finish() if self._session is not None else None
        self._session = None
        self.toggle_button.setText(f"開始錄製（{self._toggle_key.upper()}）")
        if state == "aborted" or actions is None:
            self.status_label.setText("已放棄錄製")
        elif not actions:
            self.status_label.setText("沒有錄到任何動作")
        else:
            self._actions = actions
            self.status_label.setText(f"錄到 {len(actions)} 個動作，輸入名稱後儲存")

    # -- 小地圖路線學習 --

    def _setup_route_only(self, region, timed: str, title: str) -> None:
        """編輯器「繞一圈學路線」：只顯示路線選項，結果交回編輯器而不另存腳本。"""
        import re
        self.setWindowTitle("繞一圈學路線")
        self.route_check.setChecked(True)
        self.route_check.setVisible(False)
        self.full_trajectory_check.setVisible(False)
        self.name_box.setVisible(False)
        self.save_button.setText("套用到腳本")
        if region:
            self.region_edit.setText(", ".join(str(v) for v in region))
        self.timed_edit.setText(timed)
        if title:
            for i, w in enumerate(self._windows):
                try:
                    hit = re.search(title, w.title)
                except re.error:
                    hit = title in w.title
                if hit:
                    self.window_combo.setCurrentIndex(i)
                    break
        self.status_label.setText(
            f"確認小地圖範圍後按開始錄製（{self._toggle_key.upper()}），照平常跑一圈")

    def _on_route_toggled(self, checked: bool) -> None:
        self.route_box.setVisible(checked)
        self.full_trajectory_check.setEnabled(not checked)

    def _route_region(self):
        from keyboard_executor.app.action_fields import parse_int_list
        raw = self.region_edit.text().strip()
        if not raw:
            self.status_label.setText("請先框選小地圖範圍")
            return None
        try:
            region = parse_int_list("小地圖範圍", raw, 4)
        except ScriptValidationError as e:
            self.status_label.setText(str(e))
            return None
        if region[2] <= 0 or region[3] <= 0:
            self.status_label.setText("小地圖範圍的寬高必須大於 0")
            return None
        return region

    def _route_jump_key(self):
        key = self.jump_edit.text().strip().lower()
        if not key or not is_valid_key(key):
            self.status_label.setText(f"跳躍鍵不是可用的按鍵名稱：{key!r}")
            return None
        return key

    def _route_timed(self):
        try:
            return self.timed_edit.items()
        except ScriptValidationError as e:
            self.status_label.setText(str(e))
            return None

    def _pick_region(self) -> None:
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale

        index = self.window_combo.currentIndex()
        if index < 0 or index >= len(self._windows):
            self.status_label.setText("請先選擇目標視窗")
            return
        win = self._wm.refresh(self._windows[index]) or self._windows[index]
        overlay = RegionPickerOverlay(self, capture_factory=self._capture_factory)
        self._region_overlay = overlay

        def on_selected(rect) -> None:
            try:
                region = screen_rect_to_window_region(
                    rect, Point(win.x, win.y), drag_scale(overlay.devicePixelRatio()))
            except ValueError as e:
                self.status_label.setText(str(e))
                return
            self.region_edit.setText(", ".join(str(v) for v in region))
            self.status_label.setText("已框選小地圖，按開始錄製後照平常跑一圈")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()

    def _finish_route(self, state: str) -> None:
        events = self._session.finish() if self._session is not None else None
        self._session = None
        self.toggle_button.setText(f"開始錄製（{self._toggle_key.upper()}）")
        if state == "aborted" or events is None:
            self._sampler.stop()
            self._sampler = None
            self.status_label.setText("已放棄錄製")
            return
        self._route_window = (self._route_window[0], time.monotonic())
        self.toggle_button.setEnabled(False)
        self.status_label.setText("整理路線中……人物先別動")
        # 最後一步之後多讀一下黃點，才知道滑行/落地停在哪。
        QTimer.singleShot(self._route_settle_ms, lambda: self._build_route(events))

    def _build_route(self, events) -> None:
        sampler, self._sampler = self._sampler, None
        samples = sampler.stop()
        self.toggle_button.setEnabled(True)
        start, end = self._route_window
        timed = self._route_timed() or ()
        skip = {t.key for t in timed}
        events = [e for e in events if e.key not in skip]   # 定時技能不當成路線上的按鍵
        try:
            result = build_route(events, samples, self._route_region(),
                                 jump_key=self._route_jump_key() or "space",
                                 loop_count=self.loop_spin.value(), start=start, end=end,
                                 replay=self.style_combo.currentData() == "replay",
                                 sweeps=self.sweep_spin.value())
        except (ValueError, ScriptValidationError) as e:
            self.status_label.setText(f"無法產生路線：{e}")
            return
        self._route_result = result
        self._route_png = minimap_png(getattr(sampler, "last_image", None))
        self._actions = result.actions
        self._timed = tuple(timed)
        if not self.name_edit.text().strip():
            self.name_edit.setText("小地圖路線")
        tail = ("按「套用到腳本」放進編輯器" if self._route_only
                else "輸入名稱後儲存，再到編輯器檢查")
        self.status_label.setText(f"{result.summary}，{tail}\n\n{result.analysis}")

    def _on_save_clicked(self) -> None:
        if not self._actions:
            self.status_label.setText("沒有可儲存的錄製結果")
            return
        if self._route_only:
            self.learned_actions = list(self._actions)
            self.learned_timed = tuple(self._timed)
            if self._route_result is not None:
                self.learned_map = self._route_result.sidecar
                self.learned_png = self._route_png
            self.accept()
            return
        try:
            script = script_from_recording(self.name_edit.text().strip(),
                                           self._win, self._actions)
            if self._timed:
                from dataclasses import replace
                script = replace(script, settings=replace(script.settings,
                                                          timed_keys=self._timed))
            path = self._storage.save(script)
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")   # 名稱不合法→留在面板重試
            return
        if self._route_result is not None and hasattr(self._storage, "save_route_map"):
            self._storage.save_route_map(script.name, self._route_result.sidecar,
                                         self._route_png)
        self.status_label.setText(f"已儲存：{path}（共 {len(self._actions)} 個動作）")
        self.accept()                       # 儲存成功 → 自動關閉
