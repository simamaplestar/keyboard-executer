"""Fatal chat failures reach Discord through the GUI service and real player."""
import json
import threading
from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace

import cv2
import pytest

from keyboard_executor.app.chat_reply_service import build_chat_session
from keyboard_executor.app.settings import Settings
from keyboard_executor.core import discord_notify
from keyboard_executor.core.ai.provider import AiAborted, AiProviderError
from keyboard_executor.core.chat_observer import ChatMessage
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.factory import Platform
from tests.core.test_chat_reply_channel import ChannelScene
from tests.core.test_chat_reply_config import config_data, script_data
from tests.core.test_player_flow import make_window
from tests.fakes import FakeInputBackend, FakeOcrEngine, FakeWindowManager


@pytest.fixture
def discord(monkeypatch):
    queued, sent = [], []
    transport = SimpleNamespace(queued=queued, sent=sent, dispatch_error=None,
                                dispatch_attempts=0)

    def dispatch(job):
        transport.dispatch_attempts += 1
        if transport.dispatch_error is not None:
            raise transport.dispatch_error
        queued.append(job)

    monkeypatch.setattr(discord_notify, "_daemon_dispatch", dispatch)

    def post(url, data, timeout, content_type):
        sent.append((url, json.loads(data)["content"]))

    monkeypatch.setattr(discord_notify, "_urllib_post", post)
    return transport


def _settings():
    return Settings(ai_provider="openai", ai_model="fake", ai_api_key="test",
                    discord_webhook_url="https://example.invalid/test-only")


def _ready_reply(session):
    message = ChatMessage(1, "whisper", "朋友", "在嗎")
    session._ai_result = Future()
    session._ai_result.set_result(([message], [(message, "有收到")]))


@pytest.fixture
def runtime(discord):
    config = config_data()
    config["region"] = [10, 300, 320, 200]
    script = script_from_dict(script_data(config))
    win = replace(make_window("遊戲"), x=100, y=80, width=800, height=600,
                  is_active=True)
    backend, stop, records = FakeInputBackend(), threading.Event(), []
    platform = Platform(backend, FakeWindowManager([win]), ocr_engine=FakeOcrEngine())
    session = build_chat_session(_settings(), None, script, platform, stop, records.append,
                                 provider_factory=lambda *_: object())
    scene = ChannelScene(session, win, backend)
    # Completed AI data needs a real incoming sender in the final chat frame.
    # Keep pixel parsing/identity checks active, then exercise the actual input
    # failures below; a history-only sender must now be skipped before typing.
    capture, recognize = scene.capture, scene.recognize

    def capture_chat(region):
        image = capture(region)
        if scene.last_region == (10, 300, 320, 200):
            cv2.putText(image, 'Whisper', (10, 137), cv2.FONT_HERSHEY_SIMPLEX,
                        .55, (0, 245, 20), 1, cv2.LINE_AA)
        return image

    def recognize_chat(image):
        boxes = recognize(image)
        if scene.last_region == (10, 300, 320, 200):
            boxes.append(TextBox('朋友[CH.301]>>在嗎', 10, 120, 300, 22, .99))
        return boxes

    scene.capture, scene.recognize = capture_chat, recognize_chat
    session._platform = replace(platform, screen_capture=scene, ocr_engine=scene)
    # Supply completed AI data at an action boundary; no external AI or monitor
    # scheduling is needed to exercise the production confirmation/send guards.
    session._window = win
    session._next_check = float("inf")
    _ready_reply(session)
    runtime = SimpleNamespace(session=session, script=script, win=win, backend=backend,
                              stop=stop, scene=scene, records=records)
    yield runtime
    stop.set()
    session.close()


def _play(runtime):
    return Player(runtime.session._platform, stop_event=runtime.stop,
                  on_action_boundary=runtime.session).play(runtime.script)


def _deliver(discord):
    while discord.queued:
        discord.queued.pop(0)()


