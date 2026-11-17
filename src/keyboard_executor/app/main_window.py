"""主視窗（spec §9）：左側腳本/規則清單、右側摘要＋執行控制、下方即時日誌。

Task 2 建立完整版面骨架與所有頂層 widget 屬性（跨任務契約）；行為接線由
Task 4（腳本清單/回放/日誌）、Task 8（監看/錄製/設定/規則清單）逐步接上。
QWidget 保持「薄」：狀態與轉換一律在純 Python controller，版面列人工驗收。"""
from __future__ import annotations

import dataclasses
import logging
import os
import sys
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.ai_panel import AiPanel
from keyboard_executor.app.application import settings_urls_for_missing
from keyboard_executor.app.confirm import confirm_delete
from keyboard_executor.app.logview import format_progress, format_result, should_log
from keyboard_executor.app.rule_list import RuleListController
from keyboard_executor.app.run_controller import RunController
from keyboard_executor.app.script_list import ScriptListController, summary_for_script, script_list_label
from keyboard_executor.app.settings import Settings, SettingsStore, ocr_lang_from_setting
from keyboard_executor.app.watch_controller import WatchController
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.app.worker import Worker
from keyboard_executor.cli import default_scripts_dir
from keyboard_executor.core.logging_config import PACKAGE_LOGGER
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.platforms.factory import get_platform
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.templates import TemplateStore

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    emergency_stop_requested = Signal()   # 背景輪詢器跨執行緒請求緊急停止（排到 GUI 執行緒）
    script_hotkey_requested = Signal(str)   # 背景輪詢器請求執行某腳本（排到 GUI 執行緒）

    def __init__(self, data_dir=None, *, permission_warnings=None, settings=None,
                 script_storage=None, rule_storage=None, template_store=None,
                 run_controller=None, watch_controller=None,
                 worker_factory=Worker, permission_checks=None, url_opener=None,
                 confirm=None, ai_auth_service=None, demo_controller=None,
                 update_controller=None, update_exe=None):
        super().__init__()
        self._data_dir = Path(data_dir) if data_dir is not None else default_scripts_dir()
        self._settings = settings if settings is not None else Settings()
        self._permission_checks = permission_checks
        self._url_opener = url_opener if url_opener is not None else self._open_url
        self._confirm = (confirm if confirm is not None
                         else (lambda message: confirm_delete(self, message)))
        self._script_storage = (script_storage if script_storage is not None
                                else ScriptStorage(self._data_dir))
        self._rule_storage = (rule_storage if rule_storage is not None
                              else RuleStorage(self._data_dir))
        self._template_store = (template_store if template_store is not None
                                else TemplateStore(self._data_dir))
        self._get_platform = partial(
            get_platform,
            ocr_lang=ocr_lang_from_setting(self._settings.ocr_language))
        self._run_controller = (run_controller if run_controller is not None
                                else RunController(
                                    self._script_storage,
                                    self._template_store.load_template,
                                    get_platform=self._get_platform,
                                    stop_key=self._settings.stop_key,
                                    corner_failsafe=self._settings.corner_failsafe,
                                    chat_factory=self._build_chat_reply,
                                    sequence_factory=self._build_sequence_input))
        self._watch_controller = (watch_controller if watch_controller is not None
                                  else WatchController(
                                      self._rule_storage, self._script_storage,
                                      self._template_store.load_template,
                                      get_platform=self._get_platform,
                                      discord_webhook_url=self._settings.discord_webhook_url,
                                      on_stop_all=self._on_rule_stop_all))
        self._worker_factory = worker_factory
        if ai_auth_service is None:
            from keyboard_executor.app.ai_auth_service import AiAuthService
            ai_auth_service = AiAuthService()
        self._ai_auth_service = ai_auth_service
        from keyboard_executor.storage.ai_demo_sessions import AiDemoSessionStore
        self._demo_sessions = AiDemoSessionStore(self._data_dir)
        if demo_controller is None:
            from keyboard_executor.app.ai_demo_controller import AiDemoController
            demo_controller = AiDemoController(
                get_settings=lambda: self._settings, auth_service=self._ai_auth_service,
                script_storage=self._script_storage, templates=self._template_store,
                sessions=self._demo_sessions,
                get_platform=lambda **kw: self._get_platform(**kw),
                worker_factory=self._worker_factory)
        self._demo = demo_controller
        self._worker = None
        self._watch_worker = None
        self._global_hotkey = None     # Windows 系統級緊急停止（遊戲擋低階 hook 時的後盾）
        self._key_poller = None        # Windows 按鍵輪詢緊急停止（RegisterHotKey 與滑鼠角落之外的第三道後盾）
        self._script_hotkey_poller = None   # Windows 輪詢／macOS pynput 啟動熱鍵
        self._hotkey_platform = sys.platform
        self._window_manager = None    # 快取供腳本編輯器挑視窗，免每次重建整個 platform
        self._scripts = ScriptListController(self._script_storage)
        self._rules = RuleListController(self._rule_storage)
        self.setWindowTitle("Keyboard Executor")
        self._build_ui(permission_warnings or [])
        fit_window_to_available_screen(self, 1000, 700)
        self._wire()
        self.refresh_scripts()
        self.refresh_rules()
        self.emergency_stop_requested.connect(self._on_emergency_hotkey)
        self.script_hotkey_requested.connect(self._run_script)
        self._setup_global_hotkey()
        self._setup_key_poller()
        self._setup_script_hotkeys()
        self._setup_updater(update_controller, update_exe)

    def _setup_global_hotkey(self) -> None:
        """Windows：註冊系統級緊急停止熱鍵（RegisterHotKey），作為 pynput 低階鍵盤
        hook 被遊戲/反作弊擋掉時的可靠後盾（實測：遊戲中 F10 等鍵盤 hook 收不到，
        但滑鼠角落仍有效）。失敗（被占用/非 Windows）僅記錄，不影響其他停止途徑。"""
        if sys.platform != "win32":
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None or app.platformName() == "offscreen":
                return          # 測試／離屏環境不註冊系統熱鍵

            from keyboard_executor.app.global_hotkey import WindowsHotkey
            hk = WindowsHotkey(self._on_emergency_hotkey)
            if hk.register(self._settings.stop_key):
                QApplication.instance().installNativeEventFilter(hk)
                self._global_hotkey = hk
                logger.info("系統級緊急停止熱鍵已註冊：%s（遊戲中也應有效）",
                            self._settings.stop_key.upper())
            else:
                logger.warning(
                    "系統級緊急停止熱鍵註冊失敗（可能被其他程式占用）：%s；"
                    "仍可用滑鼠甩到螢幕左上角停止", self._settings.stop_key.upper())
        except Exception:
            logger.warning("系統級緊急停止熱鍵無法啟用", exc_info=True)

    def _setup_key_poller(self) -> None:
        """Windows：背景輪詢 GetAsyncKeyState 讀實體按鍵狀態，作為 RegisterHotKey
        與滑鼠角落之外的第三道緊急停止（遊戲擋掉前兩者時的後盾）。上升緣經
        emergency_stop_requested 排到 GUI 執行緒處理。"""
        if sys.platform != "win32":
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None or app.platformName() == "offscreen":
                return
            from keyboard_executor.app.key_stop_poller import AsyncKeyStopPoller
            poller = AsyncKeyStopPoller(self.emergency_stop_requested.emit)
            if poller.start(self._settings.stop_key):
                self._key_poller = poller
                logger.info("按鍵緊急停止輪詢已啟用：%s", self._settings.stop_key.upper())
        except Exception:
            logger.warning("按鍵緊急停止輪詢無法啟用", exc_info=True)

    def _setup_script_hotkeys(self) -> None:
        """依平台啟用腳本熱鍵；觸發經 Qt signal 排到 GUI 執行緒。"""
        if self._hotkey_platform not in ("win32", "darwin"):
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None or app.platformName() == "offscreen":
                return
            if self._hotkey_platform == "darwin":
                from keyboard_executor.app.pynput_hotkeys import PynputScriptHotkeys
                hotkeys_cls = PynputScriptHotkeys
            else:
                from keyboard_executor.app.script_hotkey_poller import ScriptHotkeyPoller
                hotkeys_cls = ScriptHotkeyPoller
            self._script_hotkey_poller = hotkeys_cls(
                self.script_hotkey_requested.emit)
            self._refresh_script_hotkeys()
        except Exception:
            logger.warning("腳本啟動熱鍵無法啟用", exc_info=True)

    def _build_script_bindings(self) -> list[tuple[str, list[int]]]:
        """從所有腳本的 settings.hotkey 建綁定；去重（先出現者贏）、略過含緊急停止鍵者
        與無法對應者。回傳 [(腳本名, [vk,...])]。"""
        from keyboard_executor.app.global_hotkey import hotkey_to_vks, vk_for_key
        stop_vk = vk_for_key(self._settings.stop_key)
        claimed: set[frozenset[int]] = set()
        bindings: list[tuple[str, list[int]]] = []
        for name in self._scripts.names:          # list_names() 已排序 → 先出現者贏
            try:
                hk = self._script_storage.load(name).settings.hotkey.strip()
            except ScriptValidationError:
                logger.warning("腳本「%s」載入失敗，略過其啟動熱鍵", name)
                continue
            if not hk:
                continue
            vks = hotkey_to_vks(hk)
            if vks is None:
                logger.warning("腳本「%s」啟動熱鍵 %s 有無法對應的按鍵，略過", name, hk)
                continue
            if stop_vk is not None and stop_vk in vks:
                logger.warning("腳本「%s」啟動熱鍵 %s 含緊急停止鍵，略過", name, hk)
                continue
            key = frozenset(vks)
            if key in claimed:
                logger.warning("腳本「%s」啟動熱鍵 %s 與其他腳本重複，略過", name, hk)
                continue
            claimed.add(key)
            bindings.append((name, vks))
        return bindings

    def _build_darwin_script_bindings(self) -> list[tuple[str, list[str]]]:
        from keyboard_executor.platforms.common.keymap import key_to_name, parse_combo, parse_key
        stop_key = key_to_name(parse_key(self._settings.stop_key))
        claimed = set()
        bindings = []
        for name in self._scripts.names:
            try:
                hotkey = self._script_storage.load(name).settings.hotkey.strip()
                if not hotkey:
                    continue
                keys = [key_to_name(key) for key in parse_combo(hotkey)]
                signature = frozenset(keys)
                if None in signature or stop_key in signature or signature in claimed:
                    logger.warning("腳本「%s」啟動熱鍵 %s 重複或包含緊急停止鍵，略過", name, hotkey)
                    continue
            except (ScriptValidationError, ValueError):
                logger.warning("腳本「%s」啟動熱鍵無法在 macOS 使用，略過", name)
                continue
            claimed.add(signature)
            bindings.append((name, keys))
        return bindings

    def _refresh_script_hotkeys(self) -> None:
        poller = self._script_hotkey_poller
        if poller is None:
            return
        poller.stop()
        bindings = (self._build_darwin_script_bindings() if self._hotkey_platform == "darwin"
                    else self._build_script_bindings())
        if bindings:
            poller.start(bindings)

    def _on_rule_stop_all(self) -> None:
        """規則的「停止全部」：停執行中的腳本，也結束 AI 示範試跑（監看執行緒呼叫）。"""
        self._run_controller.stop()
        demo = getattr(self, "_demo", None)
        if demo is not None:
            demo.stop()

    def _on_emergency_hotkey(self) -> None:
        """緊急停止（系統級/背景輪詢）：只中止進行中的回放；監看完全獨立，
        由「停止監看」按鈕停止。"""
        self.append_log("偵測到緊急停止 → 中止回放")
        self._run_controller.stop()
        self._demo.stop()     # 沒在試跑時是 no-op

    def _build_ui(self, warnings: list[str]) -> None:
        """模組化版面：頂列（品牌＋全域）／權限橫幅／腳本模組｜規則模組／日誌。

        設計原則：動作貼著它操作的對象（腳本鈕在腳本模組、規則鈕在規則模組），
        每個模組只有一個醒目的主要動作（執行綠／開始監看琥珀），停止與刪除用語意色。"""
        # 頂層可縮到小螢幕放得下；完整桌面仍維持原本 760×560 的版面，較小時由
        # 外層 QScrollArea 提供捲動，不讓標題列／底部按鈕落到螢幕外而無法操作。
        self.setMinimumSize(420, 320)
        central = QWidget()
        central.setMinimumSize(760, 560)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._titlebar = self._build_titlebar()
        root.addWidget(self._titlebar)
        root.addWidget(self._build_banner(warnings))

        workspace = QWidget()
        ws = QVBoxLayout(workspace)
        ws.setContentsMargins(14, 14, 14, 14)
        ws.setSpacing(14)
        modules = QHBoxLayout()
        modules.setSpacing(14)
        modules.addWidget(self._build_scripts_module(), stretch=1)
        modules.addWidget(self._build_rules_module(), stretch=1)
        ws.addLayout(modules, stretch=3)
        ws.addWidget(self._build_console(), stretch=2)
        root.addWidget(workspace, stretch=1)

        self._main_scroll = QScrollArea()
        self._main_scroll.setObjectName("mainScroll")
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._main_scroll.setWidget(central)
        self.setCentralWidget(self._main_scroll)

        self._ai_panel = AiPanel(
            get_settings=lambda: self._settings,
            ack_privacy=self._ack_ai_privacy,
            storage=self._script_storage,
            rule_storage=self._rule_storage,
            get_selected_script=lambda: self._scripts.selected,
            worker_factory=self._worker_factory,
            auth_service=self._ai_auth_service,
            demo_controller=self._demo)
        self._ai_dock = QDockWidget("AI 助手", self)
        self._ai_dock.setObjectName("aiDock")
        self._ai_dock.setWidget(self._ai_panel)
        # 原生標題列的浮動/關閉鈕吃不到深色主題（會畫成淺色系統控件），改用自訂
        # 標題列；同時關掉浮動，這個面板只在右側停靠或收合。
        self._ai_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self._ai_dock.setTitleBarWidget(self._build_ai_titlebar())
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._ai_dock)
        self._ai_dock.hide()

        self._set_tooltips()

    # ---- 版面建構 helper（皆建立 self.* widget，供 _wire 接線）----

    def _hline(self) -> QFrame:
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    def _module_head(self, icon: str, title: str, subtitle: str, kind: str = ""):
        """模組標頭：圖示＋標題／副標＋（右側主要動作由呼叫端補）。回傳 (layout, )。"""
        head = QHBoxLayout()
        head.setContentsMargins(14, 13, 12, 11)
        head.setSpacing(10)
        ico = QLabel(icon)
        ico.setObjectName("modIcon")
        if kind:
            ico.setProperty("kind", kind)
        ico.setFixedSize(30, 30)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("moduleTitle")
        s = QLabel(subtitle)
        s.setObjectName("moduleSub")
        title_box.addWidget(t)
        title_box.addWidget(s)
        head.addWidget(ico)
        head.addLayout(title_box)
        head.addStretch(1)
        return head

    def _build_titlebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("titlebar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 14, 10)
        lay.setSpacing(10)
        keycap = QLabel("K")
        keycap.setObjectName("keycap")
        keycap.setFixedSize(32, 32)
        keycap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        word = QLabel("KEYBOARD EXECUTOR")
        word.setObjectName("wordmark")
        word.setProperty("accentWord", "true")
        from keyboard_executor import __version__
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("ver")
        lay.addWidget(keycap)
        lay.addWidget(word)
        lay.addWidget(ver)
        lay.addStretch(1)
        self._estop_label = QLabel(f"● 緊急停止 {self._settings.stop_key.upper()}")
        self._estop_label.setObjectName("estop")
        lay.addWidget(self._estop_label)
        self.ai_button = QPushButton("AI 助手")
        self.ai_button.setProperty("variant", "ghost")
        lay.addWidget(self.ai_button)
        self.transfer_button = QPushButton("匯出／匯入")
        self.transfer_button.setProperty("variant", "ghost")
        lay.addWidget(self.transfer_button)
        self.template_manage_button = QPushButton("模板管理")
        self.template_manage_button.setProperty("variant", "ghost")
        self.settings_button = QPushButton("設定")
        self.settings_button.setProperty("variant", "ghost")
        lay.addWidget(self.template_manage_button)
        lay.addWidget(self.settings_button)
        return bar

    def _build_ai_titlebar(self) -> QFrame:
        """AI dock 的自訂標題列：字標＋收合鈕，配色比照主視窗 titlebar。"""
        bar = QFrame()
        bar.setObjectName("aiTitleBar")
        # dock 貼在主標題列右側，兩條列的底線必須切齊，否則視窗頂端會出現一道
        # 錯位的階梯。高度取主標題列的實測值（非寫死），字型/DPI 變動仍會對齊。
        bar.setFixedHeight(self._titlebar.sizeHint().height())
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(8)
        word = QLabel("✦ AI 助手")
        word.setObjectName("aiTitleWord")
        lay.addWidget(word)
        lay.addStretch(1)
        self.ai_close_button = QPushButton("✕")
        self.ai_close_button.setObjectName("aiTitleClose")
        self.ai_close_button.setToolTip("收合 AI 助手")
        self.ai_close_button.setFixedSize(24, 24)
        self.ai_close_button.clicked.connect(self._ai_dock.hide)
        lay.addWidget(self.ai_close_button)
        return bar

    def _build_banner(self, warnings: list[str]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("banner")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, 10, 14, 10)
        lay.setSpacing(10)
        self.permission_banner = QLabel()
        self.permission_banner.setObjectName("bannerText")
        self.permission_banner.setWordWrap(True)
        self.open_settings_button = QPushButton("開啟系統設定")
        lay.addWidget(self.permission_banner, stretch=1)
        lay.addWidget(self.open_settings_button)
        if warnings:
            self.permission_banner.setText("\n\n".join(warnings))
        else:
            # 無警告：隱藏 label 本身（test 斷言 permission_banner.isHidden()）與整條橫幅
            self.permission_banner.hide()
            self.open_settings_button.hide()
            frame.hide()
        return frame

    def _build_scripts_module(self) -> QFrame:
        card = QFrame()
        card.setObjectName("module")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = self._module_head("", "腳本", "回放一次性動作序列")
        self.stop_button = QPushButton("■ 停止")
        self.stop_button.setProperty("variant", "danger")
        self.run_button = QPushButton("▶ 執行")
        self.run_button.setProperty("variant", "run")
        head.addWidget(self.stop_button)
        head.addWidget(self.run_button)
        lay.addLayout(head)

        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 12)
        body.setSpacing(8)
        self.script_list = QListWidget()
        body.addWidget(self.script_list, stretch=1)
        self.summary_label = QLabel("尚未選取腳本")
        self.summary_label.setObjectName("detail")
        self.summary_label.setWordWrap(True)
        body.addWidget(self.summary_label)
        lay.addLayout(body, stretch=1)

        lay.addWidget(self._hline())
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 10, 12, 12)
        foot.setSpacing(8)
        self.new_script_button = QPushButton("新增")
        self.edit_button = QPushButton("編輯")
        self.script_duplicate_button = QPushButton("複製")
        self.record_button = QPushButton("錄製")
        self.script_delete_button = QPushButton("刪除")
        self.script_delete_button.setProperty("variant", "danger")
        foot.addWidget(self.new_script_button)
        foot.addWidget(self.edit_button)
        foot.addWidget(self.script_duplicate_button)
        foot.addWidget(self.record_button)
        foot.addStretch(1)
        foot.addWidget(self.script_delete_button)
        lay.addLayout(foot)
        return card

    def _build_rules_module(self) -> QFrame:
        card = QFrame()
        card.setObjectName("module")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = self._module_head("", "規則", "持續盯畫面・命中即觸發", kind="rules")
        self.watch_stop_button = QPushButton("■ 停止監看")
        self.watch_stop_button.setProperty("variant", "danger")
        self.watch_button = QPushButton("▶ 開始監看")
        self.watch_button.setProperty("variant", "watch")
        head.addWidget(self.watch_stop_button)
        head.addWidget(self.watch_button)
        lay.addLayout(head)

        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 12)
        body.setSpacing(8)
        self.rule_list = QListWidget()
        body.addWidget(self.rule_list, stretch=1)
        lay.addLayout(body, stretch=1)

        lay.addWidget(self._hline())
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 10, 12, 12)
        foot.setSpacing(8)
        self.rule_edit_button = QPushButton("編輯 / 新增")
        self.rule_duplicate_button = QPushButton("複製")
        self.rule_delete_button = QPushButton("刪除")
        self.rule_delete_button.setProperty("variant", "danger")
        foot.addWidget(self.rule_edit_button)
        foot.addWidget(self.rule_duplicate_button)
        foot.addStretch(1)
        foot.addWidget(self.rule_delete_button)
        lay.addLayout(foot)
        return card

    def _build_console(self) -> QFrame:
        card = QFrame()
        card.setObjectName("console")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(14, 11, 14, 10)
        head.setSpacing(10)
        label = QLabel("執行日誌")
        label.setObjectName("sectionLabel")
        head.addWidget(label)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(self._hline())
        body = QVBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        body.addWidget(self.log_view)
        lay.addLayout(body, stretch=1)
        return card

    def _set_tooltips(self) -> None:
        """把每個按鈕的作用與關聯講清楚（直接處理『看不懂按鍵關聯性』）。"""
        self.run_button.setToolTip("對選取的腳本執行一次回放")
        self.stop_button.setToolTip("停止目前的腳本回放")
        self.watch_button.setToolTip("依已啟用的規則持續監看畫面，命中即觸發")
        self.watch_stop_button.setToolTip("停止監看")
        self.new_script_button.setToolTip(
            "手動新增空白腳本，逐一加入按鍵/點擊/延遲並指定目標視窗（不需先錄製）")
        self.edit_button.setToolTip("編輯選取的腳本（含目標視窗、動作序列）")
        self.script_duplicate_button.setToolTip("複製選取的腳本（含編輯器版面）")
        self.record_button.setToolTip(
            f"開啟錄製面板錄製新腳本（{self._settings.toggle_key.upper()} 開始/停止）")
        self.script_delete_button.setToolTip("刪除選取的腳本")
        self.rule_edit_button.setToolTip("編輯選取的規則；未選取時新增一條規則")
        self.rule_duplicate_button.setToolTip("複製選取的規則")
        self.rule_delete_button.setToolTip("刪除選取的規則（清單雙擊可切換啟用/停用）")
        self.transfer_button.setToolTip(
            "把腳本與規則匯出成單一檔案傳給別人，或從匯出檔匯入（模板圖片會一併打包）")
        self.template_manage_button.setToolTip("管理圖像比對用的模板")
        self.settings_button.setToolTip("熱鍵、OCR 語言、日誌等級與權限")
        self.ai_button.setToolTip(
            "AI 助手：可附圖詢問，並產生規則、腳本或整套自動化提案")

    def _wire(self) -> None:
        self.script_list.currentItemChanged.connect(self._on_script_current_changed)
        self.script_list.itemDoubleClicked.connect(lambda _item: self._on_edit_script())
        self.run_button.clicked.connect(self._on_run_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.edit_button.clicked.connect(self._on_edit_script)
        self.script_duplicate_button.clicked.connect(self._on_duplicate_script)
        self.rule_edit_button.clicked.connect(self._on_edit_rule)
        self.rule_duplicate_button.clicked.connect(self._on_duplicate_rule)
        self.rule_list.itemDoubleClicked.connect(self._on_rule_toggled)
        self.watch_button.clicked.connect(self._on_watch_clicked)
        self.watch_stop_button.clicked.connect(self._on_watch_stop_clicked)
        self.record_button.clicked.connect(self._on_open_recorder)
        self.settings_button.clicked.connect(self._on_open_settings)
        self.ai_button.clicked.connect(
            lambda: self._ai_dock.setVisible(self._ai_dock.isHidden()))
        self._ai_panel.open_settings_requested.connect(self._on_open_settings)
        self._ai_panel.scripts_changed.connect(self.refresh_scripts)
        self._ai_panel.rules_changed.connect(self.refresh_rules)
        self._ai_panel.demo_requested.connect(self._on_open_demo)
        self._demo.active_changed.connect(self._on_demo_active)
        self._demo.scripts_changed.connect(self.refresh_scripts)
        self.open_settings_button.clicked.connect(self._on_open_system_settings)
        self.script_delete_button.clicked.connect(self._on_delete_script)
        self.rule_delete_button.clicked.connect(self._on_delete_rule)
        self.transfer_button.clicked.connect(self._on_transfer)
        self.template_manage_button.clicked.connect(self._on_manage_templates)
        self.new_script_button.clicked.connect(self._on_new_script)

    def refresh_scripts(self) -> None:
        self.script_list.clear()
        for name in self._scripts.refresh():
            item = QListWidgetItem(script_list_label(self._script_storage, name))
            item.setData(Qt.ItemDataRole.UserRole, name)   # 真名與顯示文字解耦
            self.script_list.addItem(item)
        self._refresh_script_hotkeys()

    def append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _on_script_current_changed(self, current, previous) -> None:
        name = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._on_script_selected(name)

    def _on_script_selected(self, name: str) -> None:
        if not name:
            return
        self._scripts.select(name)
        self.summary_label.setText(summary_for_script(self._script_storage, name))

    def _on_run_clicked(self) -> None:
        self._run_script(self._scripts.selected)

    def _build_sequence_input(self, script, platform, stop_event, progress):
        from keyboard_executor.app.sequence_input_service import build_sequence_runtime
        return build_sequence_runtime(self._settings, self._ai_auth_service, script,
                                      platform, stop_event, progress, history_root=self._data_dir)

    def _build_chat_reply(self, script, platform, stop_event, progress):
        from keyboard_executor.app.chat_reply_service import build_chat_session

        return build_chat_session(self._settings, self._ai_auth_service, script,
                                  platform, stop_event, progress, history_root=self._data_dir)

    def _run_script(self, name) -> None:
        if self._demo.active:
            self.append_log("AI 示範試跑中，暫停手動執行腳本（可在 AI 面板停止試跑）")
            return
        if name is None:
            self.append_log("請先選取要執行的腳本")
            return
        # 先停現在跑的、再跑新的（_cleanup_worker 收尾會把 self._worker 設 None，故非
        # None 即代表仍在跑，熱鍵可在腳本執行中切換）。必須在 build_job 之前——build_job
        # 會覆寫 run_controller._stop_event，若先 build 再 stop 會停到新 job 而非舊的
        # （舊的停不下來、新的一啟動就被停）。
        # 取捨：新腳本若載入失敗，前一個腳本已被停掉——可接受，使用者按熱鍵就是要切換。
        if self._worker is not None:
            self._run_controller.stop()
            self._cleanup_worker()
        try:
            job = self._run_controller.build_job(name)
        except ScriptValidationError as e:
            self.append_log(f"腳本載入失敗：{e}")
            self.run_button.setEnabled(True)   # 載入失敗（可能已先停掉舊的）→ 恢復按鈕，避免卡死
            return
        stop_key = self._settings.stop_key.upper()
        self.append_log(f"開始回放：{name}（{stop_key} 或滑鼠甩到螢幕左上角可緊急停止）")
        worker = self._worker_factory(job)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_run_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker = worker                    # 保留引用，避免執行中被 GC
        self.run_button.setEnabled(False)
        worker.start()

    def _on_progress(self, record: dict) -> None:
        if self._demo.active:
            kind = record.get("kind")
            if (kind == "fire"
                    and "run_script" in str(record.get("trigger", "")).split("+")):
                # 規則的腳本會操作角色：中斷這一輪，等它跑完再重跑
                self._demo.set_external_busy(True)
                self._demo.interrupt(f"規則「{record.get('rule')}」觸發")
            elif kind == "fire_done":
                self._demo.set_external_busy(False)
        if should_log(record, self._settings.log_level):
            self.append_log(format_progress(record))

    def _on_run_finished(self, result) -> None:
        # 忽略舊 worker 殘留的 finished：切換腳本時舊 worker 的訊號雖已 disconnect，
        # 但 PySide6 不會清掉已排入佇列的跨執行緒呼叫；若在新 worker 就位後才送達，
        # sender 會與現任 self._worker 不同 → 忽略，以免 _cleanup_worker() wait() 卡住
        # 新 worker（loop_forever 會讓 GUI 凍結）。
        if self.sender() is not None and self.sender() is not self._worker:
            return
        self.append_log(format_result(result))
        self.run_button.setEnabled(True)
        self._cleanup_worker()

    def _on_worker_failed(self, message: str) -> None:
        if self.sender() is not None and self.sender() is not self._worker:
            return
        self.append_log(message)
        self.run_button.setEnabled(True)
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        """收尾：斷開舊 worker 訊號、等背景執行緒結束、把 self._worker 歸零，
        避免舊 worker 的 finished/failed 在新 worker 就位後回頭誤觸，也讓
        「self._worker 非 None 即在跑」的判斷成立。"""
        w = self._worker
        if w is None:
            return
        for attr, slot in (("progress", self._on_progress),
                           ("finished", self._on_run_finished),
                           ("failed", self._on_worker_failed)):
            sig = getattr(w, attr, None)      # 假 worker（如 SpyWorker）可能沒有訊號
            if sig is not None:
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        w.wait()
        self._worker = None

    def _on_stop_clicked(self) -> None:
        self._run_controller.stop()
        self.append_log("已送出停止訊號")

    def _list_windows(self):
        """開啟中的視窗清單（供腳本編輯器挑目標視窗）；失敗回空清單、不擾使用者。
        window_manager 快取重用，避免每次都重建 platform（含 mss/輸入後端）。"""
        try:
            if self._window_manager is None:
                self._window_manager = self._get_platform().window_manager
            return self._window_manager.list_all()
        except Exception as e:
            self.append_log(f"無法列出視窗：{e}")
            return []

    def _on_new_script(self) -> None:
        """手動新增空白腳本（不需先錄製）：開啟編輯器，逐一新增動作、設定目標視窗。"""
        from keyboard_executor.app.script_editor import ScriptEditorDialog
        from keyboard_executor.app.script_editor_model import ScriptEditorModel

        model = ScriptEditorModel.new()
        ScriptEditorDialog(model, self._script_storage, parent=self,
                           window_lister=self._list_windows,
                           ai_model_label=f"{self._settings.ai_provider or '尚未設定 AI'} / {self._settings.ai_model or '自動選擇'}").exec()
        self.refresh_scripts()

    def _on_edit_script(self) -> None:
        from keyboard_executor.app.script_editor import ScriptEditorDialog
        from keyboard_executor.app.script_editor_model import ScriptEditorModel

        name = self._scripts.selected
        if name is None:
            self.append_log("請先選取要編輯的腳本")
            return
        try:
            model = ScriptEditorModel(self._script_storage.load(name))
        except ScriptValidationError as e:
            self.append_log(f"腳本載入失敗：{e}")
            return
        ScriptEditorDialog(model, self._script_storage, parent=self,
                           window_lister=self._list_windows,
                           ai_model_label=f"{self._settings.ai_provider or '尚未設定 AI'} / {self._settings.ai_model or '自動選擇'}").exec()
        self.refresh_scripts()

    def _on_edit_rule(self) -> None:
        from keyboard_executor.app.rule_editor import RuleEditorDialog
        from keyboard_executor.app.rule_editor_model import RuleEditorModel

        index = self.rule_list.currentRow()
        if index < 0 or index >= len(self._rules.names):
            model = RuleEditorModel()          # 新規則
        else:
            try:
                model = RuleEditorModel.from_rule(
                    self._rule_storage.load(self._rules.names[index]))
            except ScriptValidationError as e:
                self.append_log(f"規則載入失敗：{e}")
                return
        RuleEditorDialog(model, self._rule_storage,
                         template_store=self._template_store, parent=self,
                         window_lister=self._list_windows,
                         script_names=self._script_storage.list_names).exec()
        self.refresh_rules()

    def _on_delete_script(self) -> None:
        name = self._scripts.selected
        if name is None:
            self.append_log("請先選取要刪除的腳本")
            return
        if not self._confirm(f"確定刪除腳本「{name}」？此操作無法復原。"):
            return
        try:
            self._scripts.delete_selected()
        except (ScriptValidationError, ValueError) as e:
            self.append_log(f"腳本刪除失敗：{e}")
            return
        self.append_log(f"已刪除腳本「{name}」")
        self.refresh_scripts()
        self.summary_label.setText("尚未選取腳本")

    def _on_delete_rule(self) -> None:
        index = self.rule_list.currentRow()
        if index < 0 or index >= len(self._rules.names):
            self.append_log("請先選取要刪除的規則")
            return
        name = self._rules.names[index]
        if not self._confirm(f"確定刪除規則「{name}」？此操作無法復原。"):
            return
        try:
            self._rules.delete(name)
        except ScriptValidationError as e:
            self.append_log(f"規則刪除失敗：{e}")
            return
        self.append_log(f"已刪除規則「{name}」")
        self.refresh_rules()

    def _on_duplicate_script(self) -> None:
        name = self._scripts.selected
        if name is None:
            self.append_log("請先選取要複製的腳本")
            return
        try:
            new = self._scripts.duplicate_selected()
        except (ScriptValidationError, ValueError) as e:
            self.append_log(f"腳本複製失敗：{e}")
            return
        self.append_log(f"已複製為「{new}」")
        self.refresh_scripts()
        self.script_list.setCurrentRow(self._scripts.names.index(new))

    def _on_duplicate_rule(self) -> None:
        index = self.rule_list.currentRow()
        if index < 0 or index >= len(self._rules.names):
            self.append_log("請先選取要複製的規則")
            return
        name = self._rules.names[index]
        try:
            new = self._rules.duplicate(name)
        except ScriptValidationError as e:
            self.append_log(f"規則複製失敗：{e}")
            return
        self.append_log(f"已複製為「{new}」")
        self.refresh_rules()
        self.rule_list.setCurrentRow(self._rules.names.index(new))

    def _on_manage_templates(self) -> None:
        from keyboard_executor.app.template_manager import TemplateManagerDialog

        TemplateManagerDialog(self._template_store, parent=self).exec()

    def _on_transfer(self) -> None:
        """匯出／匯入腳本與規則（相依的模板圖片會一併打包）。"""
        from keyboard_executor.app.transfer_dialog import TransferDialog

        TransferDialog(self._script_storage, self._rule_storage,
                       self._template_store, parent=self).exec()
        # 匯入可能新增/覆蓋了腳本與規則，兩份清單都要重讀
        self.refresh_scripts()
        self.refresh_rules()

    def refresh_rules(self) -> None:
        self.rule_list.clear()
        self.rule_list.addItems(self._rules.labels())

    def _on_rule_toggled(self, item) -> None:
        index = self.rule_list.row(item)
        if index < 0 or index >= len(self._rules.names):
            return
        name = self._rules.names[index]
        try:
            enabled = self._rules.toggle_enabled(name)
        except ScriptValidationError as e:
            self.append_log(f"規則切換失敗：{e}")
            return
        self.append_log(f"規則「{name}」已{'啟用' if enabled else '停用'}")
        self.refresh_rules()

    def _on_watch_clicked(self) -> None:
        try:
            job = self._watch_controller.build_job()
        except ScriptValidationError as e:
            self.append_log(f"無法開始監看：{e}")
            return
        self.append_log("開始監看（停止監看按鈕可停止）")
        worker = self._worker_factory(job)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_watch_finished)
        worker.failed.connect(self._on_watch_worker_failed)
        self._watch_worker = worker
        self.watch_button.setEnabled(False)
        worker.start()

    def _on_watch_finished(self, message) -> None:
        self.append_log(str(message))
        self.watch_button.setEnabled(True)
        self._cleanup_watch_worker()

    def _on_watch_worker_failed(self, message: str) -> None:
        self.append_log(message)
        self.watch_button.setEnabled(True)
        self._cleanup_watch_worker()

    def _cleanup_watch_worker(self) -> None:
        """與 _cleanup_worker 相同的收尾治理（Task 4 模式套用到監看 Worker）：
        finished/failed 送達時背景執行緒已 quit()，這裡 wait() 確保真正結束
        再放手，避免監看反覆啟停時 QThread 累積。"""
        if self._watch_worker is not None:
            self._watch_worker.wait()

    def _on_watch_stop_clicked(self) -> None:
        self._watch_controller.stop()

    def _on_open_recorder(self) -> None:
        from keyboard_executor.app.recorder_panel import RecorderPanel

        panel = RecorderPanel(self._get_platform().window_manager,
                              self._script_storage,
                              toggle_key=self._settings.toggle_key,
                              stop_key=self._settings.stop_key, parent=self)
        panel.exec()
        self.refresh_scripts()

    def _on_open_demo(self) -> None:
        if self._worker is not None:
            # 腳本送出的按鍵會被錄進示範，試跑時也會跟它搶著操作角色
            self.append_log("有腳本正在執行，請先停止再開始 AI 示範錄製")
            return
        from keyboard_executor.app.ai_demo_dialog import AiDemoDialog

        dialog = AiDemoDialog(self._get_platform().window_manager, self._demo_sessions,
                              toggle_key=self._settings.toggle_key,
                              stop_key=self._settings.stop_key, parent=self)
        dialog.recorded.connect(
            lambda rec, win, session: self._demo.start_loop(rec, win, session))
        self._ai_dock.show()
        dialog.exec()

    def _on_demo_active(self, active: bool) -> None:
        self.run_button.setEnabled(not active and self._worker is None)
        self.append_log("AI 示範試跑開始" if active else "AI 示範試跑結束")

    # ---- 自動更新 ----
    def _setup_updater(self, update_controller, update_exe) -> None:
        if update_controller is None:
            from keyboard_executor import __version__
            from keyboard_executor.app.update_controller import UpdateController
            update_controller = UpdateController(
                exe=update_exe, current=__version__, get_settings=lambda: self._settings,
                is_busy=self.is_busy, parent=self)
        self._updater = update_controller
        self._updater.update_ready.connect(self._on_update_ready)
        self._updater.manual_update_needed.connect(self._on_manual_update)
        self._updater.start()

    def is_busy(self) -> bool:
        """更新提示的時機判斷：腳本執行、規則監看、AI 示範試跑或任何對話框開著都算忙。"""
        from PySide6.QtWidgets import QApplication

        from keyboard_executor.app.settings_page import SettingsPage
        modal = QApplication.activeModalWidget()
        # 設定頁不算忙：使用者常在設定頁按「立即檢查更新」，要能直接跳出提示
        blocking_modal = modal is not None and not isinstance(modal, SettingsPage)
        return (self._worker is not None or self._watch_worker is not None
                or self._demo.active or blocking_modal)

    def _on_update_ready(self, info) -> None:
        from keyboard_executor.core.update.install import (
            install_staged, restart_command, restart_env,
        )
        from keyboard_executor.core.update.release import UpdateError
        if not self._confirm_update(info) or self.is_busy():
            self._updater.postpone()      # 對話框開著時可能有熱鍵啟動腳本：不中途關閉
            return
        exe = self._updater.exe
        if not self._updater.exe_replaced():   # 另一個開著的程式已換好新版就只重開
            try:
                install_staged(exe)
            except UpdateError as e:
                logger.warning("安裝更新失敗：%s", e)
                self._show_update_error(f"更新失敗：{e}\n\n舊版仍可正常使用，稍後會再提醒。")
                self._updater.install_failed(info.version)
                return
        logger.info("已換上新版 %s，重新啟動", info.version)
        try:
            self._popen(restart_command(exe, sys.argv), restart_env(os.environ))
        except OSError as e:
            logger.warning("重新啟動新版失敗：%s", e)
            self._show_update_error(f"新版 {info.version} 已安裝，但無法自動重新開啟：{e}\n請手動開啟程式。")
        self._quit()

    def _confirm_update(self, info) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("有新版本")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"新版 {info.version} 已下載，要現在重新啟動更新嗎？")
        if info.notes.strip():
            box.setInformativeText(f"更新內容：\n{info.notes.strip()}")
        update = box.addButton("立即更新", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍後", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is update

    def _show_update_error(self, text: str) -> None:
        QMessageBox.warning(self, "更新", text)

    def _popen(self, cmd, env) -> None:
        import subprocess
        subprocess.Popen(cmd, env=env, close_fds=True)

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        self.close()
        QApplication.quit()

    def _on_manual_update(self, url: str) -> None:
        if self._confirm_manual_update(url):
            self._url_opener(url)

    def _confirm_manual_update(self, url: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("有新版本")
        box.setText("有新版本，但程式所在的資料夾無法寫入，沒辦法自動更新。\n"
                    f"請到下載頁手動下載：\n{url}")
        open_button = box.addButton("開啟下載頁", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("關閉", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is open_button

    def _on_open_settings(self) -> None:
        from keyboard_executor.app.settings_page import SettingsPage

        page = SettingsPage(SettingsStore(self._data_dir),
                            permission_checks=self._permission_checks, parent=self,
                            auth_service=self._ai_auth_service,
                            worker_factory=self._worker_factory,
                            update_controller=self._updater)
        page.saved.connect(self._apply_settings)
        page.exec()

    def _ack_ai_privacy(self) -> None:
        """AI 隱私告知確認：持久化並同步記憶體設定。"""
        self._settings = dataclasses.replace(self._settings, ai_privacy_ack=True)
        try:
            SettingsStore(self._data_dir).save(self._settings)
        except ScriptValidationError as e:
            logger.warning("儲存 AI 隱私確認失敗：%s", e)

    def _apply_settings(self, new: "Settings") -> None:
        """設定存檔後免重開即套用：日誌等級與系統熱鍵立即；控制器 stop_key／
        webhook／OCR 於下一次執行/監看生效（進行中的維持原設定）。"""
        self._settings = new
        # 日誌等級即時生效：除了 progress 過濾（讀 self._settings），也要調整套件根
        # logger 與 GUI 日誌 handler 的等級（原本只在開機設一次，否則 logger.debug
        # 與檔案日誌要重開才變詳細）。
        logging.getLogger(PACKAGE_LOGGER).setLevel(new.log_level)
        handler = getattr(self, "gui_log_handler", None)
        if handler is not None:
            handler.setLevel(new.log_level)
        self._get_platform = partial(
            get_platform,
            ocr_lang=ocr_lang_from_setting(new.ocr_language))
        self._run_controller.apply_settings(
            stop_key=new.stop_key, get_platform=self._get_platform,
            corner_failsafe=new.corner_failsafe)
        self._watch_controller.apply_settings(
            get_platform=self._get_platform,
            discord_webhook_url=new.discord_webhook_url)
        self._reregister_hotkey(new.stop_key)
        self._refresh_hotkey_labels()
        self._refresh_script_hotkeys()   # stop_key 若改變，撞停止鍵而略過的熱鍵可能重新可用
        self._ai_panel.refresh_state()

    def _reregister_hotkey(self, stop_key: str) -> None:
        # 輪詢器與 RegisterHotKey 各自獨立：即使 RegisterHotKey 註冊失敗（_global_hotkey
        # 為 None，例如熱鍵被別的程式占用），輪詢器仍須隨設定更新到新鍵。
        if self._key_poller is not None:
            self._key_poller.stop()
            if not self._key_poller.start(stop_key):
                logger.warning("按鍵緊急停止輪詢重新啟動失敗：%s", stop_key.upper())
        if self._global_hotkey is None:
            return
        self._global_hotkey.unregister()
        if self._global_hotkey.register(stop_key):
            logger.info("系統級緊急停止熱鍵已更新：%s", stop_key.upper())
        else:
            logger.warning("系統級緊急停止熱鍵重新註冊失敗：%s；仍可用滑鼠角落停止",
                           stop_key.upper())

    def _refresh_hotkey_labels(self) -> None:
        self._estop_label.setText(f"● 緊急停止 {self._settings.stop_key.upper()}")
        self.record_button.setToolTip(
            f"開啟錄製面板錄製新腳本（{self._settings.toggle_key.upper()} 開始/停止）")

    def _on_open_system_settings(self) -> None:
        urls = settings_urls_for_missing(self._permission_checks)
        if not urls:
            self.append_log("目前沒有缺失的權限")
            return
        # 系統設定一次只顯示一個分頁：開第一個缺失的；其餘依橫幅引導文字逐一處理
        self._url_opener(urls[0])

    def _open_url(self, url: str) -> None:
        """thin：真實開啟 deep link（人工驗收）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self, event):
        # 關窗前先停掉進行中的回放/監看，並等 QThread 真正結束，避免 teardown 時
        # 「QThread: Destroyed while thread is still running」與背景仍送輸入；
        # 最後拆除 GUI 日誌橋（build_app 掛上的），避免後續記錄投遞給已銷毀 widget。
        self._run_controller.stop()
        self._watch_controller.stop()
        if self._global_hotkey is not None:
            self._global_hotkey.unregister()
        if self._key_poller is not None:
            self._key_poller.stop()
        if self._script_hotkey_poller is not None:
            self._script_hotkey_poller.stop()
        self._cleanup_worker()
        self._cleanup_watch_worker()
        self._ai_panel.shutdown()
        self._demo.shutdown()
        self._updater.shutdown()
        from keyboard_executor.app.qt_log_handler import detach_gui_handler

        detach_gui_handler(getattr(self, "gui_log_handler", None))
        event.accept()
