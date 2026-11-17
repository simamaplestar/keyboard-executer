import threading

import pytest

from keyboard_executor.app.settings import Settings
from keyboard_executor.core.models import ScriptValidationError, script_from_dict
from tests.core.test_chat_reply_config import config_data, script_data


def test_disabled_ai_cannot_silently_run_chat_script():
    from keyboard_executor.app.chat_reply_service import build_chat_session
    script = script_from_dict(script_data(config_data()))
    with pytest.raises(ScriptValidationError, match="AI"):
        build_chat_session(Settings(), None, script, object(), threading.Event(), None)


def test_both_channels_disabled_do_not_require_provider_or_ocr():
    from keyboard_executor.app.chat_reply_service import build_chat_session
    script = script_from_dict(script_data({"enabled": True, "reply_map": False,
                                           "reply_whisper": False}))
    assert build_chat_session(Settings(), None, script, object(), threading.Event(), None) is None


def test_chat_uses_configured_custom_model_and_key_without_subscription_lookup():
    from keyboard_executor.app.chat_reply_service import build_chat_session
    script = script_from_dict(script_data(config_data()))
    settings = Settings(ai_provider="openai", ai_model="custom-model", ai_api_key="test-key")
    received = []
    provider = object()

    def factory(*args, **kwargs):
        received.append((args, kwargs))
        return provider

    session = build_chat_session(settings, None, script, object(), threading.Event(), None,
                                 provider_factory=factory)
    assert callable(session)
    assert received == [(("openai", "test-key", "custom-model"), {})]


def test_subscription_chat_requires_valid_auth_profile():
    from keyboard_executor.app.chat_reply_service import build_chat_session
    script = script_from_dict(script_data(config_data()))
    settings = Settings(ai_provider="anthropic", ai_auth_mode="subscription",
                        ai_auth_profile="claude-cli")

    class Auth:
        def resolve_profile(self, _):
            return None

    with pytest.raises(ScriptValidationError, match="登入"):
        build_chat_session(settings, Auth(), script, object(), threading.Event(), None)


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_fast_reasoning_is_requested_only_for_openai_subscription_chat(provider):
    from keyboard_executor.app.chat_reply_service import build_chat_session
    from keyboard_executor.core.ai.auth.models import AuthProfile
    profile = AuthProfile(provider, 'test', '')
    class Auth:
        def resolve_profile(self, _):
            return profile
    received = []
    def factory(*args, **kwargs):
        received.append((args, kwargs))
        return object()
    build_chat_session(
        Settings(ai_provider=provider, ai_auth_mode='subscription', ai_model='custom'),
        Auth(), script_from_dict(script_data(config_data())), object(), threading.Event(), None,
        provider_factory=factory)
    assert received[0][0] == (provider, '', 'custom')
    assert received[0][1].get('reasoning_effort') == ('low' if provider == 'openai' else None)


def test_chat_ocr_is_isolated_from_original_player_platform():
    from dataclasses import replace
    from keyboard_executor.app.chat_reply_service import build_chat_session
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
    from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine
    from tests.core.test_player_flow import make_platform

    platform, _ = make_platform()
    original = RapidOcrEngine()
    platform = replace(platform, ocr_engine=original)
    session = build_chat_session(
        Settings(ai_provider="openai", ai_model="custom", ai_api_key="test-key"), None,
        script_from_dict(script_data(config_data())), platform, threading.Event(), None,
        provider_factory=lambda *_: object())
    try:
        assert isinstance(session._platform.ocr_engine, ProcessOcrEngine)
        assert platform.ocr_engine is original
        assert session._platform.input_backend is platform.input_backend
        assert session._platform.ocr_engine._process is None  # 建構不等待 spawn 或載入
    finally:
        session.close()
