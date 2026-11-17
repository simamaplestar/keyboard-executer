"""Assemble the GUI visual runtime; one owner for one shared OCR process."""
from dataclasses import replace
import queue
import threading
import time

import cv2
import numpy as np
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.sequence_recognizer import SequenceRecognizer, SequenceSample
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.sequence_watcher import SequenceWatcher
from keyboard_executor.core.sequence_submitter import SequenceSubmitter
from keyboard_executor.core.visual_intervention import VisualIntervention


def preflight(recognizer, stop_event, *, timeout=10.0, clock=time.monotonic):
    """A small synthetic image checks transport/schema without capturing the desktop."""
    deadline = clock() + timeout
    cancelled = threading.Event()
    result = queue.Queue(maxsize=1)
    image = np.full((160, 160, 3), 255, np.uint8)
    cv2.putText(image, "A", (35, 100), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 5)
    cv2.putText(image, "1", (125, 145), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    def aborted():
        return stop_event.is_set() or cancelled.is_set() or clock() >= deadline
    def request():
        try:
            rows = recognizer.recognize([SequenceSample(0, image)], should_abort=aborted)
            result.put((True, rows))
        except Exception as exc:
            result.put((False, exc))
    if not aborted():
        threading.Thread(target=request, name="sequence-preflight", daemon=True).start()
    try:
        while not aborted():
            try:
                ok, rows = result.get(timeout=.05)
            except queue.Empty:
                continue
            if aborted():
                break
            if (ok and len(rows) == 1 and rows[0].sample_id == 0
                    and rows[0].index == 1 and rows[0].char == "A"):
                return
            raise ScriptValidationError("圖片模型檢查失敗，請選擇支援圖片辨識的模型")
        raise ScriptValidationError("圖片模型檢查已取消或逾時（10 秒），未執行脚本")
    finally:
        cancelled.set()


def build_sequence_runtime(settings, auth_service, script, platform, stop_event, on_progress, *,
                           provider_factory=make_provider, history_root=None):
    config = script.settings.sequence_input
    if config is None or not config.enabled:
        return None
    if not settings.ai_provider:
        raise ScriptValidationError("圖片順序輸入需要設定 AI 供應商與圖片模型")
    if settings.ai_auth_mode == "subscription":
        profile = auth_service.resolve_profile(settings) if auth_service else None
        if profile is None:
            raise ScriptValidationError("AI 訂閱登入已失效，請重新連結")
        provider = provider_factory(settings.ai_provider, "", settings.ai_model,
                                    auth_mode="subscription", auth_profile=profile)
    else:
        if not settings.ai_model or not settings.ai_api_key:
            raise ScriptValidationError("請先填入 AI API Key 與支援圖片的模型")
        provider = provider_factory(settings.ai_provider, settings.ai_api_key, settings.ai_model)
    if provider is None or platform.screen_capture is None or platform.ocr_engine is None:
        raise ScriptValidationError("圖片順序輸入需要 AI、螢幕擷取及 OCR 能力")
    if config.mode == "panel":
        from keyboard_executor.core.ai.sequence_char_recognizer import CharRecognizer
        recognizer = CharRecognizer(provider)
    else:
        recognizer = SequenceRecognizer(provider)
        if on_progress:
            on_progress({"kind": "notify", "message": "圖片順序輸入：檢查模型圖片能力（最多10秒，API可能產生用量）"})
        preflight(recognizer, stop_event)

    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
    from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine
    from keyboard_executor.app.chat_reply_service import build_chat_session
    engine = platform.ocr_engine
    if isinstance(engine, RapidOcrEngine):
        engine = ProcessOcrEngine(None, stop_event)
    shared_platform = replace(platform, ocr_engine=engine)
    watcher = chat = None
    try:
        if config.mode == "panel":
            from keyboard_executor.core.sequence_panel_watcher import PanelWatcher
            from keyboard_executor.core.sequence_discord import (
                make_sequence_notifier, make_sequence_outcome_notifier)
            watcher = PanelWatcher(shared_platform, config, recognizer, stop_event, on_progress,
                on_detected=make_sequence_notifier(settings.discord_webhook_url, stop_event, on_progress),
                on_outcome=make_sequence_outcome_notifier(settings.discord_webhook_url, on_progress),
                discord_configured=bool((settings.discord_webhook_url or '').strip()))
            submitter = SequenceSubmitter(shared_platform, config, watcher, stop_event,
                                          target_provider=watcher.submission_target)
        else:
            watcher = SequenceWatcher(shared_platform, config, recognizer, stop_event, on_progress)
            submitter = SequenceSubmitter(shared_platform, config, watcher, stop_event)
        chat_options = {"history_root": history_root} if history_root is not None else {}
        chat = build_chat_session(settings, auth_service, script, shared_platform, stop_event, on_progress,
                                  provider_factory=provider_factory, owns_ocr=False, **chat_options)
        return VisualIntervention(watcher, submitter, chat, owned_ocr=engine)
    except Exception:
        if watcher:
            watcher.close()
        if chat:
            chat.close()
        close = getattr(engine, "close", None)
        if close:
            close()
        raise
