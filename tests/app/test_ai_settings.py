"""Settings AI 欄位驗證與設定頁 AI 區塊。"""
import pytest

from keyboard_executor.app.settings import Settings, SettingsStore, validate_settings
from keyboard_executor.core.models import ScriptValidationError


class SyncWorker:
    class _Signal:
        def __init__(self): self.slot = None
        def connect(self, slot): self.slot = slot
        def emit(self, value):
            if self.slot: self.slot(value)

    def __init__(self, job):
        self.job = job
        self.progress = self._Signal()
        self.finished = self._Signal()
        self.failed = self._Signal()

    def start(self):
        try:
            result = self.job(self.progress.emit)
        except Exception as exc:
            self.failed.emit(f"執行失敗：{exc}")
        else:
            self.finished.emit(result)

    def wait(self): return True


def test_defaults_ai_disabled():
    s = Settings()
    assert s.ai_provider == "" and s.ai_model == "" and s.ai_api_key == ""
    assert s.ai_auth_mode == "api_key" and s.ai_auth_profile == ""
    assert s.ai_privacy_ack is False
    validate_settings(s)   # 預設值必須合法


def test_provider_whitelist():
    with pytest.raises(ScriptValidationError, match="ai_provider"):
        validate_settings(Settings(ai_provider="gemini", ai_model="m", ai_api_key="k"))


def test_provider_set_requires_model_and_key():
    with pytest.raises(ScriptValidationError, match="ai_model"):
        validate_settings(Settings(ai_provider="anthropic", ai_model="", ai_api_key="k"))
    with pytest.raises(ScriptValidationError, match="ai_api_key"):
        validate_settings(Settings(ai_provider="openai", ai_model="m", ai_api_key=""))


def test_subscription_requires_profile_but_not_api_key():
    with pytest.raises(ScriptValidationError, match="ai_auth_profile"):
        validate_settings(Settings(ai_provider="openai", ai_model="m",
                                   ai_auth_mode="subscription"))
    value = validate_settings(Settings(ai_provider="openai", ai_model="m",
                                       ai_auth_mode="subscription",
                                       ai_auth_profile=" codex "))
    assert value.ai_auth_profile == "codex" and value.ai_api_key == ""


def test_subscription_may_use_provider_default_model():
    value = validate_settings(Settings(ai_provider="openai", ai_model="",
                                       ai_auth_mode="subscription",
                                       ai_auth_profile="codex"))
    assert value.ai_model == ""


def test_auth_mode_whitelist():
    with pytest.raises(ScriptValidationError, match="ai_auth_mode"):
        validate_settings(Settings(ai_auth_mode="cookie"))


def test_subscription_profile_is_provider_specific():
    with pytest.raises(ScriptValidationError, match="必須是 codex"):
        validate_settings(Settings(ai_provider="openai", ai_auth_mode="subscription",
                                   ai_auth_profile="claude-cli"))
    with pytest.raises(ScriptValidationError, match="claude-cli 或 setup-token"):
        validate_settings(Settings(ai_provider="anthropic",
                                   ai_auth_mode="subscription",
                                   ai_auth_profile="codex"))


def test_values_normalized_stripped():
    s = validate_settings(Settings(ai_provider="anthropic",
                                   ai_model=" claude-sonnet-5 ",
                                   ai_api_key=" sk-x "))
    assert s.ai_model == "claude-sonnet-5" and s.ai_api_key == "sk-x"


def test_round_trip_through_store(tmp_path):
    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_model="gpt-5-mini",
                        ai_api_key="sk-1", ai_privacy_ack=True))
    loaded = store.load()
    assert loaded.ai_provider == "openai" and loaded.ai_privacy_ack is True


def test_settings_page_has_ai_fields_and_saves(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_privacy_ack=True))   # 既有 ack 不可被頁面存檔洗掉
    page = SettingsPage(store, permission_checks={})
    idx = page.ai_provider_combo.findData("anthropic")
    page.ai_provider_combo.setCurrentIndex(idx)
    page.ai_model_edit.setText("claude-sonnet-5")
    page.ai_key_edit.setText("sk-test")
    page._on_save()
    loaded = store.load()
    assert loaded.ai_provider == "anthropic"
    assert loaded.ai_model == "claude-sonnet-5"
    assert loaded.ai_api_key == "sk-test"
    assert loaded.ai_privacy_ack is True   # 保留，不被重設


def test_settings_page_key_field_password_echo(qapp, tmp_path):
    from PySide6.QtWidgets import QLineEdit

    from keyboard_executor.app.settings_page import SettingsPage

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert page.ai_key_edit.echoMode() == QLineEdit.EchoMode.Password


