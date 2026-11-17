from keyboard_executor.app.settings import SettingsStore
from keyboard_executor.app.settings_page import SettingsPage


def test_fixed_ocr_model_display_preserves_legacy_language_setting(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings
    store = SettingsStore(tmp_path)
    store.save(Settings(ocr_language='japan'))
    page = SettingsPage(store, permission_checks={})
    assert page.ocr_edit.isReadOnly()
    assert 'PP-OCRv6 tiny' in page.ocr_edit.text()
    page.save_button.click()
    assert store.load().ocr_language == 'japan'


def test_settings_page_hotkeys_use_capture_widget(qapp, tmp_path):
    from keyboard_executor.app.key_capture import _KeyCaptureEdit
    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert isinstance(page.toggle_edit, _KeyCaptureEdit)   # 熱鍵改用錄製擷取
    assert isinstance(page.stop_edit, _KeyCaptureEdit)


def test_settings_page_is_scrollable_on_small_screens(qapp, tmp_path):
    from PySide6.QtWidgets import QScrollArea

    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert isinstance(page._scroll, QScrollArea)
    assert page._scroll.widgetResizable()
    assert page.minimumHeight() <= 320
    page.resize(420, 320)
    page.show()
    qapp.processEvents()
    assert page._scroll.verticalScrollBar().maximum() > 0
    page.close()


def test_settings_page_constructs_and_save_persists(qapp, tmp_path):
    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={})
    page.stop_edit.setText("f8")
    page.level_combo.setCurrentText("WARNING")
    page.save_button.click()
    assert "已儲存" in page.status_label.text()
    loaded = store.load()
    assert loaded.stop_key == "f8" and loaded.log_level == "WARNING"


def test_settings_page_has_discord_field_default_empty(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    assert page.discord_edit.text() == ""


def test_settings_page_saves_discord_webhook(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store)
    page.discord_edit.setText("https://discord.com/api/webhooks/1/abc")
    page.save_button.click()
    assert store.load().discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert "已儲存" in page.status_label.text()


def test_settings_page_emits_saved_with_persisted_settings(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store)
    seen = []
    page.saved.connect(seen.append)
    page.stop_edit.setText("f8")
    page.save_button.click()
    assert len(seen) == 1
    assert isinstance(seen[0], Settings) and seen[0].stop_key == "f8"


def test_settings_page_does_not_emit_saved_on_validation_failure(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    seen = []
    page.saved.connect(seen.append)
    page.stop_edit.setText("")               # 空熱鍵 → 驗證失敗
    page.save_button.click()
    assert seen == []
    assert "儲存失敗" in page.status_label.text()


def test_settings_page_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))     # 預設 f9/f10/auto/INFO 有效
    page.save_button.click()
    assert page.result() == QDialog.DialogCode.Accepted          # 成功 → 關閉


def test_settings_page_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    page = SettingsPage(SettingsStore(tmp_path))
    page.stop_edit.setText("")                        # 空熱鍵 → 驗證失敗
    page.save_button.click()
    assert page.result() != QDialog.DialogCode.Accepted          # 失敗 → 不關
    assert "儲存失敗" in page.status_label.text()


def test_corner_failsafe_checkbox_saves(qapp, tmp_path):
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={})
    page.corner_failsafe_check.setChecked(False)
    page.save_button.click()
    assert store.load().corner_failsafe is False


def test_corner_failsafe_checkbox_reflects_loaded(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    store.save(Settings(corner_failsafe=False))
    page = SettingsPage(store, permission_checks={})
    assert page.corner_failsafe_check.isChecked() is False


def test_demo_limits_round_trip(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    store = SettingsStore(tmp_path)
    store.save(Settings(ai_demo_max_frames=20, ai_demo_max_rounds=5))
    page = SettingsPage(store, permission_checks={})
    assert page.demo_frames_spin.value() == 20
    assert page.demo_rounds_spin.value() == 5
    assert page.demo_frames_spin.minimum() == 4 and page.demo_frames_spin.maximum() == 100
    page.demo_frames_spin.setValue(12)
    page.demo_rounds_spin.setValue(2)
    page.save_button.click()
    saved = store.load()
    assert saved.ai_demo_max_frames == 12
    assert saved.ai_demo_max_rounds == 2


class _FakeUpdater:
    def __init__(self, enabled=True):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            check_finished = Signal(str)
        self._sig = _Sig()
        self.check_finished = self._sig.check_finished
        self.enabled = enabled
        self.checks = 0

    def check_now(self):
        self.checks += 1


def test_settings_page_saves_auto_update(qapp, tmp_path):
    store = SettingsStore(tmp_path)
    page = SettingsPage(store, permission_checks={})
    assert page.auto_update_check.isChecked() is True
    page.auto_update_check.setChecked(False)
    page.save_button.click()
    assert store.load().auto_update is False


def test_settings_page_shows_current_version(qapp, tmp_path):
    from keyboard_executor import __version__
    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert __version__ in page.version_label.text()


def test_settings_page_check_now_shows_result(qapp, tmp_path):
    updater = _FakeUpdater()
    page = SettingsPage(SettingsStore(tmp_path), permission_checks={}, update_controller=updater)
    assert page.check_update_button.isEnabled()
    page.check_update_button.click()
    assert updater.checks == 1
    assert "檢查中" in page.update_status_label.text()
    updater.check_finished.emit("已是最新版本 0.5.0")
    assert page.update_status_label.text() == "已是最新版本 0.5.0"


def test_settings_page_without_controller_disables_button(qapp, tmp_path):
    page = SettingsPage(SettingsStore(tmp_path), permission_checks={})
    assert not page.check_update_button.isEnabled()
    assert "原始碼" in page.update_status_label.text()
    disabled = SettingsPage(SettingsStore(tmp_path), permission_checks={},
                            update_controller=_FakeUpdater(enabled=False))
    assert not disabled.check_update_button.isEnabled()
