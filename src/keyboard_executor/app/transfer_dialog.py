"""匯出／匯入對話框：勾選要帶走的腳本與規則，或從匯出檔還原。

薄件：相依解析在 core/transfer、讀寫在 storage/transfer.TransferService，這裡只負責
勾選、選檔與詢問覆蓋。

兩個刻意的設計：
- 勾選後即時顯示「實際會匯出什麼」。使用者勾 1 支腳本，可能因為 run_script 而帶進
  第 2 支、因為圖像動作而帶進幾張圖——這要在按下匯出前就看得到。
- 匯入遇到同名一律先問。來源是別人給的檔案，靜默覆蓋等於弄丟使用者自己的腳本。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.storage.transfer import TransferService

_FILTER = "Keyboard Executor 匯出檔 (*.json);;所有檔案 (*)"


def _checkable_list() -> QListWidget:
    widget = QListWidget()
    widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    widget.setUniformItemSizes(True)
    return widget


def _fill(widget: QListWidget, names) -> None:
    widget.clear()
    for name in names:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)      # 預設全選
        widget.addItem(item)


def _checked(widget: QListWidget) -> list[str]:
    return [widget.item(i).text() for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked]


def _set_all(widget: QListWidget, state: Qt.CheckState) -> None:
    for i in range(widget.count()):
        widget.item(i).setCheckState(state)


class TransferDialog(QDialog):
    def __init__(self, script_storage, rule_storage, template_store, *,
                 service_factory=TransferService, parent=None):
        super().__init__(parent)
        self._scripts = script_storage
        self._rules = rule_storage
        self._service = service_factory(script_storage, rule_storage, template_store)
        self.setWindowTitle("匯出／匯入")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "勾選要匯出的項目，相依的模板圖片與被呼叫的腳本會自動一併帶上。"))

        layout.addWidget(QLabel("腳本"))
        self.script_list = _checkable_list()
        layout.addWidget(self.script_list, stretch=1)
        layout.addWidget(QLabel("規則"))
        self.rule_list = _checkable_list()
        layout.addWidget(self.rule_list, stretch=1)

        select_row = QHBoxLayout()
        self.select_all_button = QPushButton("全選")
        self.select_none_button = QPushButton("全不選")
        select_row.addWidget(self.select_all_button)
        select_row.addWidget(self.select_none_button)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        self.plan_label.setObjectName("detail")
        layout.addWidget(self.plan_label)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("從檔案匯入…")
        self.export_button = QPushButton("匯出選取項目…")
        self.export_button.setProperty("variant", "primary")
        self.close_button = QPushButton("關閉")
        buttons.addWidget(self.import_button)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.select_all_button.clicked.connect(
            lambda: self._set_all_and_refresh(Qt.CheckState.Checked))
        self.select_none_button.clicked.connect(
            lambda: self._set_all_and_refresh(Qt.CheckState.Unchecked))
        self.script_list.itemChanged.connect(self._refresh_plan)
        self.rule_list.itemChanged.connect(self._refresh_plan)
        self.export_button.clicked.connect(self._on_export)
        self.import_button.clicked.connect(self._on_import)
        self.close_button.clicked.connect(self.reject)

        self.reload()
        fit_window_to_available_screen(self, 560, 560)

    def reload(self) -> None:
        _fill(self.script_list, self._script_names())
        _fill(self.rule_list, self._rule_names())
        self._refresh_plan()

    def _script_names(self):
        return self._scripts.list_names()

    def _rule_names(self):
        return self._rules.list_names()

    def _set_all_and_refresh(self, state) -> None:
        for widget in (self.script_list, self.rule_list):
            _set_all(widget, state)
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        """即時反映「實際會匯出什麼」，含自動帶上的相依與缺漏警告。"""
        scripts, rules = _checked(self.script_list), _checked(self.rule_list)
        if not scripts and not rules:
            self.plan_label.setText("尚未勾選任何項目")
            self.export_button.setEnabled(False)
            return
        self.export_button.setEnabled(True)
        try:
            plan = self._service.plan(scripts, rules)
        except ScriptValidationError as e:
            self.plan_label.setText(f"無法解析相依項目：{e}")
            return
        extra = len(plan.scripts) - len(scripts)
        parts = [f"將匯出 {len(plan.scripts)} 支腳本"
                 + (f"（含 {extra} 支被呼叫的）" if extra > 0 else ""),
                 f"{len(plan.rules)} 條規則",
                 f"{len(plan.templates)} 張模板圖片"]
        text = "、".join(parts)
        if plan.missing_scripts:
            text += f"\n⚠ 找不到被引用的腳本：{'、'.join(plan.missing_scripts)}"
        if plan.missing_templates:
            text += f"\n⚠ 找不到被引用的模板：{'、'.join(plan.missing_templates)}"
        self.plan_label.setText(text)

    # --- 匯出 ---

    def _ask_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出為", "keyboard-executor-匯出.json", _FILTER)
        return path

    def _on_export(self) -> None:
        scripts, rules = _checked(self.script_list), _checked(self.rule_list)
        if not scripts and not rules:
            self.status_label.setText("請至少勾選一個項目")
            return
        path = self._ask_save_path()
        if not path:
            return
        try:
            summary = self._service.export(path, scripts, rules)
        except ScriptValidationError as e:
            self.status_label.setText(f"匯出失敗：{e}")
            return
        text = (f"已匯出到 {summary.path}："
                f"{len(summary.scripts)} 支腳本、{len(summary.rules)} 條規則、"
                f"{len(summary.templates)} 張模板圖片")
        if summary.has_warnings:
            missing = summary.missing_scripts + summary.missing_templates
            text += f"\n⚠ 下列被引用的項目不存在，未包含在匯出檔中：{'、'.join(missing)}"
        self.status_label.setText(text)

    # --- 匯入 ---

    def _ask_open_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "選擇匯入檔", "", _FILTER)
        return path

    def _confirm_overwrite(self, conflicts) -> bool:
        """回傳是否覆蓋同名項目；使用者選「否」則保留現有、只匯入不衝突的部分。"""
        names = "、".join(conflicts.all_names[:12])
        if len(conflicts.all_names) > 12:
            names += f"… 等 {len(conflicts.all_names)} 項"
        answer = QMessageBox.question(
            self, "已有同名項目",
            f"下列項目在你的資料裡已經存在：\n\n{names}\n\n"
            "要用匯入檔的版本覆蓋它們嗎？\n選「否」則保留你現有的版本，只匯入其餘項目。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _on_import(self) -> None:
        path = self._ask_open_path()
        if not path:
            return
        try:
            bundle = self._service.read(path)
        except ScriptValidationError as e:
            self.status_label.setText(f"匯入失敗：{e}")
            return
        conflicts = self._service.conflicts(bundle)
        overwrite = set(conflicts.all_names) if (
            conflicts and self._confirm_overwrite(conflicts)) else set()
        summary = self._service.apply(bundle, overwrite=overwrite)

        text = (f"已匯入 {len(summary.scripts)} 支腳本、{len(summary.rules)} 條規則、"
                f"{len(summary.templates)} 張模板圖片")
        if summary.skipped:
            text += f"\n略過同名項目：{'、'.join(summary.skipped)}"
        if summary.failed:
            text += f"\n⚠ 下列項目匯入失敗：{'、'.join(summary.failed)}"
        if summary.missing_templates:
            text += (f"\n⚠ 匯入檔沒有附上這些模板圖片，相關圖像判斷會失效："
                     f"{'、'.join(summary.missing_templates)}")
        self.status_label.setText(text)
        self.reload()
