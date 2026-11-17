from dataclasses import replace
import threading
from types import SimpleNamespace
import pytest
from tests.fakes import FakeInputBackend, FakeWindowManager
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from tests.core.test_sequence_input_config import config_data


class ReadyWatcher:
    def __init__(self):
        self.clicked = 0
        self.phase = "READY"
        self.failure = None
    def snapshot(self):
        return SimpleNamespace(round_id=1, phase=self.phase, answer="HDP", deadline=30.,
                               prepare_deadline=18., confirm_deadline=20., failure=self.failure)
    def wait_ready(self): return self.snapshot()
    def validate_prompt(self, round_id): return True
    def begin_submit(self, round_id):
        if self.phase != "READY": return None
        self.phase = "SUBMITTING"
        return "HDP"
    def mark_clicked(self, round_id):
        self.clicked += 1
        self.phase = "VERIFYING"
    def wait_complete(self, round_id):
        self.phase = "SUCCEEDED"
        return True
    def fail(self, reason):
        self.failure, self.phase = reason, "FAILED"


def build():
    from keyboard_executor.core.sequence_submitter import SequenceSubmitter
    stop = threading.Event()
    backend = FakeInputBackend()
    win = WindowInfo(1, "記事本", "app", 0, 0, 500, 500, True)
    platform = SimpleNamespace(input_backend=backend, window_manager=FakeWindowManager([win]))
    watcher, now = ReadyWatcher(), [1.]
    submitter = SequenceSubmitter(platform, sequence_config_from_dict(config_data()), watcher, stop, clock=lambda: now[0])
    return submitter, watcher, platform, win, stop, now


@pytest.mark.parametrize("at", ["mouse_click", "key_down", "type_text"])
def test_stop_between_steps_never_confirms_and_releases_keys(at):
    submitter, watcher, platform, win, stop, _ = build()
    backend = platform.input_backend
    original = getattr(backend, at)
    def interrupt(*args):
        original(*args)
        stop.set()
    setattr(backend, at, interrupt)
    assert not submitter.run(win)
    assert watcher.clicked == 0
    assert len([c for c in backend.calls if c[0] == "mouse_click"]) == 1
    if at == "key_down": assert ("key_up", "ctrl") in backend.calls


def test_success_order_and_second_call_cannot_repeat():
    submitter, watcher, platform, win, _, _ = build()
    assert submitter.run(win)
    backend = platform.input_backend
    assert ''.join(c[1] for c in backend.calls if c[0] == "type_text") == "HDP"
    assert [c[1:3] for c in backend.calls if c[0] == "mouse_click"] == [(80,220), (330,220)]
    calls = list(backend.calls)
    assert not submitter.run(win)
    assert backend.calls == calls
    assert watcher.clicked == 1


@pytest.mark.parametrize("case", ["deadline", "moved", "inactive", "click_error"])
def test_runtime_changes_prevent_confirmation(case):
    submitter, watcher, platform, win, stop, now = build()
    original = platform.input_backend.type_text
    def type_text(text):
        original(text)
        if case == "deadline": now[0] = 30
        elif case in {"moved", "inactive"}:
            platform.window_manager.windows[:] = [replace(win, x=10, is_active=case != "inactive")]
        else: raise RuntimeError("input error")
    platform.input_backend.type_text = type_text
    assert not submitter.run(win)
    assert stop.is_set()
    assert watcher.clicked == 0


def test_failed_final_prompt_check_and_expired_budget_never_type():
    submitter, watcher, platform, win, _, now = build()
    now[0] = 18
    assert not submitter.run(win)
    assert platform.input_backend.calls == []
