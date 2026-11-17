"""GUI 應用組裝：QApplication 建立、macOS 權限檢查、主視窗組裝。"""
from __future__ import annotations

import sys


def default_permission_checks():
    """darwin 三權限檢查（輔助使用/螢幕錄製/輸入監控）；非 darwin 回傳空 dict。
    sys.platform 判斷沿用 cli._check_darwin_permissions 的已核准例外模式。"""
    if sys.platform != "darwin":
        return {}
    from keyboard_executor.platforms.darwin.permissions import (
        ACCESSIBILITY_GUIDE,
        INPUT_MONITORING_GUIDE,
        SCREEN_RECORDING_GUIDE,
        check_accessibility,
        check_input_monitoring,
        check_screen_recording,
    )

    return {
        "輔助使用": (check_accessibility, ACCESSIBILITY_GUIDE),
        "螢幕錄製": (check_screen_recording, SCREEN_RECORDING_GUIDE),
        "輸入監控": (check_input_monitoring, INPUT_MONITORING_GUIDE),
    }


def collect_permission_warnings(checks=None) -> list[str]:
    """回傳缺失權限的繁中引導文字清單（純邏輯，checks 注入供測試）。
    個別檢查拋例外時視同缺失——保守提示使用者，不讓啟動崩潰（spec §10）。"""
    checks = checks if checks is not None else default_permission_checks()
    warnings = []
    for _name, (check, guide) in checks.items():
        try:
            ok = check()
        except Exception:
            ok = False
        if not ok:
            warnings.append(guide)
    return warnings


_PANE_BY_PERMISSION = {"輔助使用": "accessibility",
                       "螢幕錄製": "screen-recording",
                       "輸入監控": "input-monitoring"}


def settings_urls_for_missing(checks=None) -> list[str]:
    """缺失權限 → 直達系統設定的 deep-link URL 清單（spec §10「附直達系統設定
    的連結」）。checks 注入供測試；darwin 權限模組頂層無 pyobjc import，
    跨平台可安全 import。未知權限名稱略過；check 拋例外視同缺失。"""
    from keyboard_executor.platforms.darwin.permissions import system_settings_url

    checks = checks if checks is not None else default_permission_checks()
    urls = []
    for name, (check, _guide) in checks.items():
        try:
            ok = check()
        except Exception:
            ok = False
        if not ok and name in _PANE_BY_PERMISSION:
            urls.append(system_settings_url(_PANE_BY_PERMISSION[name]))
    return urls


def request_missing_permissions(requesters=None) -> None:
    """啟動時主動觸發 macOS 授權對話框（M4 待辦 #3：打包後的 .app 藉此出現在
    系統設定清單）。requesters 注入供測試；預設 darwin 為 AX 與兩個 CGRequest 包裝、
    非 darwin no-op（sys.platform 沿用 cli._check_darwin_permissions 已核准
    例外模式）。個別請求失敗不阻斷啟動（spec §10 報錯不崩潰）。"""
    if requesters is None:
        if sys.platform != "darwin":
            return
        from keyboard_executor.platforms.darwin.permissions import (
            request_accessibility,
            request_input_monitoring,
            request_screen_recording,
        )

        requesters = (request_accessibility, request_screen_recording, request_input_monitoring)
    for request in requesters:
        try:
            request()
        except Exception:
            pass  # 權限請求失敗只影響引導體驗，不可讓啟動崩潰


def default_update_exe():
    """可自動更新的 EXE 路徑：只有 Windows 打包版（PyInstaller frozen）才有；否則 None。"""
    from pathlib import Path
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable)
    return None


def build_app(argv=None, *, data_dir=None, permission_checks=None, request_permissions=None):
    """建立（或重用）QApplication 與主視窗：權限請求、載入設定、日誌、權限檢查、全接線。"""
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from keyboard_executor.app.main_window import MainWindow
    from keyboard_executor.app.qt_log_handler import attach_gui_handler
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.cli import default_scripts_dir
    from keyboard_executor.core.logging_config import setup_logging

    app = QApplication.instance() or QApplication(list(argv) if argv else [])
    from keyboard_executor.app.theme import DARK_QSS
    app.setStyleSheet(DARK_QSS)   # 固定深色主題（主視窗與所有對話框一致）
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    translator = QTranslator(app)
    if translator.load(QLocale("zh_TW"), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)   # 內建對話框（開檔、訊息框標準鈕）轉繁中
    if request_permissions is None:
        request_permissions = request_missing_permissions
    request_permissions()   # 先請求（觸發 TCC 對話框），再檢查、顯示引導橫幅
    directory = Path(data_dir) if data_dir is not None else default_scripts_dir()
    settings = SettingsStore(directory).load()
    setup_logging(directory / "logs", level=settings.log_level)
    update_exe = default_update_exe()   # 上次更新留下的 <exe>.old 由更新控制器延後清理
    window = MainWindow(
        directory, settings=settings, update_exe=update_exe,
        permission_warnings=collect_permission_warnings(permission_checks),
        permission_checks=permission_checks)
    # GUI 日誌橋：logger 記錄（含 Worker QThread 內的）同步進日誌面板（spec §10）。
    # 存為公開屬性，closeEvent 收尾時 detach，避免對已銷毀 widget 投遞。
    window.gui_log_handler = attach_gui_handler(window.append_log,
                                                level=settings.log_level)
    return app, window