@pytest.mark.parametrize("failure,reason,sent", [
    ("recipient", "密語對象", False),
    ("window", "視窗", False),
    ("text", "文字輸入失敗", False),
    ("submit", "送出", False),
    ("cleanup", "已送出", True),
])
def test_fatal_delivery_stops_player_and_notifies_original_reason(runtime, discord,
                                                                failure, reason, sent):
    scene = runtime.scene
    if failure in ("recipient", "text"):
        # 回覆失敗本身不停腳本；頻道選單也壞掉、聊天關不掉時才停止。
        scene.missing_menu = True
    if failure == "recipient":
        scene.open_recipient = False
    elif failure == "window":
        original = runtime.backend.type_text

        def move_window(text):
            original(text)
            runtime.session._platform.window_manager.refresh = lambda _: replace(
                runtime.win, x=runtime.win.x + 10)

        runtime.backend.type_text = move_window
    elif failure == "text":
        original = runtime.backend.type_text

        def fail_text(text):
            if text == "有收到":
                raise OSError("文字輸入失敗")
            original(text)

        runtime.backend.type_text = fail_text
    elif failure == "submit":
        scene.ignored_enters = 100
    else:
        scene.missing_menu = True

    result = _play(runtime)

    assert not result.ok and reason in result.error
    assert result.actions_run == 0
    assert bool(scene.sent) is sent
    assert not any(call[:2] == ("key_press", "a") for call in runtime.backend.calls)
    assert not discord.sent  # The failing player never waits for HTTP.
    _deliver(discord)
    assert len(discord.sent) == 1
    url, message = discord.sent[0]
    assert url == "https://example.invalid/test-only"
    assert "聊天" in message and "AI" in message and "停止" in message
    assert result.error.removeprefix("未預期錯誤: ") in message


def test_repeated_failure_and_close_send_only_one_notification(runtime, discord):
    runtime.scene.open_recipient = False
    runtime.scene.missing_menu = True     # 聊天關不掉才是致命失敗
    for _ in range(2):
        _ready_reply(runtime.session)
        with pytest.raises(RuntimeError, match="密語對象"):
            runtime.session(runtime.script, runtime.win)
    runtime.session.close()
    _deliver(discord)
    assert len(discord.sent) == 1


@pytest.mark.parametrize("failed_delivery", [False, True])
def test_close_failure_notifies_once_without_replacing_prior_reason(runtime, discord,
                                                                  failed_delivery):
    if failed_delivery:
        runtime.scene.open_recipient = False
        runtime.scene.missing_menu = True
        result = _play(runtime)
        assert not result.ok
    failure = RuntimeError("聊天 OCR 關閉失敗")

    def fail_close():
        raise failure

    runtime.scene.close = fail_close
    try:
        with pytest.raises(RuntimeError) as raised:
            runtime.session.close()
        assert raised.value is failure
    finally:
        del runtime.scene.close
    _deliver(discord)
    assert len(discord.sent) == 1
    assert ("密語對象" if failed_delivery else str(failure)) in discord.sent[0][1]


def test_successful_reply_resumes_player_without_discord(runtime, discord):
    result = _play(runtime)
    assert result.ok and result.actions_run == 1
    assert runtime.scene.sent == [("有收到", "whisper")]
    assert runtime.scene.channel == "public"
    assert not discord.queued and not discord.sent


@pytest.mark.parametrize("prepared", [None, "empty", "network", "format", "abort"])
def test_nonfatal_ai_results_continue_without_discord(runtime, discord, prepared):
    future = runtime.session._ai_result = Future()
    if prepared == "network":
        future.set_exception(AiProviderError("連線失敗"))
    elif prepared == "format":
        future.set_exception(ValueError("AI 回覆格式不正確"))
    elif prepared == "abort":
        future.set_exception(AiAborted())
    else:
        future.set_result(([], []) if prepared == "empty" else None)
    result = _play(runtime)
    assert result.ok and result.actions_run == 1
    assert not runtime.scene.sent
    assert not discord.queued and not discord.sent


