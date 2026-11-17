"""One-region panel setup with explicit, lossless legacy-mode conversion."""
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)
from keyboard_executor.app.action_fields import parse_int_list
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.sequence_input_config import (
    SequenceInputConfig, sequence_config_from_dict, sequence_config_to_dict,
)


class SequenceInputDialog(QDialog):
    def __init__(self, config=None, parent=None, *, get_target_window=None, get_target_app=None,
                 get_platform=None, capture_factory=None, model_label=""):
        super().__init__(parent)
        self.setWindowTitle("圖片順序輸入")
        self._get_title = get_target_window or (lambda: "")
        self._get_app = get_target_app or (lambda: "")
        if get_platform is None:
            from keyboard_executor.platforms.factory import get_platform
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._get_platform, self._capture_factory = get_platform, capture_factory
        self._overlay = None
        config = config or SequenceInputConfig(mode="panel")
        self._mode = config.mode
        data = sequence_config_to_dict(config)
        body = QVBoxLayout(self)
        self.enabled_check = QCheckBox("執行此腳本時啟用圖片順序輸入")
        self.enabled_check.setChecked(config.enabled)
        body.addWidget(self.enabled_check)
        self.policy_label = QLabel()
        self.policy_label.setWordWrap(True)
        body.addWidget(self.policy_label)
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        body.addWidget(self.hint_label)
        self.model_label = QLabel(model_label or "沿用設定頁的 AI 供應商／圖片模型")
        body.addWidget(self.model_label)

        self.panel_widget = QWidget()
        panel_form = QFormLayout(self.panel_widget)
        panel_row = QHBoxLayout()
        self.panel_edit = QLineEdit()
        self.panel_edit.setPlaceholderText("框選完整提示、輪播圖片、輸入框及確認按鈕")
        panel_row.addWidget(self.panel_edit, 1)
        self.panel_button = QPushButton("框選完整面板")
        self.panel_button.clicked.connect(lambda: self._pick("panel_region"))
        panel_row.addWidget(self.panel_button)
        panel_form.addRow("完整面板區域", panel_row)
        body.addWidget(self.panel_widget)
        self.manual_widget = QWidget()
        form = QFormLayout(self.manual_widget)
        self.prompt_edit = QLineEdit(config.prompt_text)
        form.addRow("提示文字", self.prompt_edit)
        self._manual_edits = {}
        for name, label in (("prompt_region", "提示文字區域"), ("image_region", "輪播圖片區域"),
                            ("input_point", "輸入框位置"), ("confirm_point", "確認按鈕位置")):
            row = QHBoxLayout()
            value = data.get(name)
            field = QLineEdit(", ".join(map(str, value)) if value is not None else "")
            field.setPlaceholderText("x, y, 寬, 高" if name.endswith("region") else "x, y")
            self._manual_edits[name] = field
            row.addWidget(field, 1)
            button = QPushButton("框選" if name.endswith("region") else "取點")
            button.clicked.connect(lambda checked=False, key=name: self._pick(key))
            row.addWidget(button)
            form.addRow(label, row)
        self.convert_button = QPushButton("改用單一框選")
        self.convert_button.clicked.connect(lambda: self._pick("panel_region"))
        form.addRow(self.convert_button)
        body.addWidget(self.manual_widget)
        if config.panel_region is not None:
            self.panel_edit.setText(", ".join(map(str, config.panel_region)))
        self._show_mode()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        body.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        fit_window_to_available_screen(self, 660, 480)

    def _show_mode(self):
        panel = self._mode == "panel"
        self.panel_widget.setVisible(panel)
        self.manual_widget.setVisible(not panel)
        self.coordinate_edits = {"panel_region": self.panel_edit} if panel else self._manual_edits
        prefix = "OCR 偵測 → AI 辨識。" if panel else "舊版手動設定。"
        self.policy_label.setText(prefix + "每秒截圖；18 秒前準備輸入；20 秒前確認；驗證消失總上限 30 秒；確認只點一次；逾時停止。")
        if panel:
            self.hint_label.setText(
                "只需框選整個面板，包含提示、輪播字元與編號、輸入框及確認按鈕。\n"
                "平常只用本機 OCR；偵測到提示才送 AI，並同時傳 Discord 文字通知（沿用設定頁 Webhook）。\n"
                "依 1→2→3 輸入 ASCII 英數字。請保持目標視窗前景且無遮擋。\n"
                "OCR 漏讀可能不觸發；AI 辨識可能產生用量，無法保證每次在時限內成功。")
        else:
            self.hint_label.setText(
                "此腳本保留舊版手動座標及提示文字。可按「改用單一框選」轉換，取消框選不會改變設定。\n"
                "舊模式啟動時檢查 AI 圖片能力（最多10秒，可能產生用量）；保持目標視窗前景且無遮擋。")

    def set_region(self, kind, region):
        if kind == "panel":
            config = sequence_config_from_dict(dict(enabled=self.enabled_check.isChecked(), mode="panel", panel_region=region))
            self.panel_edit.setText(", ".join(map(str, config.panel_region)))
            self._mode = "panel"
            self._show_mode()
        else:
            self.coordinate_edits[kind + "_region"].setText(", ".join(map(str, region)))

    def set_point(self, kind, point):
        self.coordinate_edits[kind + "_point"].setText(", ".join(map(str, point)))

    def config(self):
        if self._mode == "panel":
            text = self.panel_edit.text().strip()
            return sequence_config_from_dict(dict(enabled=self.enabled_check.isChecked(), mode="panel",
                panel_region=parse_int_list("panel_region", text, 4) if text else None))
        data = dict(enabled=self.enabled_check.isChecked(), prompt_text=self.prompt_edit.text())
        for name, edit in self.coordinate_edits.items():
            text = edit.text().strip()
            data[name] = parse_int_list(name, text, 4 if name.endswith("region") else 2) if text else None
        return sequence_config_from_dict(data)

    def accept(self):
        try:
            self.config()
        except (ScriptValidationError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _pick(self, name):
        from keyboard_executor.app.region_math import screen_rect_to_window_region, screen_point_to_window_point
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.app.point_picker import PointPickerOverlay
        from keyboard_executor.core.geometry import Point
        title, app = self._get_title().strip(), self._get_app().strip()
        if not title and not app:
            self.status_label.setText("請先在腳本編輯器指定目標視窗")
            return
        try:
            wm = self._get_platform().window_manager
            windows = wm.find_windows(title_pattern=title or None, app_name=app or None)
            if not windows or not wm.activate(windows[0]):
                raise ValueError("找不到或無法啟用目標視窗")
            win = wm.refresh(windows[0])
            if win is None:
                raise ValueError("目標視窗已關閉")
            origin = Point(win.x, win.y)
            def save(values):
                fresh = wm.refresh(win)
                if fresh is None or (fresh.x, fresh.y, fresh.width, fresh.height) != (win.x, win.y, win.width, win.height):
                    self.status_label.setText("目標視窗已改變，請重新框選")
                    return
                x, y = values[:2]
                w, h = values[2:] if len(values) == 4 else (1, 1)
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > win.width or y+h > win.height:
                    self.status_label.setText("請在目標視窗範圍內選取")
                    return
                if name == "panel_region":
                    self.set_region("panel", values)
                else:
                    self.coordinate_edits[name].setText(", ".join(map(str, values)))
                self.status_label.setText("已填入視窗相對座標")
            if name.endswith("region"):
                overlay = RegionPickerOverlay(self, capture_factory=self._capture_factory)
                def selected(rect):
                    try:
                        save(screen_rect_to_window_region(rect, origin, drag_scale(overlay.devicePixelRatio())))
                    except ValueError as exc:
                        self.status_label.setText(str(exc))
                overlay.region_selected.connect(selected)
            else:
                convert = lambda x, y: screen_point_to_window_point(x, y, origin, drag_scale(overlay.devicePixelRatio()))
                overlay = PointPickerOverlay(self._capture_factory, to_window=convert, parent=self)
                overlay.point_picked.connect(lambda x, y: save(convert(x, y)))
            self._overlay = overlay
            overlay.cancelled.connect(lambda: self.status_label.setText("已取消選取，保留原設定"))
            overlay.open_fullscreen()
        except Exception as exc:
            self.status_label.setText(f"無法選取：{exc}")
