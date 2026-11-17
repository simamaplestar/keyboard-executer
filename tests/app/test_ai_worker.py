"""build_chat_job：delta → progress、結果/中止/錯誤的 Worker 契約。"""
import threading

import pytest

from keyboard_executor.app.ai_worker import build_chat_job
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatProvider,
    ChatResult,
)


class FakeProvider(ChatProvider):
    def __init__(self, result=None, deltas=(), error=None):
        self.result = result or ChatResult(text="done")
        self.deltas = deltas
        self.error = error
        self.seen = None

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.seen = {"messages": messages, "system": system, "tools": tools}
        for d in self.deltas:
            on_delta(d)
        if should_abort():
            raise AiAborted()
        if self.error:
            raise self.error
        return self.result


def _run(job):
    """用 Worker 同步跑 job（run() 直接呼叫＝當前執行緒執行）。"""
    events = {"progress": [], "finished": [], "failed": []}
    w = Worker(job)
    w.progress.connect(events["progress"].append)
    w.finished.connect(events["finished"].append)
    w.failed.connect(events["failed"].append)
    w.run()
    return events


def test_deltas_flow_through_progress(qapp):
    p = FakeProvider(result=ChatResult(text="你好"), deltas=["你", "好"])
    ev = _run(build_chat_job(p, [{"role": "user", "content": "hi"}],
                             system="s", tools=[], abort_event=threading.Event()))
    assert ev["progress"] == [{"kind": "delta", "text": "你"},
                              {"kind": "delta", "text": "好"}]
    assert ev["finished"][0].text == "你好"
    assert ev["failed"] == []


def test_abort_returns_none_not_failed(qapp):
    p = FakeProvider()
    abort = threading.Event()
    abort.set()
    ev = _run(build_chat_job(p, [], system="s", tools=[], abort_event=abort))
    assert ev["finished"] == [None] and ev["failed"] == []


def test_provider_error_goes_to_failed(qapp):
    p = FakeProvider(error=AiProviderError("連線失敗：測試"))
    ev = _run(build_chat_job(p, [], system="s", tools=[],
                             abort_event=threading.Event()))
    assert ev["finished"] == []
    assert "連線失敗：測試" in ev["failed"][0]


def test_job_passes_messages_system_tools(qapp):
    p = FakeProvider()
    msgs = [{"role": "user", "content": "做腳本"}]
    tools = [{"name": "t"}]
    _run(build_chat_job(p, msgs, system="SYS", tools=tools,
                        abort_event=threading.Event()))
    assert p.seen == {"messages": msgs, "system": "SYS", "tools": tools}
