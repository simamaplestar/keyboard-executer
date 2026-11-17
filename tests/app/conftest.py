"""app 層測試共用基座：強制 Qt offscreen（無頭），提供 session 級 QApplication。

QT_QPA_PLATFORM 必須在第一次 import PySide6 widgets 前設定，故放在 conftest
模組層（pytest 收集 tests/app/ 時先 import 本檔）。fixture 只在 tests/app/
範圍可見，不影響既有非 GUI 測試。不引入 pytest-qt：測試直接呼叫 slot、
設值、發 signal、檢查 model 狀態。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