def test_settings_page_switches_api_and_subscription_fields(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})

    # API 模式只顯示 API key，不留下訂閱欄位的空白標籤。
    assert not page.ai_key_label.isHidden()
    assert page.ai_auth_status_label.isHidden()
    assert page.ai_setup_token_label.isHidden()

    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    assert page.ai_key_label.isHidden()
    assert page.ai_model_edit.isHidden()
    assert not page.ai_model_combo.isHidden()
    assert page.ai_model_combo.isEditable()
    assert page.ai_model_combo.itemData(0) == ""
    assert page.ai_model_combo.itemText(0).startswith("ChatGPT")
    assert page.ai_model_combo.findData("gpt-6.1-sol") >= 0
    assert not page.ai_auth_status_label.isHidden()
    assert page.ai_setup_token_label.isHidden()
    assert not page.ai_device_button.isHidden()

    # Claude 訂閱模式顯示 setup-token 備援欄，並隱藏 OpenAI 裝置碼按鈕。
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("anthropic"))
    assert page.ai_model_combo.itemText(0).startswith("Claude")
    assert page.ai_model_combo.findData("sonnet") >= 0
    assert page.ai_model_combo.findData("gpt-5.6-sol") == -1
    assert not page.ai_setup_token_label.isHidden()
    assert not page.ai_setup_token_host.isHidden()
    assert page.ai_device_button.isHidden()


def test_subscription_requires_explicit_chatgpt_or_claude_choice(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    assert page.ai_provider_combo.currentData() == ""
    assert not page.ai_login_button.isEnabled()
    assert "ChatGPT 或 Claude" in page.ai_auth_status.text()
    assert "Claude" not in page.ai_login_button.text()


def test_subscription_model_selection_is_saved_from_dropdown(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage
    from keyboard_executor.core.ai.auth.models import AuthStatus

    class Auth:
        def login_openai(self, **_kwargs):
            return AuthStatus(True, provider="openai", profile_id="codex",
                              source="codex_app_server")

    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=SyncWorker)
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    page.ai_model_combo.setCurrentIndex(
        page.ai_model_combo.findData("gpt-6.1-sol"))
    page.ai_login_button.click()
    page._on_save()
    assert store.load().ai_model == "gpt-6.1-sol"


def test_unknown_saved_subscription_model_is_preserved(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex", ai_model="future-model"))
    page = SettingsPage(store, permission_checks={})
    assert page.ai_model_combo.currentText() == "future-model"
    page._on_save()
    assert store.load().ai_model == "future-model"


def test_openrouter_settings_roundtrip_and_subscription_rejected(tmp_path):
    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openrouter", ai_api_key="key",
                        ai_model="vendor/custom-model:free"))
    assert store.load().ai_provider == "openrouter"
    assert store.load().ai_model == "vendor/custom-model:free"
    with pytest.raises(ScriptValidationError, match="API"):
        validate_settings(Settings(ai_provider="openrouter", ai_auth_mode="subscription",
                                   ai_auth_profile="codex"))


def test_openrouter_selection_switches_to_api_key_and_saves_custom_model(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={})
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    index = page.ai_provider_combo.findData("openrouter")
    assert index >= 0
    page.ai_provider_combo.setCurrentIndex(index)
    assert page.ai_auth_combo.currentData() == "api_key"
    assert page.ai_auth_combo.findData("subscription") == -1
    assert not page.ai_model_edit.isHidden() and page.ai_auth_buttons.isHidden()
    page.ai_model_edit.setText(" vendor/custom-model:free ")
    page.ai_key_edit.setText("router-key")
    page._on_save()
    assert store.load().ai_model == "vendor/custom-model:free"
    assert store.load().ai_api_key == "router-key"
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("anthropic"))
    assert page.ai_auth_combo.findData("subscription") >= 0


def test_custom_subscription_model_typed_over_selection_is_saved(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="anthropic", ai_auth_mode="subscription",
                        ai_auth_profile="claude-cli", ai_model="sonnet"))
    page = SettingsPage(store, permission_checks={})
    page.ai_model_combo.setEditText(" claude-future-model ")
    page._on_save()
    assert store.load().ai_model == "claude-future-model"


def test_codex_refresh_replaces_catalog_preserves_custom_value(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    class Auth:
        def list_openai_models(self):
            return (("New account model", "account-model"),)

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex", ai_model="custom-model"))
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=SyncWorker)
    page.ai_model_refresh_button.click()
    assert page.ai_model_combo.findData("account-model") >= 0
    assert page.ai_model_combo.findData("gpt-6.1-sol") == -1
    assert page.ai_model_combo.currentText() == "custom-model"
    page.ai_model_combo.setCurrentIndex(page.ai_model_combo.findData("account-model"))
    page._on_save()
    assert store.load().ai_model == "account-model"


