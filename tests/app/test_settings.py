import logging

import pytest

from keyboard_executor.app.settings import (
    Settings,
    SettingsStore,
    ocr_lang_from_setting,
    validate_settings,
)
from keyboard_executor.core.models import ScriptValidationError


def test_defaults_when_file_missing(tmp_path):
    settings = SettingsStore(tmp_path).load()
    assert settings == Settings()
    assert (settings.toggle_key, settings.stop_key) == ("f9", "f10")
    assert (settings.ocr_language, settings.log_level) == ("auto", "INFO")


def test_save_load_round_trip(tmp_path):
    store = SettingsStore(tmp_path)
    saved = Settings(toggle_key="f7", stop_key="f8", ocr_language="ja",
                     log_level="DEBUG")
    path = store.save(saved)
    assert path == tmp_path / "settings.json"
    assert store.load() == saved


def test_corrupt_json_falls_back_to_defaults(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="keyboard_executor.app.settings")
    (tmp_path / "settings.json").write_text("{壞掉", encoding="utf-8")
    assert SettingsStore(tmp_path).load() == Settings()
    assert "設定檔載入失敗" in caplog.text


def test_hotkeys_normalized_to_canonical_lowercase(tmp_path):
    # 使用者可能打大寫/含空白（如 "F10"）；必須正規化成 hook 送出的小寫 canonical，
    # 否則 SessionGuard 的 event.key == stop_key 永遠不相等，緊急停止完全無效。
    s = validate_settings(Settings(toggle_key="F9", stop_key="F10"))
    assert (s.toggle_key, s.stop_key) == ("f9", "f10")
    store = SettingsStore(tmp_path)
    store.save(Settings(toggle_key="F9", stop_key=" F10 "))
    assert store.load().stop_key == "f10"       # 存大寫→讀回小寫


def test_configured_uppercase_stop_key_triggers_guard():
    # 端到端：使用者設 "F10" → 正規化 → SessionGuard 收到 hook 的小寫 "f10" 事件即停止
    import threading

    from keyboard_executor.core.guard import SessionGuard
    from keyboard_executor.platforms.base import EventKind, InputEvent

    stop_key = validate_settings(Settings(stop_key="F10")).stop_key
    stop_event = threading.Event()
    guard = SessionGuard(hook=None, stop_event=stop_event, stop_key=stop_key)
    guard.handle(InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=0, key="f10"))
    assert stop_event.is_set()


def test_invalid_hotkey_rejected(tmp_path):
    with pytest.raises(ScriptValidationError, match="不是可用的按鍵名稱"):
        SettingsStore(tmp_path).save(Settings(stop_key="not-a-key"))
    with pytest.raises(ScriptValidationError, match="不可相同"):
        validate_settings(Settings(toggle_key="f9", stop_key="f9"))


def test_invalid_log_level_rejected(tmp_path):
    with pytest.raises(ScriptValidationError, match="log_level"):
        SettingsStore(tmp_path).save(Settings(log_level="VERBOSE"))


def test_ocr_lang_from_setting():
    assert ocr_lang_from_setting("auto") is None
    assert ocr_lang_from_setting("") is None
    assert ocr_lang_from_setting("  en ") == "en"
    assert ocr_lang_from_setting("chinese_cht") == "chinese_cht"


def test_discord_webhook_defaults_empty():
    assert Settings().discord_webhook_url == ""


def test_validate_accepts_valid_and_empty_webhook():
    ok = validate_settings(Settings(
        discord_webhook_url="https://discord.com/api/webhooks/1/abc"))
    assert ok.discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    assert validate_settings(Settings(discord_webhook_url="")).discord_webhook_url == ""


def test_validate_strips_and_rejects_malformed_webhook():
    stripped = validate_settings(Settings(
        discord_webhook_url="  https://discord.com/api/webhooks/1/abc  "))
    assert stripped.discord_webhook_url == "https://discord.com/api/webhooks/1/abc"
    with pytest.raises(ScriptValidationError, match="discord_webhook_url"):
        validate_settings(Settings(discord_webhook_url="http://example.com/nope"))
    with pytest.raises(ScriptValidationError, match="discord_webhook_url"):
        validate_settings(Settings(discord_webhook_url="https://example.com/nope"))


def test_load_old_settings_without_webhook_field(tmp_path):
    import json
    (tmp_path / "settings.json").write_text(json.dumps(
        {"toggle_key": "f9", "stop_key": "f10",
         "ocr_language": "auto", "log_level": "INFO"}), encoding="utf-8")
    assert SettingsStore(tmp_path).load().discord_webhook_url == ""


def test_corner_failsafe_defaults_true():
    from keyboard_executor.app.settings import Settings
    assert Settings().corner_failsafe is True


def test_corner_failsafe_round_trips(tmp_path):
    from keyboard_executor.app.settings import Settings, SettingsStore
    store = SettingsStore(tmp_path)
    store.save(Settings(corner_failsafe=False))
    assert store.load().corner_failsafe is False


def test_corner_failsafe_rejects_non_bool():
    import pytest
    from keyboard_executor.app.settings import Settings, validate_settings
    from keyboard_executor.core.models import ScriptValidationError
    with pytest.raises(ScriptValidationError):
        validate_settings(Settings(corner_failsafe="yes"))


def test_settings_demo_limits_validated():
    import pytest
    from keyboard_executor.app.settings import Settings, validate_settings
    from keyboard_executor.core.models import ScriptValidationError
    s = Settings()
    assert s.ai_demo_max_frames == 30
    assert s.ai_demo_max_rounds == 3
    validate_settings(Settings(ai_demo_max_frames=4, ai_demo_max_rounds=10))
    for bad in (dict(ai_demo_max_frames=3), dict(ai_demo_max_frames=101),
                dict(ai_demo_max_rounds=0), dict(ai_demo_max_rounds=11),
                dict(ai_demo_max_frames=True)):
        with pytest.raises(ScriptValidationError):
            validate_settings(Settings(**bad))


def test_auto_update_defaults_true_and_validates():
    assert Settings().auto_update is True
    validate_settings(Settings(auto_update=False))
    with pytest.raises(ScriptValidationError, match="auto_update"):
        validate_settings(Settings(auto_update="yes"))
