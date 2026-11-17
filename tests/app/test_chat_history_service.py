"""Persistence is opt-in at the service boundary and uses the app data root."""
import threading
from types import SimpleNamespace

import pytest

from keyboard_executor.app.chat_reply_service import build_chat_session
from keyboard_executor.app.settings import Settings
from keyboard_executor.core.chat_observer import ChatMessage
from keyboard_executor.core.models import script_from_dict
from tests.core.test_chat_reply_config import config_data, script_data


def build_with_store(monkeypatch, **options):
    from keyboard_executor.core import chat_reply_monitor
    captured = {}

    def session(*_args, **kwargs):
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(chat_reply_monitor, "BackgroundChatReplySession", session)
    return build_chat_session(
        Settings(ai_provider="openai", ai_model="test-model", ai_api_key="test-key"),
        None, script_from_dict(script_data(config_data())), object(), threading.Event(), None,
        provider_factory=lambda *_: object(), **options)


def test_service_history_root_creates_store_beneath_app_data_directory(tmp_path, monkeypatch):
    from keyboard_executor.storage.chat_history import ChatHistoryStore
    session_options = build_with_store(monkeypatch, history_root=tmp_path)
    record = ChatMessage(1, "map", "朋友", "你好")
    session_options["history_store"].append("自己", "朋友", record)
    assert ChatHistoryStore(tmp_path / ".chat-history").load("自己") == {"朋友": [record]}
    assert list(tmp_path.glob("*.json")) == []


def test_service_default_does_not_enable_persistence(monkeypatch):
    assert build_with_store(monkeypatch).get("history_store") is None


@pytest.mark.parametrize("builder,service_name,factory", [
    ("_build_chat_reply", "chat_reply_service", "build_chat_session"),
    ("_build_sequence_input", "sequence_input_service", "build_sequence_runtime"),
])
def test_main_window_passes_its_data_directory_to_chat_history(
        tmp_path, monkeypatch, builder, service_name, factory):
    from importlib import import_module
    from keyboard_executor.app.main_window import MainWindow
    service = import_module(f"keyboard_executor.app.{service_name}")
    captured = {}

    def build(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(service, factory, build)
    window = SimpleNamespace(_settings=object(), _ai_auth_service=object(), _data_dir=tmp_path)
    getattr(MainWindow, builder)(window, object(), object(), threading.Event(), None)
    assert captured["history_root"] == tmp_path


@pytest.mark.parametrize("persistent", [True, False])
def test_combined_service_only_forwards_history_root_when_supplied(tmp_path, monkeypatch, persistent):
    from dataclasses import replace
    from keyboard_executor.app import chat_reply_service, sequence_input_service
    from tests.core.test_player_flow import make_platform
    captured = {}

    def build_chat(*_args, **kwargs):
        captured.update(kwargs)

    # Isolate chat assembly from the independent image workflow and its provider calls.
    monkeypatch.setattr(chat_reply_service, "build_chat_session", build_chat)
    monkeypatch.setattr(sequence_input_service, "SequenceRecognizer", lambda *_: object())
    monkeypatch.setattr(sequence_input_service, "preflight", lambda *_: None)
    monkeypatch.setattr(sequence_input_service, "SequenceWatcher", lambda *_: None)
    monkeypatch.setattr(sequence_input_service, "SequenceSubmitter", lambda *_: object())
    platform, _ = make_platform()
    platform = replace(platform, screen_capture=object(), ocr_engine=object())
    script = SimpleNamespace(settings=SimpleNamespace(
        sequence_input=SimpleNamespace(enabled=True, mode="sequence")))
    options = {"history_root": tmp_path} if persistent else {}
    sequence_input_service.build_sequence_runtime(
        Settings(ai_provider="openai", ai_model="test-model", ai_api_key="test-key"),
        None, script, platform, threading.Event(), None,
        provider_factory=lambda *_: object(), **options)
    if persistent:
        assert captured["history_root"] == tmp_path
    else:
        assert "history_root" not in captured
    assert captured["owns_ocr"] is False