@pytest.mark.parametrize("delayed", [False, True])
def test_subscription_picker_opens_account_choices_and_saves_selection(qapp, tmp_path,
                                                                      delayed):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from keyboard_executor.app.settings_page import SettingsPage
    from keyboard_executor.app.theme import DARK_QSS

    class Auth:
        def list_openai_models(self):
            return (("Account model", "account-model"),)

    class DelayedWorker(SyncWorker):
        def start(self):
            pass

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex", ai_model="custom-model"))
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=DelayedWorker if delayed else SyncWorker)
    page.setStyleSheet(DARK_QSS)
    page.show()
    qapp.processEvents()
    try:
        # 深色主題的 editable combo 像輸入框：使用具名按鈕即可展開並選取。
        page.ai_model_pick_button.click()
        qapp.processEvents()
        if delayed:
            assert page.ai_model_combo.view().isVisible()
            SyncWorker.start(page._model_worker)
            qapp.processEvents()
        assert page.ai_model_combo.view().isVisible()
        assert page.ai_model_combo.currentText() == "custom-model"
        assert page.ai_model_combo.itemData(0) == ""
        assert page.ai_model_combo.findData("gpt-6.1-sol") == -1
        choice = page.ai_model_combo.findData("account-model")
        assert choice >= 0
        view = page.ai_model_combo.view()
        target = view.visualRect(page.ai_model_combo.model().index(choice, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target.center())
        page._on_save()
        assert store.load().ai_model == "account-model"
    finally:
        page.ai_model_combo.hidePopup()
        page.close()


def test_subscription_picker_failure_keeps_fallback_choices_open(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    class Auth:
        def list_openai_models(self):
            raise RuntimeError("Codex unavailable")

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex"))
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=SyncWorker)
    page.show()
    qapp.processEvents()
    try:
        page.ai_model_pick_button.click()
        qapp.processEvents()
        assert page.ai_model_combo.view().isVisible()
        assert page.ai_model_combo.findData("gpt-6.1-sol") >= 0
        assert page.ai_model_combo.currentData() == ""
        assert "Codex unavailable" in page.ai_model_status.text()
    finally:
        page.ai_model_combo.hidePopup()
        page.close()


def test_codex_refresh_failure_keeps_selection_and_fallbacks(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    class Auth:
        def list_openai_models(self):
            raise RuntimeError("Codex unavailable")

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex", ai_model="custom-model"))
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=SyncWorker)
    page.ai_model_refresh_button.click()
    assert page.ai_model_combo.findData("gpt-6.1-sol") >= 0
    assert page.ai_model_combo.currentText() == "custom-model"
    assert "Codex unavailable" in page.ai_model_status.text()
    assert page.ai_model_refresh_button.isEnabled()


def test_late_codex_refresh_does_not_replace_claude_model(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    class DelayedWorker(SyncWorker):
        def start(self):
            pass

    class Auth:
        def list_openai_models(self):
            return (("New account model", "account-model"),)

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={},
                        auth_service=Auth(), worker_factory=DelayedWorker)
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    page.ai_model_refresh_button.click()
    worker = page._model_worker
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("anthropic"))
    page.ai_model_combo.setEditText("claude-custom")
    SyncWorker.start(worker)
    assert page.ai_model_combo.currentText() == "claude-custom"
    assert page.ai_model_combo.findData("account-model") == -1
    assert page.ai_model_combo.findData("sonnet") >= 0
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    assert page.ai_model_combo.findData("account-model") >= 0


def test_clearing_subscription_combo_saves_provider_default(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage

    store = SettingsStore(tmp_path)
    store.save(Settings(ai_provider="anthropic", ai_auth_mode="subscription",
                        ai_auth_profile="claude-cli", ai_model="sonnet"))
    page = SettingsPage(store, permission_checks={})
    page.ai_model_combo.clearEditText()
    page._on_save()
    assert store.load().ai_model == ""


def test_subscription_login_saves_profile_without_api_key(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage
    from keyboard_executor.core.ai.auth.models import AuthStatus

    class Auth:
        def login_openai(self, **kwargs):
            kwargs["on_info"]({"kind": "browser"})
            return AuthStatus(True, provider="openai", profile_id="codex",
                              source="codex_app_server", account_label="me@test")

    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={}, auth_service=Auth(),
                        worker_factory=SyncWorker)
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("openai"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    page.ai_model_combo.setCurrentIndex(
        page.ai_model_combo.findData("gpt-5.6-sol"))
    page.ai_login_button.click()
    assert "me@test" in page.ai_auth_status.text()
    page._on_save()
    loaded = store.load()
    assert loaded.ai_auth_mode == "subscription"
    assert loaded.ai_auth_profile == "codex" and loaded.ai_api_key == ""


def test_claude_setup_token_clears_input_and_selects_profile(qapp, tmp_path):
    from keyboard_executor.app.settings_page import SettingsPage
    from keyboard_executor.core.ai.auth.models import AuthStatus

    class Auth:
        def save_claude_token(self, token):
            assert token == "oauth-token-secret-long-enough"
            return AuthStatus(True, provider="anthropic", profile_id="setup-token",
                              source="anthropic_setup_token")

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={},
                        auth_service=Auth(), worker_factory=SyncWorker)
    page.ai_provider_combo.setCurrentIndex(page.ai_provider_combo.findData("anthropic"))
    page.ai_auth_combo.setCurrentIndex(page.ai_auth_combo.findData("subscription"))
    page.ai_setup_token_edit.setText("oauth-token-secret-long-enough")
    page.ai_setup_token_button.click()
    assert page.ai_setup_token_edit.text() == ""
    assert page._auth_profile == "setup-token"
