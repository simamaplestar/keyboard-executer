"""設定頁（spec §9）：熱鍵自訂、OCR 語言、日誌等級、macOS 權限狀態顯示。

薄件：驗證與持久化在 app/settings.py（純邏輯）。熱鍵與 OCR 語言於控制器
建構時讀取——儲存後如實提示重新啟動生效。"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.application import default_permission_checks
from keyboard_executor.app.key_capture import _KeyCaptureEdit
from keyboard_executor.app.settings import Settings, SettingsStore
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.auth.models import AuthStatus
from keyboard_executor.core.ai.model_catalog import subscription_model_options
from keyboard_executor.core.models import ScriptValidationError


class SettingsPage(QDialog):
    saved = Signal(object)   # 存檔成功後發出已持久化並正規化的 Settings

    def __init__(self, store: SettingsStore, permission_checks=None, parent=None,
                 auth_service=None, worker_factory=Worker, update_controller=None):
        super().__init__(parent)
        self._store = store
        self._update_controller = update_controller
        if auth_service is None:
            from keyboard_executor.app.ai_auth_service import AiAuthService
            auth_service = AiAuthService()
        self._auth_service = auth_service
        self._worker_factory = worker_factory
        self._auth_worker = None
        self._model_worker = None
        self._codex_models = None
        self._auth_abort = threading.Event()
        self._pending_logout = False
        self.setWindowTitle("設定")
        self.setMinimumSize(420, 320)
        settings = store.load()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._form_page = QWidget()
        layout = QFormLayout(self._form_page)
        self._scroll.setWidget(self._form_page)
        outer.addWidget(self._scroll)
        # 熱鍵改用「錄製擷取」：點欄位再按一次要用的鍵，直接記成 canonical 名稱，
        # 避免手打大小寫/別名與輸入 hook 送出的不一致（緊急停止尤其要一致）。
        self.toggle_edit = _KeyCaptureEdit()
        self.toggle_edit.setText(settings.toggle_key)
        layout.addRow("錄製切換熱鍵", self.toggle_edit)
        self.stop_edit = _KeyCaptureEdit()
        self.stop_edit.setText(settings.stop_key)
        layout.addRow("緊急停止熱鍵", self.stop_edit)
        self.ocr_edit = QLineEdit('新版模型自動辨識（PP-OCRv6 tiny）')
        self.ocr_edit.setReadOnly(True)
        layout.addRow('OCR 模型（所有功能）', self.ocr_edit)
        self.discord_edit = QLineEdit(settings.discord_webhook_url)
        layout.addRow("Discord Webhook 網址（留空＝停用）", self.discord_edit)
        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level_combo.setCurrentText(settings.log_level)
        layout.addRow("日誌等級", self.level_combo)
        self.corner_failsafe_check = QCheckBox("滑鼠左上角緊急停止（游標甩到左上角即停）")
        self.corner_failsafe_check.setChecked(settings.corner_failsafe)
        layout.addRow("", self.corner_failsafe_check)

        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("停用", "")
        self.ai_provider_combo.addItem("ChatGPT（OpenAI）", "openai")
        self.ai_provider_combo.addItem("Claude（Anthropic）", "anthropic")
        self.ai_provider_combo.addItem("OpenRouter", "openrouter")
        idx = self.ai_provider_combo.findData(settings.ai_provider)
        self.ai_provider_combo.setCurrentIndex(max(0, idx))
        layout.addRow("AI 平台", self.ai_provider_combo)
        self.ai_auth_combo = QComboBox()
        self.ai_auth_combo.addItem("API 金鑰（按量計費）", "api_key")
        self.ai_auth_combo.addItem("訂閱登入（使用上方選擇的平台）", "subscription")
        auth_idx = self.ai_auth_combo.findData(settings.ai_auth_mode)
        self.ai_auth_combo.setCurrentIndex(max(0, auth_idx))
        layout.addRow("使用方式", self.ai_auth_combo)
        self.ai_model_edit = QLineEdit(settings.ai_model)
        self.ai_model_edit.setPlaceholderText("API model 名稱")
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        self.ai_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ai_model_combo.lineEdit().setPlaceholderText("選擇或自行輸入 model 名稱")
        self.ai_model_combo.setToolTip("可自行輸入 model 名稱；留空使用平台預設模型")
        self.ai_model_pick_button = QPushButton("選擇模型 ▼")
        self.ai_model_pick_button.clicked.connect(self._show_subscription_models)
        self.ai_model_refresh_button = QPushButton("更新模型")
        self.ai_model_refresh_button.clicked.connect(self._refresh_codex_models)
        self.ai_model_buttons = QWidget()
        model_buttons = QHBoxLayout(self.ai_model_buttons)
        model_buttons.setContentsMargins(0, 0, 0, 0)
        model_buttons.addWidget(self.ai_model_pick_button)
        model_buttons.addWidget(self.ai_model_refresh_button)
        model_buttons.addStretch()
        self.ai_model_host = QWidget()
        model_row = QVBoxLayout(self.ai_model_host)
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.addWidget(self.ai_model_edit)
        model_row.addWidget(self.ai_model_combo)
        model_row.addWidget(self.ai_model_buttons)
        self._initial_ai_model = settings.ai_model
        self._ai_model_context = None
        layout.addRow("AI 模型", self.ai_model_host)
        self.ai_model_status = QLabel("")
        self.ai_model_status.setWordWrap(True)
        layout.addRow("", self.ai_model_status)
        self.ai_key_edit = QLineEdit(settings.ai_api_key)
        self.ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key_label = QLabel("AI API 金鑰")
        layout.addRow(self.ai_key_label, self.ai_key_edit)
        self.ai_key_note = QLabel("API 金鑰以明文儲存於本機 settings.json")
        self.ai_key_note.setWordWrap(True)
        layout.addRow("", self.ai_key_note)

        self.ai_auth_status = QLabel("")
        self.ai_auth_status.setWordWrap(True)
        self.ai_auth_status.setTextInteractionFlags(
            self.ai_auth_status.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ai_auth_status_label = QLabel("訂閱登入狀態")
        layout.addRow(self.ai_auth_status_label, self.ai_auth_status)
        self.ai_auth_buttons = QWidget()
        auth_row = QHBoxLayout(self.ai_auth_buttons)
        auth_row.setContentsMargins(0, 0, 0, 0)
        self.ai_login_button = QPushButton("登入訂閱")
        self.ai_login_button.setProperty("variant", "primary")
        self.ai_device_button = QPushButton("使用裝置碼")
        self.ai_logout_button = QPushButton("登出")
        self.ai_logout_button.setProperty("variant", "ghost")
        auth_row.addWidget(self.ai_login_button)
        auth_row.addWidget(self.ai_device_button)
        auth_row.addWidget(self.ai_logout_button)
        layout.addRow("", self.ai_auth_buttons)
        self.ai_setup_token_edit = QLineEdit()
        self.ai_setup_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_setup_token_edit.setPlaceholderText("貼上 claude setup-token 的輸出")
        self.ai_setup_token_button = QPushButton("儲存 setup-token")
        setup_row_host = QWidget()
        setup_row = QHBoxLayout(setup_row_host)
        setup_row.setContentsMargins(0, 0, 0, 0)
        setup_row.addWidget(self.ai_setup_token_edit, 1)
        setup_row.addWidget(self.ai_setup_token_button)
        self.ai_setup_token_host = setup_row_host
        self.ai_setup_token_label = QLabel("Claude setup-token")
        layout.addRow(self.ai_setup_token_label, setup_row_host)
        self.ai_subscription_note = QLabel("")
        self.ai_subscription_note.setWordWrap(True)
        layout.addRow("", self.ai_subscription_note)
        self.demo_frames_spin = QSpinBox()
        self.demo_frames_spin.setRange(4, 100)
        self.demo_frames_spin.setValue(settings.ai_demo_max_frames)
        self.demo_frames_spin.setToolTip("示範錄製每次送給 AI 的截圖上限；越多越準，但越慢、越耗額度")
        layout.addRow("示範錄製：截圖上限", self.demo_frames_spin)
        self.demo_rounds_spin = QSpinBox()
        self.demo_rounds_spin.setRange(1, 10)
        self.demo_rounds_spin.setValue(settings.ai_demo_max_rounds)
        self.demo_rounds_spin.setToolTip("AI 產生腳本後最多自動試跑、修正幾輪")
        layout.addRow("示範錄製：試跑輪數", self.demo_rounds_spin)
        self._build_update_rows(layout, settings)
        self._auth_profile = settings.ai_auth_profile
        self._auth_profile_provider = settings.ai_provider if self._auth_profile else ""

        self.ai_provider_combo.currentIndexChanged.connect(self._sync_ai_auth_ui)
        self.ai_auth_combo.currentIndexChanged.connect(self._sync_ai_auth_ui)
        self.ai_login_button.clicked.connect(self._on_subscription_login)
        self.ai_device_button.clicked.connect(
            lambda: self._on_subscription_login(device_code=True))
        self.ai_logout_button.clicked.connect(self._on_subscription_logout)
        self.ai_setup_token_button.clicked.connect(self._on_save_setup_token)
        self._sync_ai_auth_ui()

        checks = (permission_checks if permission_checks is not None
                  else default_permission_checks())
        for name, (check, _guide) in checks.items():
            try:
                ok = check()
            except Exception:
                ok = False
            layout.addRow(f"權限：{name}", QLabel("已授權" if ok else "未授權"))

        self.save_button = QPushButton("儲存")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._on_save)
        layout.addRow(self.save_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addRow(self.status_label)
        fit_window_to_available_screen(self, 680, 720)

    def _build_update_rows(self, layout, settings) -> None:
        from keyboard_executor import __version__

        self.version_label = QLabel(f"目前版本 {__version__}")
        layout.addRow("版本", self.version_label)
        self.auto_update_check = QCheckBox("自動檢查更新（有新版會在背景下載，閒置時詢問是否更新）")
        self.auto_update_check.setChecked(settings.auto_update)
        layout.addRow("", self.auto_update_check)
        self.check_update_button = QPushButton("立即檢查更新")
        self.update_status_label = QLabel("")
        self.update_status_label.setWordWrap(True)
        updater = self._update_controller
        if updater is None or not updater.enabled:
            self.check_update_button.setEnabled(False)
            self.update_status_label.setText("從原始碼執行，不檢查更新")
        else:
            self.check_update_button.clicked.connect(self._on_check_update)
            updater.check_finished.connect(self.update_status_label.setText)
        layout.addRow(self.check_update_button, self.update_status_label)

    def _on_check_update(self) -> None:
        self.update_status_label.setText("檢查中…")
        self._update_controller.check_now()

    def _on_save(self) -> None:
        current = self._store.load()   # 保留頁面沒編輯的欄位（ai_privacy_ack）
        try:
            self._store.save(Settings(
                toggle_key=self.toggle_edit.text().strip(),
                stop_key=self.stop_edit.text().strip(),
                ocr_language=current.ocr_language,  # 保留舊設定；新版固定模型不使用語言碼
                log_level=self.level_combo.currentText(),
                discord_webhook_url=self.discord_edit.text().strip(),
                corner_failsafe=self.corner_failsafe_check.isChecked(),
                ai_provider=self.ai_provider_combo.currentData(),
                ai_auth_mode=self.ai_auth_combo.currentData(),
                ai_auth_profile=(self._auth_profile
                                 if self._auth_profile_provider
                                 == self.ai_provider_combo.currentData() else ""),
                ai_model=(self._subscription_model_value()
                          if self.ai_auth_combo.currentData() == "subscription"
                          else self.ai_model_edit.text().strip()),
                ai_api_key=self.ai_key_edit.text().strip(),
                ai_privacy_ack=current.ai_privacy_ack,
                ai_demo_max_frames=self.demo_frames_spin.value(),
                ai_demo_max_rounds=self.demo_rounds_spin.value(),
                auto_update=self.auto_update_check.isChecked()))
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")
            return
        self.status_label.setText("已儲存，已即時套用（執行中的維持原設定）")
        self.saved.emit(self._store.load())
        self.accept()                       # 儲存成功 → 自動關閉（saved 訊號已先發）

    def _sync_ai_auth_ui(self) -> None:
        provider = self.ai_provider_combo.currentData()
        # OpenRouter 沒有訂閱登入；切換平台時移除該選項並回到 API 模式。
        self.ai_auth_combo.blockSignals(True)
        subscription_index = self.ai_auth_combo.findData("subscription")
        if provider == "openrouter" and subscription_index >= 0:
            self.ai_auth_combo.setCurrentIndex(self.ai_auth_combo.findData("api_key"))
            self.ai_auth_combo.removeItem(subscription_index)
        elif provider != "openrouter" and subscription_index < 0:
            self.ai_auth_combo.addItem("訂閱登入（使用上方選擇的平台）", "subscription")
        self.ai_auth_combo.blockSignals(False)
        subscription = self.ai_auth_combo.currentData() == "subscription"
        self._sync_ai_model_ui(provider, subscription)
        self.ai_model_edit.setVisible(not subscription)
        self.ai_model_edit.setPlaceholderText(
            "OpenRouter model ID（自行填寫，例如 provider/model）"
            if provider == "openrouter" else "API model 名稱")
        self.ai_model_combo.setVisible(subscription)
        self.ai_model_buttons.setVisible(subscription)
        self.ai_model_pick_button.setEnabled(subscription and bool(provider))
        self.ai_model_refresh_button.setVisible(subscription and provider == "openai")
        self.ai_model_status.setVisible(subscription)
        for widget in (self.ai_key_label, self.ai_key_edit, self.ai_key_note):
            widget.setVisible(not subscription)
        for widget in (self.ai_auth_status_label, self.ai_auth_status,
                       self.ai_auth_buttons,
                       self.ai_subscription_note):
            widget.setVisible(subscription)
        is_claude = provider == "anthropic"
        self.ai_setup_token_label.setVisible(subscription and is_claude)
        self.ai_setup_token_host.setVisible(subscription and is_claude)
        self.ai_device_button.setVisible(subscription and provider == "openai")
        if not subscription:
            self.ai_auth_status.setText("")
            return
        if provider == "openai":
            self.ai_subscription_note.setText(
                "使用 ChatGPT 訂閱；由官方 Codex 管理登入。Windows 找不到 Codex "
                "時會自動使用 WSL 內的 Codex。按「選擇模型」即可從帳號可用模型中選取，"
                "也可自行輸入模型名稱。")
        elif provider == "anthropic":
            self.ai_subscription_note.setText(
                "使用 Claude Pro/Max 訂閱；由官方 Claude Code 管理登入，也可使用 "
                "setup-token。Windows 找不到 Claude Code 時會自動使用 WSL。"
                "模型別名隨 CLI 更新；也可自行輸入完整模型名稱，實際可用性依帳號與 CLI 版本。")
        else:
            self.ai_subscription_note.setText("請先在上方選擇 ChatGPT 或 Claude。")
            self.ai_auth_status.setText("請先選擇 ChatGPT 或 Claude")
            self.ai_login_button.setText("請先選擇平台")
            self.ai_login_button.setEnabled(False)
            self.ai_device_button.setEnabled(False)
            self.ai_logout_button.setEnabled(False)
            return
        active_profile = (self._auth_profile
                          if self._auth_profile_provider == provider else "")
        if active_profile:
            source = ("Codex/ChatGPT" if provider == "openai"
                      else ("Claude setup-token" if active_profile == "setup-token"
                            else "Claude Code"))
            self.ai_auth_status.setText(f"已連結：{source}")
        else:
            self.ai_auth_status.setText(
                "ChatGPT 尚未登入" if provider == "openai" else "Claude 尚未登入")
        self.ai_login_button.setText(
            "連結 ChatGPT 訂閱" if provider == "openai" else "連結 Claude Code 訂閱")
        idle = self._auth_worker is None
        self.ai_login_button.setEnabled(idle)
        self.ai_device_button.setEnabled(idle)
        self.ai_logout_button.setEnabled(idle and bool(active_profile))

    def _sync_ai_model_ui(self, provider: str, subscription: bool) -> None:
        context = (provider, "subscription" if subscription else "api_key")
        if self._ai_model_context is None and subscription:
            preferred = self._initial_ai_model
        elif self._ai_model_context == context:
            preferred = self._subscription_model_value()
        else:
            preferred = ""
        self._initial_ai_model = ""
        self._ai_model_context = context
        options = subscription_model_options(provider)
        if provider == "openai" and self._codex_models:
            options = (options[0], *self._codex_models)
        self._set_model_options(options, preferred)
        self.ai_model_status.setText(
            "按「選擇模型」展開清單；首次會讀取帳號可用模型。留空使用平台預設。"
            if provider == "openai" else "按「選擇模型」展開清單；也可自行輸入完整模型名稱。")

    def _subscription_model_value(self) -> str:
        text = self.ai_model_combo.currentText().strip()
        # Editable combo 的 currentData 在手打新名稱後仍可能指向舊選項。
        index = self.ai_model_combo.findText(text)
        return str(self.ai_model_combo.itemData(index) or "") if index >= 0 else text

    def _set_model_options(self, options, preferred: str) -> None:
        self.ai_model_combo.clear()
        if not options:
            self.ai_model_combo.addItem("請先選擇 ChatGPT 或 Claude", "")
            self.ai_model_combo.setEnabled(False)
            return
        for label, model in options:
            self.ai_model_combo.addItem(label, model)
        selected = self.ai_model_combo.findData(preferred)
        self.ai_model_combo.setCurrentIndex(selected if selected >= 0 else 0)
        if selected < 0 and preferred:
            self.ai_model_combo.setEditText(preferred)
        self.ai_model_combo.setEnabled(True)

    def _show_subscription_models(self) -> None:
        if not self.ai_model_combo.isEnabled():
            return
        if self._ai_model_context == ("openai", "subscription") and self._codex_models is None:
            self._refresh_codex_models()
        self.ai_model_combo.showPopup()

    def _refresh_codex_models(self) -> None:
        if self._model_worker is not None:
            return
        self.ai_model_refresh_button.setEnabled(False)
        self.ai_model_status.setText("正在讀取 Codex 可用模型…")
        worker = self._worker_factory(lambda _progress: self._auth_service.list_openai_models())
        self._model_worker = worker
        worker.finished.connect(self._on_models_finished)
        worker.failed.connect(self._on_models_failed)
        worker.start()

    def _finish_model_worker(self) -> None:
        if self._model_worker is not None:
            self._model_worker.wait()
            self._model_worker = None
        self.ai_model_refresh_button.setEnabled(True)

    def _on_models_finished(self, options) -> None:
        self._finish_model_worker()
        if not options:
            self._on_models_failed("Codex 尚未提供模型清單；可使用預設選項或自行輸入。")
            return
        self._codex_models = tuple(options)
        if self._ai_model_context == ("openai", "subscription"):
            preferred = self._subscription_model_value()
            self._set_model_options((subscription_model_options("openai")[0], *options),
                                    preferred)
            self.ai_model_status.setText("已更新 Codex 可用模型。")

    def _on_models_failed(self, message: str) -> None:
        self._finish_model_worker()
        if self._ai_model_context == ("openai", "subscription"):
            self.ai_model_status.setText(f"更新模型失敗：{message}")

    def _start_auth_job(self, job) -> None:
        if self._auth_worker is not None:
            return
        self._auth_abort = threading.Event()
        self.ai_auth_status.setText("登入中…請在瀏覽器完成授權")
        self.ai_login_button.setEnabled(False)
        self.ai_device_button.setEnabled(False)
        self.ai_logout_button.setEnabled(False)
        self.ai_setup_token_button.setEnabled(False)
        worker = self._worker_factory(job)
        self._auth_worker = worker
        worker.progress.connect(self._on_auth_progress)
        worker.finished.connect(self._on_auth_finished)
        worker.failed.connect(self._on_auth_failed)
        worker.start()

    def _on_subscription_login(self, checked=False, *, device_code=False) -> None:
        provider = self.ai_provider_combo.currentData()

        def job(progress):
            if provider == "openai":
                return self._auth_service.login_openai(
                    device_code=device_code, on_info=progress,
                    should_abort=self._auth_abort.is_set)
            if provider == "anthropic":
                return self._auth_service.login_claude(
                    should_abort=self._auth_abort.is_set)
            raise ScriptValidationError("請先選擇 AI 供應商")

        self._start_auth_job(job)

    def _on_auth_progress(self, payload: dict) -> None:
        if payload.get("kind") == "device_code":
            code = payload.get("user_code", "")
            self.ai_auth_status.setText(f"請在已開啟的網頁輸入裝置碼：{code}")
        else:
            self.ai_auth_status.setText("瀏覽器已開啟，請完成登入…")

    def _on_auth_finished(self, status: AuthStatus) -> None:
        self._auth_worker = None
        self.ai_login_button.setEnabled(True)
        self.ai_device_button.setEnabled(True)
        self.ai_logout_button.setEnabled(True)
        self.ai_setup_token_button.setEnabled(True)
        if status and status.configured:
            self._auth_profile = status.profile_id
            self._auth_profile_provider = status.provider
            label = f"（{status.account_label}）" if status.account_label else ""
            self.ai_auth_status.setText(f"已連結{label}")
        else:
            if self._pending_logout:
                self._auth_profile = ""
                self._auth_profile_provider = ""
                self.ai_auth_status.setText("已登出")
            else:
                self.ai_auth_status.setText("登入未完成")
        self._pending_logout = False

    def _on_auth_failed(self, message: str) -> None:
        self._auth_worker = None
        self.ai_login_button.setEnabled(True)
        self.ai_device_button.setEnabled(True)
        self.ai_logout_button.setEnabled(True)
        self.ai_setup_token_button.setEnabled(True)
        self.ai_auth_status.setText(message)
        self._pending_logout = False

    def _on_save_setup_token(self) -> None:
        if self._auth_worker is not None:
            return
        token = self.ai_setup_token_edit.text()

        def job(_progress):
            return self._auth_service.save_claude_token(token)

        self.ai_setup_token_edit.clear()
        self._start_auth_job(job)

    def _on_subscription_logout(self) -> None:
        if self._auth_worker is not None:
            return
        provider = self.ai_provider_combo.currentData()
        profile = (self._auth_profile
                   if self._auth_profile_provider == provider else "")
        if not profile:
            return

        def job(_progress):
            self._auth_service.logout(provider, profile)
            return AuthStatus(configured=False, provider=provider)

        self._pending_logout = True
        self._start_auth_job(job)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._auth_abort.set()
        if self._auth_worker is not None:
            self._auth_worker.wait()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        # accept()/reject() 也會關閉對話框；等待查詢結束，避免銷毀仍在跑的 QThread。
        if self._model_worker is not None:
            self._model_worker.wait(-1)
        super().done(result)
