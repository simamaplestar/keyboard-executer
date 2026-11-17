"""規則編輯器（spec §9）：條件（文字/圖像）、區域、間隔、冷卻、觸發、啟用。

薄件：狀態與驗證在 RuleEditorModel；本檔只做表單接線。錯誤/結果顯示在
status_label（非 modal，可測）。pick_region_button 由 Task 7 接上區域框選器。"""
from __future__ import annotations

import colorsys
import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.action_fields import choice_label
from keyboard_executor.app.template_preview import TemplatePreview
from keyboard_executor.app.window_sizing import fit_window_to_available_screen

_PREVIEW_SIZE = (200, 150)   # 規則編輯器內的模板預覽上限；夠看清楚又不撐長表單
from keyboard_executor.core.models import ScriptValidationError


def _fill_choice(combo, values, current):
    """填充下拉：顯示繁中（choice_label）、userData 存原值，並選到 current。"""
    for v in values:
        combo.addItem(choice_label(v), v)
    i = combo.findData(current)
    if i >= 0:
        combo.setCurrentIndex(i)


class RuleEditorDialog(QDialog):
    def __init__(self, model, rule_storage, template_store=None, parent=None,
                 get_platform=None, capture_factory=None,
                 window_lister=None, script_names=None):
        super().__init__(parent)
        self._model = model
        self._storage = rule_storage
        self._template_store = template_store
        self._overlay = None
        self._window_lister = window_lister      # 跟腳本編輯器一致：可從開啟視窗挑選
        self._script_names = script_names        # 觸發腳本名稱改用下拉挑選
        self._windows = []
        if get_platform is None:
            from keyboard_executor.platforms.factory import get_platform as _real_get_platform
            get_platform = _real_get_platform
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._get_platform = get_platform          # M4 待辦 #8：注入取代直接建構
        self._capture_factory = capture_factory
        self.setWindowTitle("規則編輯器")
        self.setMinimumSize(420, 320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._form_page = QWidget()
        layout = QFormLayout(self._form_page)
        self._scroll.setWidget(self._form_page)
        outer.addWidget(self._scroll)
        self._form = layout          # 供依條件類型切換輸入欄位顯示（_update_condition_fields）

        self.name_edit = QLineEdit(model.name)
        layout.addRow("規則名稱", self.name_edit)

        # 目標視窗：跟腳本編輯器一致——從開啟中的視窗挑選，或手動填 regex/app 名稱
        pick = QHBoxLayout()
        self.window_combo = QComboBox()
        self.refresh_windows_button = QPushButton("重新整理")
        self.use_window_button = QPushButton("用此視窗")
        pick.addWidget(self.window_combo, 1)
        pick.addWidget(self.refresh_windows_button)
        pick.addWidget(self.use_window_button)
        pick_container = QWidget()
        pick_container.setLayout(pick)
        layout.addRow("目標視窗", pick_container)

        self.title_edit = QLineEdit(model.title_pattern)
        layout.addRow("視窗標題（regex）", self.title_edit)
        self.app_edit = QLineEdit(model.app_name)
        layout.addRow("應用程式名稱", self.app_edit)
        self.region_edit = QLineEdit(model.region_text)
        layout.addRow("區域 x, y, w, h（留空＝整個視窗）", self.region_edit)
        self.pick_region_button = QPushButton("框選區域…")
        layout.addRow("", self.pick_region_button)
        self.capture_template_button = QPushButton("框選並擷取模板…")
        layout.addRow("", self.capture_template_button)

        self.condition_combo = QComboBox()
        _fill_choice(self.condition_combo, ["text", "image", "color"],
                     model.condition_type)
        layout.addRow("條件類型", self.condition_combo)
        self.pattern_edit = QLineEdit(model.pattern)
        layout.addRow("文字 pattern", self.pattern_edit)
        self.mode_combo = QComboBox()
        _fill_choice(self.mode_combo, ["contains", "regex"], model.mode)
        layout.addRow("文字比對模式", self.mode_combo)
        self.template_edit = QLineEdit(model.template)
        layout.addRow("圖像模板名稱", self.template_edit)
        # 預覽讓「名稱打錯一個字」當場現形——否則要等監看跑起來、靜默比對不到才發現。
        # 沒有 template_store（單元測試的精簡建構）時不建立此列。
        self.template_preview = (
            TemplatePreview(self._template_store, max_size=_PREVIEW_SIZE)
            if self._template_store is not None else None)
        if self.template_preview is not None:
            layout.addRow("模板預覽", self.template_preview)
        self.threshold_edit = QLineEdit(model.threshold)
        layout.addRow("模板閾值 (0, 1]", self.threshold_edit)

        color_row = QHBoxLayout()
        self.pick_color_button = QPushButton("滴管取色…")
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(18, 18)
        self.color_value_label = QLabel("尚未取樣")
        color_row.addWidget(self.pick_color_button)
        color_row.addWidget(self.color_swatch)
        color_row.addWidget(self.color_value_label, 1)
        self._color_container = QWidget()
        self._color_container.setLayout(color_row)
        layout.addRow("顏色（滴管）", self._color_container)
        self.hue_tol_edit = QLineEdit(model.hue_tol)
        layout.addRow("容差（色相）", self.hue_tol_edit)
        self.min_pixels_edit = QLineEdit(model.min_pixels)
        layout.addRow("最少像素", self.min_pixels_edit)
        self.detect_combo = QComboBox()
        self.detect_combo.addItem("出現時", False)
        self.detect_combo.addItem("消失時", True)
        di = self.detect_combo.findData(model.absent)
        if di >= 0:
            self.detect_combo.setCurrentIndex(di)
        layout.addRow("偵測", self.detect_combo)

        self.interval_edit = QLineEdit(model.interval_sec)
        layout.addRow("輪詢間隔（秒）", self.interval_edit)
        self.cooldown_edit = QLineEdit(model.cooldown_sec)
        layout.addRow("冷卻（秒）", self.cooldown_edit)

        self.notify_check = QCheckBox("顯示通知")
        self.notify_check.setChecked(model.notify_enabled)
        self.stop_all_check = QCheckBox("全部停止")
        self.stop_all_check.setChecked(model.stop_all_enabled)
        self.run_script_check = QCheckBox("執行腳本")
        self.run_script_check.setChecked(model.run_script_enabled)
        trig_box = QVBoxLayout()
        trig_box.addWidget(self.notify_check)
        trig_box.addWidget(self.stop_all_check)
        trig_box.addWidget(self.run_script_check)
        trig_container = QWidget()
        trig_container.setLayout(trig_box)
        layout.addRow("觸發動作", trig_container)
        self.script_edit = QComboBox()
        self._populate_scripts(model.script_name)
        layout.addRow("觸發腳本名稱", self.script_edit)
        self.message_edit = QLineEdit(model.message)
        layout.addRow("通知訊息", self.message_edit)
        self.attach_screenshot_check = QCheckBox("附上辨識截圖到 Discord 通知")
        self.attach_screenshot_check.setChecked(model.attach_screenshot)
        layout.addRow("", self.attach_screenshot_check)

        self.enabled_check = QCheckBox("啟用")
        self.enabled_check.setChecked(model.enabled)
        layout.addRow("", self.enabled_check)

        self.save_button = QPushButton("儲存")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._on_save)
        layout.addRow(self.save_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addRow(self.status_label)

        self.pick_region_button.clicked.connect(self._on_pick_region)
        self.capture_template_button.clicked.connect(self._on_capture_template)
        if self.template_preview is not None:
            # 邊打邊更新：擷取新模板後 setText 也會走到這裡，預覽自動跟上
            self.template_edit.textChanged.connect(self.template_preview.show_template)
            self.template_preview.show_template(self.template_edit.text())
        self.refresh_windows_button.clicked.connect(self._refresh_windows)
        self.use_window_button.clicked.connect(self._use_selected_window)
        self._refresh_windows()

        self._picked_hsv = (_safe_int(model.hue), _safe_int(model.sat),
                            _safe_int(model.val))
        # 只有真的用滴管取過色（或載入既有 color 規則）才算已取樣；避免使用者選了
        # 「顏色」卻沒取色就存，用預設 (0,0,0) 造成廣泛誤命中。
        self._color_sampled = model.condition_type == "color"
        if model.condition_type == "color":
            h, s, v = self._picked_hsv
            self.color_value_label.setText(f"H={h} S={s} V={v}")
            self.color_swatch.setStyleSheet(_swatch_qss(h, s, v))
        self.pick_color_button.clicked.connect(self._on_pick_color)
        # 依條件類型只顯示對應輸入欄位（減少雜訊）；選類型時即時切換
        self.condition_combo.currentIndexChanged.connect(self._update_condition_fields)
        self._update_condition_fields()
        fit_window_to_available_screen(self, 640, 720)

    def _update_condition_fields(self, *_ignored) -> None:
        """只顯示目前條件類型需要的輸入欄位（文字/圖像/顏色互斥），其餘隱藏。
        共用欄位（名稱、視窗、區域、間隔、冷卻、觸發）不受影響。"""
        ctype = self.condition_combo.currentData()
        for w in (self.pattern_edit, self.mode_combo):
            self._form.setRowVisible(w, ctype == "text")
        image_rows = [self.template_edit, self.threshold_edit,
                      self.capture_template_button]
        if self.template_preview is not None:
            image_rows.append(self.template_preview)
        for w in image_rows:
            self._form.setRowVisible(w, ctype == "image")
        for w in (self._color_container, self.hue_tol_edit, self.min_pixels_edit):
            self._form.setRowVisible(w, ctype == "color")
        self._form.setRowVisible(self.detect_combo, True)   # 三種條件都顯示「偵測」

    def _populate_scripts(self, current: str) -> None:
        """觸發腳本名稱下拉：填入現有腳本名稱；保留既有值（載入舊規則不遺失）。"""
        try:
            names = list(self._script_names()) if self._script_names else []
        except Exception:
            names = []
        if current and current not in names:
            names = [current] + names
        self.script_edit.clear()
        self.script_edit.addItems(names)
        i = self.script_edit.findText(current)
        if i >= 0:
            self.script_edit.setCurrentIndex(i)

    def _refresh_windows(self) -> None:
        """列出開啟中、有標題的視窗供挑選（無 lister 時清單留空）。"""
        try:
            wins = list(self._window_lister()) if self._window_lister else []
        except Exception:
            wins = []
        self._windows = [w for w in wins if getattr(w, "title", "").strip()]
        self.window_combo.clear()
        self.window_combo.addItems(
            [f"{w.title}（{w.app_name}）" for w in self._windows])

    def _use_selected_window(self) -> None:
        i = self.window_combo.currentIndex()
        if 0 <= i < len(self._windows):
            w = self._windows[i]
            # 標題欄是 regex（re.search）；視窗標題常含 () 等特殊字元，直接填會被當成
            # 群組而配不到自己的視窗。escape 成字面比對（鏡射 recorder_session 的策略）。
            self.title_edit.setText(re.escape(w.title))
            self.app_edit.setText(w.app_name)

    def _apply_to_model(self) -> None:
        m = self._model
        m.name = self.name_edit.text()
        m.title_pattern = self.title_edit.text()
        m.app_name = self.app_edit.text()
        m.region_text = self.region_edit.text()
        m.condition_type = self.condition_combo.currentData()
        m.pattern = self.pattern_edit.text()
        m.mode = self.mode_combo.currentData()
        m.template = self.template_edit.text()
        m.threshold = self.threshold_edit.text()
        h, s, v = self._picked_hsv
        m.hue, m.sat, m.val = str(h), str(s), str(v)
        m.hue_tol = self.hue_tol_edit.text()
        m.min_pixels = self.min_pixels_edit.text()
        m.absent = self.detect_combo.currentData()
        m.interval_sec = self.interval_edit.text()
        m.cooldown_sec = self.cooldown_edit.text()
        m.notify_enabled = self.notify_check.isChecked()
        m.stop_all_enabled = self.stop_all_check.isChecked()
        m.run_script_enabled = self.run_script_check.isChecked()
        m.script_name = self.script_edit.currentText()
        m.message = self.message_edit.text()
        m.attach_screenshot = self.attach_screenshot_check.isChecked()
        m.enabled = self.enabled_check.isChecked()

    def _on_save(self) -> None:
        if self.condition_combo.currentData() == "color" and not self._color_sampled:
            self.status_label.setText("請先用滴管取色，再儲存顏色規則")
            return
        self._apply_to_model()
        try:
            rule = self._model.to_rule()
            path = self._storage.save(rule)
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")
            return
        old = self._model.original_name
        if old and old != rule.name:
            # 編輯既有規則且改了名 → 刪掉舊名那條，才是「同一條改名」而非新增一條。
            try:
                self._storage.delete(old)
            except ScriptValidationError:
                pass                       # 舊檔已不在也無妨
        self._model.original_name = rule.name   # 之後在同一視窗再存以新名為準
        self.status_label.setText(f"已儲存：{path}")
        self.accept()                       # 儲存成功 → 自動關閉

    def _on_pick_region(self) -> None:
        """框選螢幕區域 → 換算目標視窗相對 region 填入欄位（人工驗收）。"""
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.core.geometry import Point

        win = self._activate_target_window(required=True)
        if win is None:
            return
        overlay = RegionPickerOverlay(
            self, capture_factory=self._capture_factory)  # 凍結已置頂的目標畫面
        self._overlay = overlay                       # 保留引用避免被 GC

        def on_selected(rect) -> None:
            scale = drag_scale(overlay.devicePixelRatio())
            try:
                region = screen_rect_to_window_region(rect, Point(win.x, win.y),
                                                      scale)
            except ValueError as e:
                self.status_label.setText(str(e))
                return
            self.region_edit.setText(", ".join(str(v) for v in region))
            self.status_label.setText("已填入框選區域")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()

    def _ask_template_name(self) -> str | None:
        """thin：實機 QInputDialog（人工驗收）；取消或空白回 None。"""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "模板名稱", "輸入模板名稱")
        if not ok or not name.strip():
            return None
        return name.strip()

    def _on_pick_color(self) -> None:
        """開滴管覆蓋層取樣目標顏色。"""
        from keyboard_executor.app.color_picker import ColorPickerOverlay

        # 已指定目標視窗：先切到最上層再凍結畫面取色（同框選、擷取模板）。
        if self.title_edit.text().strip() and self._activate_target_window() is None:
            return
        overlay = ColorPickerOverlay(self._capture_factory, self)  # 以對話框為 parent
        self._overlay = overlay
        overlay.color_picked.connect(self._on_color_picked)
        overlay.open_fullscreen()

    def _on_color_picked(self, h: int, s: int, v: int) -> None:
        self._picked_hsv = (h, s, v)
        self._color_sampled = True
        self.color_value_label.setText(f"H={h} S={s} V={v}")
        self.color_swatch.setStyleSheet(_swatch_qss(h, s, v))

    def _on_capture_template(self) -> None:
        """框選並擷取模板 PNG 存入 TemplateStore（人工驗收）。"""
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.app.template_capture import capture_template
        from keyboard_executor.core.geometry import Rect

        if self._template_store is None:
            self.status_label.setText("未提供模板儲存位置，無法擷取")
            return
        # 已指定目標視窗時，先還原／切到最上層再蓋框選遮罩；新規則尚未指定視窗時
        # 仍保留原本可直接擷取任意畫面的流程。
        if self.title_edit.text().strip() and self._activate_target_window() is None:
            return
        overlay = RegionPickerOverlay(
            self, capture_factory=self._capture_factory)  # 凍結已置頂的目標畫面
        self._overlay = overlay

        def on_selected(rect) -> None:
            name = self._ask_template_name()
            if name is None:
                return
            try:
                frozen = overlay.captured_region(rect)
                if frozen is not None:
                    # 直接裁開遮罩前凍結的畫面，避免 overlay 關閉時編輯器先搶回
                    # 前景，導致模板其實截到 Keyboard Executor 本身。
                    path = self._template_store.save_template(name, frozen)
                else:
                    scale = drag_scale(overlay.devicePixelRatio())
                    points = Rect(round(rect.x * scale), round(rect.y * scale),
                                  round(rect.width * scale), round(rect.height * scale))
                    path = capture_template(self._capture_factory(), self._template_store,
                                            name, points)
            except ScriptValidationError as e:
                self.status_label.setText(f"模板儲存失敗：{e}")
                return
            self.template_edit.setText(name)
            self.status_label.setText(f"已儲存模板：{path}")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()

    def _activate_target_window(self, *, required: bool = False):
        """依表單條件找到並切前景；失敗時顯示原因且不開框選遮罩。"""
        title = self.title_edit.text().strip()
        if not title:
            if required:
                self.status_label.setText("請先填視窗標題（regex）再框選")
            return None
        app_name = self.app_edit.text().strip() or None
        try:
            wm = self._get_platform().window_manager
            windows = wm.find_windows(title_pattern=title, app_name=app_name)
        except Exception as e:
            self.status_label.setText(f"無法尋找目標視窗：{e}")
            return None
        if not windows:
            self.status_label.setText(f"找不到符合 {title!r} 的視窗")
            return None
        win = windows[0]
        try:
            active = wm.activate(win)
        except Exception as e:
            self.status_label.setText(f"無法將目標視窗切到最上層：{e}")
            return None
        if not active:
            self.status_label.setText("無法將目標視窗切到最上層，請確認視窗未被系統阻擋")
            return None
        return win


def _swatch_qss(h: int, s: int, v: int) -> str:
    """OpenCV HSV（H 0–179）→ QSS 背景色。"""
    r, g, b = colorsys.hsv_to_rgb(h / 179.0, s / 255.0, v / 255.0)
    return (f"background:rgb({int(r * 255)},{int(g * 255)},{int(b * 255)});"
            " border:1px solid #888;")


def _safe_int(text: str) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0
