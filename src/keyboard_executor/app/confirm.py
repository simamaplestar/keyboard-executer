"""繁中刪除確認對話框（共用薄件）。Qt 內建 StandardButton（Yes/No）在未載
qtbase 翻譯時是英文（M4 待辦 #9）——刪除確認直接自建繁中按鈕，雙保險；
qtbase_zh_TW translator 另於 build_app 載入，涵蓋其餘內建對話框。"""
from __future__ import annotations


def confirm_delete(parent, message: str) -> bool:
    """回傳使用者是否按下「刪除」。thin：實機外觀列人工驗收。"""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("確認刪除")
    box.setText(message)
    delete_button = box.addButton("刪除", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is delete_button
