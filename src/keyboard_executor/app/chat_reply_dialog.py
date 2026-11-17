"""每份腳本的聊天回覆設定；對話框只編輯草稿，不傳送訊息。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from keyboard_executor.app.action_fields import parse_int_list
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.core.chat_reply_config import (
    ChatReplyConfig, chat_config_from_dict, chat_config_to_dict,
)
from keyboard_executor.core.models import ScriptValidationError


class ChatReplyDialog(QDialog):
    def __init__(self, config: ChatReplyConfig | None = None, parent=None, *,
                 get_target_window=None, get_target_app=None,
                 get_platform=None, capture_factory=None):
        super().__init__(parent)
        self.setWindowTitle("AI 自動回覆")
        self._get_target_window = get_target_window or (lambda: "")
        self._get_target_app = get_target_app or (lambda: "")
        if get_platform is None:
            from keyboard_executor.platforms.factory import get_platform
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._get_platform = get_platform
        self._capture_factory = capture_factory
        self._overlay = None
        data = chat_config_to_dict(config or ChatReplyConfig())
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        self.enabled_check = QCheckBox("執行此腳本時啟用 AI 自動回覆")
        self.enabled_check.setChecked(data["enabled"])
        body.addWidget(self.enabled_check)
        channels = QHBoxLayout()
        channels.addWidget(QLabel("回覆頻道"))
        self.reply_map_check = QCheckBox("地圖聊天")
        self.reply_map_check.setChecked(data["reply_map"])
        self.reply_whisper_check = QCheckBox("密語")
        self.reply_whisper_check.setChecked(data["reply_whisper"])
        channels.addWidget(self.reply_map_check)
        channels.addWidget(self.reply_whisper_check)
        channels.addStretch(1)
        body.addLayout(channels)
        self.channel_status = QLabel()
        self.channel_status.setWordWrap(True)
        body.addWidget(self.channel_status)
        channel_hint = QLabel("程式會自動判斷回覆對象與頻道，輸入回覆並確認送出，"
                              "再切回「對所有人」、退出聊天輸入，接續腳本的下一個動作。")
        channel_hint.setWordWrap(True)
        body.addWidget(channel_hint)
        self.reply_map_check.toggled.connect(self._update_channel_status)
        self.reply_whisper_check.toggled.connect(self._update_channel_status)
        self._update_channel_status()
        info = QLabel("沿用設定頁的 AI 供應商與模型。自動回覆會將框選聊天截圖交給 AI，"
                      "請選擇支援圖片的模型。第一次讀取建立基準，只回覆之後的新訊息。"
                      "目前動作完成並放開按鍵後才回覆，送出後接續原腳本。")
        info.setWordWrap(True)
        body.addWidget(info)
        form = QFormLayout()
        self.name_edit = QLineEdit(data["self_name"])
        form.addRow("自己的角色名稱", self.name_edit)
        self.region_edit = QLineEdit(", ".join(map(str, data["region"])) if data["region"] else "")
        self.region_edit.setPlaceholderText("先在腳本編輯器指定遊戲視窗，再框選聊天區域")
        region_row = QHBoxLayout()
        self.pick_region_button = QPushButton("框選聊天區域")
        self.pick_region_button.clicked.connect(self._on_pick_region)
        region_row.addWidget(self.region_edit, 1)
        region_row.addWidget(self.pick_region_button)
        form.addRow("聊天區域（相對視窗 x, y, 寬, 高）", region_row)
        region_hint = QLabel("聊天區域必須包含左下角的對象／頻道按鈕，"
                             "以及旁邊的白色輸入列。")
        region_hint.setWordWrap(True)
        form.addRow(region_hint)
        self.prompt_edit = QPlainTextEdit(data["prompt"])
        self.prompt_edit.setMaximumHeight(120)
        form.addRow("回覆提示詞", self.prompt_edit)
        timing = QHBoxLayout()
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 300)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setValue(data["interval_sec"])
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setToolTip(
            "背景檢查不受長按或延遲影響。若單次辨識超過此間隔，完成後才開始下一次；"
            "AI 先在背景產生回覆，送出時才等待目前動作完成。")
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(data["timeout_sec"])
        self.timeout_spin.setSuffix(" 秒")
        self.length_spin = QSpinBox()
        self.length_spin.setRange(1, 500)
        self.length_spin.setValue(data["max_reply_chars"])
        self.length_spin.setSuffix(" 字")
        for label, widget in (("檢查間隔", self.interval_spin), ("AI 等待上限", self.timeout_spin),
                              ("回覆長度上限", self.length_spin)):
            timing.addWidget(QLabel(label))
            timing.addWidget(widget)
        form.addRow(timing)
        body.addLayout(form)
        body.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("套用至腳本")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        fit_window_to_available_screen(self, 760, 600)

    def config(self) -> ChatReplyConfig:
        raw_region = self.region_edit.text().strip()
        return chat_config_from_dict({
            "enabled": self.enabled_check.isChecked(), "self_name": self.name_edit.text(),
            "reply_map": self.reply_map_check.isChecked(),
            "reply_whisper": self.reply_whisper_check.isChecked(),
            "auto_map_channel": True,
            "region": parse_int_list("聊天區域", raw_region, 4) if raw_region else None,
            "prompt": self.prompt_edit.toPlainText(), "interval_sec": self.interval_spin.value(),
            "timeout_sec": self.timeout_spin.value(), "max_reply_chars": self.length_spin.value(),
            "map_actions": [], "whisper_actions": []})

    def _update_channel_status(self) -> None:
        if not self.reply_map_check.isChecked() and not self.reply_whisper_check.isChecked():
            self.channel_status.setText("兩個頻道都未勾選：暫停自動回覆。")
        else:
            self.channel_status.setText("只回覆勾選的頻道；其他頻道的訊息僅供對話上下文參考。")

    def accept(self) -> None:
        try:
            self.config()
        except ScriptValidationError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _on_pick_region(self) -> None:
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.core.geometry import Point

        title, app = self._get_target_window().strip(), self._get_target_app().strip()
        if not title and not app:
            self.status_label.setText("請先在腳本編輯器指定目標視窗，再框選聊天區域")
            return
        try:
            wm = self._get_platform().window_manager
            windows = wm.find_windows(title_pattern=title or None, app_name=app or None)
            if not windows:
                raise ValueError("找不到目標視窗")
            if not wm.activate(windows[0]):
                raise ValueError("無法將目標視窗切到最上層")
            win = wm.refresh(windows[0])
            if win is None:
                raise ValueError("目標視窗已關閉")
            overlay = RegionPickerOverlay(self, capture_factory=self._capture_factory)
            self._overlay = overlay

            def on_selected(rect):
                try:
                    region = screen_rect_to_window_region(
                        rect, Point(win.x, win.y), drag_scale(overlay.devicePixelRatio()))
                    x, y, width, height = region
                    if x < 0 or y < 0 or x + width > win.width or y + height > win.height:
                        raise ValueError("請將聊天區域完整框選在目標視窗內")
                except ValueError as exc:
                    self.status_label.setText(str(exc))
                    return
                self.region_edit.setText(", ".join(map(str, region)))
                self.status_label.setText("已填入聊天區域")

            overlay.region_selected.connect(on_selected)
            overlay.open_fullscreen()
        except Exception as exc:
            self.status_label.setText(f"無法框選聊天區域：{exc}")