def test_ocr_failure_skips_reply_and_continues_without_discord(runtime, discord):
    def fail_ocr(_):
        raise RuntimeError("OCR 暫時無法辨識")

    runtime.scene.recognize = fail_ocr
    result = _play(runtime)
    assert result.ok and result.actions_run == 1
    assert not runtime.scene.sent
    assert not discord.queued and not discord.sent


def test_manual_stop_during_chat_never_notifies(runtime, discord):
    original = runtime.backend.type_text

    def stop_after_input(text):
        original(text)
        runtime.stop.set()

    runtime.backend.type_text = stop_after_input
    result = _play(runtime)
    assert not result.ok and "手動停止" in result.error
    assert not runtime.scene.sent
    assert not discord.queued and not discord.sent


def test_provider_initialization_failure_preserves_exception_and_notifies(discord):
    failure = RuntimeError("AI 供應商初始化失敗")

    def broken_provider(*_):
        raise failure

    script = script_from_dict(script_data(config_data()))
    with pytest.raises(RuntimeError) as raised:
        build_chat_session(_settings(), None, script, object(), threading.Event(), None,
                           provider_factory=broken_provider)
    assert raised.value is failure
    _deliver(discord)
    assert len(discord.sent) == 1
    assert "聊天" in discord.sent[0][1] and str(failure) in discord.sent[0][1]


def test_dispatch_failure_cannot_replace_original_delivery_error(runtime, discord):
    discord.dispatch_error = RuntimeError("Discord 背景執行緒無法啟動")
    original = runtime.backend.type_text

    def fail_text(text):
        if text == "有收到":
            raise OSError("原始文字輸入失敗")
        original(text)

    runtime.backend.type_text = fail_text
    runtime.scene.missing_menu = True     # 聊天關不掉才停止並通知
    result = _play(runtime)
    assert not result.ok and "原始文字輸入失敗" in result.error
    assert "Discord" not in result.error
    assert discord.dispatch_attempts == 1


@pytest.mark.parametrize("cancel", ["stop", "ai-aborted", "no-webhook"])
def test_cancelled_or_unconfigured_initialization_never_sends_discord(discord, cancel):
    failure = AiAborted() if cancel == "ai-aborted" else RuntimeError("AI 初始化失敗")
    stop = threading.Event()
    if cancel == "stop":
        stop.set()
    settings = replace(_settings(), discord_webhook_url="") if cancel == "no-webhook" else _settings()

    def broken_provider(*_):
        raise failure

    with pytest.raises(type(failure)) as raised:
        build_chat_session(settings, None, script_from_dict(script_data(config_data())),
                           object(), stop, None, provider_factory=broken_provider)
    assert raised.value is failure
    assert not discord.queued and not discord.sent


def test_discord_transport_failure_keeps_the_original_failure(discord, monkeypatch, caplog):
    failure = RuntimeError("AI 供應商初始化失敗")

    def broken_provider(*_):
        raise failure

    def offline(*_):
        raise OSError("離線")

    monkeypatch.setattr(discord_notify, "_urllib_post", offline)
    with pytest.raises(RuntimeError) as raised:
        build_chat_session(_settings(), None, script_from_dict(script_data(config_data())),
                           object(), threading.Event(), None, provider_factory=broken_provider)
    assert raised.value is failure
    assert len(discord.queued) == 1
    _deliver(discord)
    assert "Discord 通知傳送失敗" in caplog.text


@pytest.mark.parametrize("failure", ["recipient", "text"])
def test_failed_reply_closes_chat_and_continues_without_discord(runtime, discord, failure):
    # 使用者要求：沒成功回覆不應該停止腳本。
    scene = runtime.scene
    if failure == "recipient":
        scene.open_recipient = False
    else:
        original = runtime.backend.type_text

        def fail_text(text):
            if text == "有收到":
                raise OSError("文字輸入失敗")
            original(text)

        runtime.backend.type_text = fail_text
    result = _play(runtime)
    assert result.ok and result.actions_run == 1
    assert not scene.sent
    assert not scene.input_focused and scene.input_stage is None
    assert any("回覆失敗" in r.get("message", "") for r in runtime.records)
    assert not discord.queued and not discord.sent
