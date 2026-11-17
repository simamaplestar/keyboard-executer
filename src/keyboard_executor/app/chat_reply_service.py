"""用設定頁的 AI 認證建立腳本聊天服務（不依賴 Qt）。"""
from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
import threading

from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.provider import AiAborted
from keyboard_executor.core.discord_notify import make_notifier
from keyboard_executor.core.models import ScriptValidationError

logger = logging.getLogger(__name__)


def build_chat_session(settings, auth_service, script, platform, stop_event, on_progress, *,
                       provider_factory=make_provider, owns_ocr=True, history_root=None):
    config = script.settings.chat_reply
    if config is None or not config.active:
        return None
    # One callback owns the entire run, including initialization and close.
    # make_notifier dispatches HTTP in the background; playback never waits.
    notify = make_notifier(lambda _: None, settings.discord_webhook_url)
    notified = False
    notification_lock = threading.Lock()

    def on_failure(exc):
        nonlocal notified
        if isinstance(exc, AiAborted) or stop_event.is_set():
            return
        with notification_lock:
            if notified:
                return
            notified = True
        try:
            notify(f"腳本「{script.name}」因 AI 自動回覆失敗而停止：{exc}")
        except Exception:
            # Even a dispatcher failure must preserve the original exception.
            logger.warning("AI 自動回覆停止通知無法排入 Discord 背景傳送")

    try:
        return _build_active_chat_session(
            settings, auth_service, script, platform, stop_event, on_progress,
            provider_factory=provider_factory, owns_ocr=owns_ocr, on_failure=on_failure,
            history_root=history_root)
    except Exception as exc:
        on_failure(exc)
        raise


def _build_active_chat_session(settings, auth_service, script, platform, stop_event, on_progress, *,
                               provider_factory, owns_ocr, on_failure, history_root):
    if not settings.ai_provider:
        raise ScriptValidationError("請先在設定頁設定 AI 供應商與模型，再啟用自動回覆")
    if settings.ai_auth_mode == "subscription":
        profile = auth_service.resolve_profile(settings) if auth_service is not None else None
        if profile is None:
            raise ScriptValidationError("AI 訂閱登入已失效，請到設定重新連結")
        options = {"reasoning_effort": "low"} if settings.ai_provider == "openai" else {}
        provider = provider_factory(settings.ai_provider, "", settings.ai_model,
                                    auth_mode="subscription", auth_profile=profile, **options)
    else:
        if not settings.ai_api_key or not settings.ai_model:
            raise ScriptValidationError("請先填入 AI API Key 與模型名稱")
        provider = provider_factory(settings.ai_provider, settings.ai_api_key, settings.ai_model)
    if provider is None:
        raise ScriptValidationError("AI 供應商尚未設定")
    from keyboard_executor.core.chat_reply_monitor import BackgroundChatReplySession
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
    from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine

    # 相同 v6 模型；聊天／圖片服務共用可取消子程序，不阻塞播放器。
    engine = getattr(platform, "ocr_engine", None)
    if isinstance(engine, RapidOcrEngine):
        platform = replace(platform, ocr_engine=ProcessOcrEngine(None, stop_event))

    history_options = {}
    if history_root is not None:
        from keyboard_executor.storage.chat_history import ChatHistoryStore
        history_options["history_store"] = ChatHistoryStore(Path(history_root) / ".chat-history")

    return BackgroundChatReplySession(platform, script.settings.chat_reply, provider,
                                      stop_event, on_progress, owns_ocr=owns_ocr,
                                      on_failure=on_failure, **history_options)
