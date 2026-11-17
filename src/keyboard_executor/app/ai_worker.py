"""AI 聊天 job：把 ChatProvider.stream_chat 包成 Worker 的 job 契約。

delta → progress({"kind": "delta", "text": ...})；使用者中止（AiAborted）→
回傳 None（走 finished，不是 failed）；AiProviderError 原樣拋出，由 Worker
轉成 failed（繁中訊息）。"""
from __future__ import annotations

import threading
from collections.abc import Callable

from keyboard_executor.core.ai.provider import AiAborted, ChatProvider, ChatResult


def build_chat_job(provider: ChatProvider, messages: list[dict], *,
                   system: str, tools: list[dict],
                   abort_event: threading.Event) -> Callable:
    def job(progress) -> ChatResult | None:
        try:
            return provider.stream_chat(
                messages, system=system, tools=tools,
                on_delta=lambda text: progress({"kind": "delta", "text": text}),
                should_abort=abort_event.is_set)
        except AiAborted:
            return None
    return job
