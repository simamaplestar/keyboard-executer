import pytest

from keyboard_executor.platforms.darwin.permissions import (
    ACCESSIBILITY_GUIDE,
    check_accessibility,
)


def test_check_accessibility_true_when_trusted():
    assert check_accessibility(_ax_is_trusted=lambda: 1) is True


def test_check_accessibility_false_when_not_trusted():
    assert check_accessibility(_ax_is_trusted=lambda: 0) is False


def test_guide_mentions_system_settings():
    assert "輔助使用" in ACCESSIBILITY_GUIDE


def test_request_accessibility_prompts_using_ax_options():
    from keyboard_executor.platforms.darwin.permissions import request_accessibility
    options = []
    assert request_accessibility(_request=lambda values: options.append(values) or True,
                                 _prompt_key="AXTrustedCheckOptionPrompt") is True
    assert options == [{"AXTrustedCheckOptionPrompt": True}]


def test_check_screen_recording_uses_injected_preflight():
    from keyboard_executor.platforms.darwin.permissions import check_screen_recording
    assert check_screen_recording(_preflight=lambda: True) is True
    assert check_screen_recording(_preflight=lambda: 0) is False


def test_check_input_monitoring_uses_injected_preflight():
    from keyboard_executor.platforms.darwin.permissions import check_input_monitoring
    assert check_input_monitoring(_preflight=lambda: 1) is True
    assert check_input_monitoring(_preflight=lambda: False) is False


def test_system_settings_url_exact_strings():
    """spec §10「直達系統設定的連結」：三分頁的 deep link 精確字串。"""
    from keyboard_executor.platforms.darwin.permissions import system_settings_url
    assert system_settings_url("accessibility") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_Accessibility")
    assert system_settings_url("screen-recording") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ScreenCapture")
    assert system_settings_url("input-monitoring") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ListenEvent")


def test_system_settings_url_rejects_unknown_pane():
    from keyboard_executor.platforms.darwin.permissions import system_settings_url
    with pytest.raises(ValueError, match="未知的權限分頁"):
        system_settings_url("camera")


def test_request_screen_recording_uses_injected_request():
    from keyboard_executor.platforms.darwin.permissions import request_screen_recording
    assert request_screen_recording(_request=lambda: 1) is True
    assert request_screen_recording(_request=lambda: 0) is False


def test_request_input_monitoring_uses_injected_request():
    from keyboard_executor.platforms.darwin.permissions import request_input_monitoring
    assert request_input_monitoring(_request=lambda: True) is True
    assert request_input_monitoring(_request=lambda: False) is False
