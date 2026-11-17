from keyboard_executor.core.ai.provider import AiProviderError
from keyboard_executor.core.ai_demo.loop import run_demo_loop
from keyboard_executor.core.ai_demo.outcome import RunOutcome
from keyboard_executor.core.ai_demo.proposal import DemoProposal, DemoProposalError
from keyboard_executor.core.ai_demo.prompt import DemoRecording
from keyboard_executor.core.models import script_from_dict


def script(name):
    return script_from_dict({"name": name, "target_window": {"title_pattern": "x"},
                             "actions": [{"type": "key_press", "key": "a"}]})


def proposal(verdict=None, changes="", main=True, ret=True):
    return DemoProposal("打怪", verdict, changes, script("練功") if main else None,
                        script("回起點") if ret else None, ())


def rec():
    return DemoRecording(frames=[], holds=[], mouse=[], event_times_ms=[], duration_ms=30_000,
                         start_dot=(100.0, 40.0), minimap_region=(0, 0, 200, 100),
                         window_title="w", goal_text="")


class FakePorts:
    def __init__(self, answers, runs=None, dots=None, resets=None):
        self.answers = list(answers)        # DemoProposal 或 Exception
        self.runs = list(runs or [])        # run_main 的 RunOutcome
        self.dots = list(dots or [])
        self.resets = list(resets or [])
        self.calls = []
        self.stop_after = None
        self.reports = []

    def _next(self, seq, default):
        return seq.pop(0) if seq else default

    def ask_ai(self, kind, payload):
        self.calls.append(("ask", kind, "error" in payload))
        answer = self._next(self.answers, proposal("success"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def save_version(self, p, version):
        self.calls.append(("save", version))

    def apply_version(self, version):
        self.calls.append(("apply", version))
        return "練功"

    def run_main(self, max_seconds):
        self.calls.append(("run", max_seconds))
        outcome = self._next(self.runs, RunOutcome("time_up"))
        if outcome.ended == "stopped":
            self.stop_after = True
        return outcome

    def run_return(self):
        self.calls.append(("return",))
        return RunOutcome("finished")

    def read_dot(self):
        return self._next(self.dots, (101.0, 41.0))

    def wait_user_reset(self, message):
        self.calls.append(("reset", message))
        return self._next(self.resets, True)

    def report(self, event):
        self.reports.append(event)

    def stopped(self):
        return bool(self.stop_after)


def kinds(ports, name):
    return [c for c in ports.calls if c[0] == name]


def test_success_on_first_fix():
    ports = FakePorts([proposal(), proposal("success")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "success"
    assert result.library_version == 1
    assert result.untested_version is None
    assert kinds(ports, "run") == [("run", 60.0)]
    assert [r.verdict for r in result.rounds] == ["success"]


def test_runs_max_rounds_and_keeps_last_tested():
    fixes = [proposal("needs_fix", f"改{i}", ret=False) for i in range(3)]
    ports = FakePorts([proposal(), *fixes])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "max_rounds"
    assert result.library_version == 3
    assert result.untested_version == 4
    assert kinds(ports, "apply") == [("apply", 1), ("apply", 2), ("apply", 3)]
    assert kinds(ports, "save") == [("save", 1), ("save", 2), ("save", 3), ("save", 4)]
    assert [r.changes for r in result.rounds] == ["改0", "改1", "改2"]


def test_stop_during_run_ends_without_ai_call():
    ports = FakePorts([proposal()], runs=[RunOutcome("stopped")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "stopped"
    assert kinds(ports, "ask") == [("ask", "initial", False)]


def test_stopped_before_start_calls_nothing_else():
    ports = FakePorts([proposal()])
    ports.stop_after = True
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "stopped"
    assert ports.calls == []


def test_interrupted_twice_same_reason_ends():
    runs = [RunOutcome("interrupted", "規則「測謊」觸發")] * 2
    ports = FakePorts([proposal()], runs=runs)
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "interrupted"
    assert "測謊" in result.message
    assert len(kinds(ports, "run")) == 2


def test_interrupted_once_reruns_without_counting():
    runs = [RunOutcome("interrupted", "規則觸發"), RunOutcome("time_up")]
    ports = FakePorts([proposal(), proposal("success")], runs=runs)
    result = run_demo_loop(rec(), ports, max_rounds=1)
    assert result.status == "success"
    assert len(kinds(ports, "run")) == 2
    assert len(result.rounds) == 1


def test_invalid_proposal_retried_once():
    ports = FakePorts([DemoProposalError("壞了"), proposal(), proposal("success")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "success"
    assert kinds(ports, "ask")[:2] == [("ask", "initial", False), ("ask", "initial", True)]


def test_invalid_proposal_twice_fails():
    ports = FakePorts([DemoProposalError("壞了"), DemoProposalError("還是壞")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "ai_failed"
    assert "還是壞" in result.message
    assert kinds(ports, "run") == []


def test_provider_error_not_retried():
    ports = FakePorts([AiProviderError("連線失敗")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "ai_failed"
    assert len(kinds(ports, "ask")) == 1


def test_return_fix_then_user_reset():
    # 回起點兩次都沒到（AI 修過一次），使用者手動帶回後繼續
    ports = FakePorts([proposal(), proposal("needs_fix", main=False), proposal("success")],
                      dots=[(150.0, 60.0), (150.0, 60.0)], resets=[True])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "success"
    assert ("ask", "return_fix", False) in ports.calls
    assert len(kinds(ports, "return")) == 2
    assert len(kinds(ports, "reset")) == 1
    assert kinds(ports, "apply") == [("apply", 1), ("apply", 2)]


def test_user_ends_on_reset_prompt():
    ports = FakePorts([proposal(), proposal("needs_fix", main=False)],
                      dots=[None, None], resets=[False])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "user_ended"
    assert kinds(ports, "run") == []


def test_dot_within_radius_counts_as_start():
    ports = FakePorts([proposal(), proposal("success")], dots=[(107.0, 40.0)])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "success"
    assert ("ask", "return_fix", False) not in ports.calls


class StopOnSecondReturn(FakePorts):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.returns = 0

    def run_return(self):
        self.returns += 1
        if self.returns == 2:
            self.stop_after = True
            self.calls.append(("return",))
            return RunOutcome("stopped")
        return super().run_return()


def test_stop_before_untested_fix_runs_restores_last_tested():
    """第 2 版已套用但還沒試跑就停止 → 腳本庫退回第 1 版，第 2 版標為未試跑。"""
    ports = StopOnSecondReturn([proposal(), proposal("needs_fix", "改")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "stopped"
    assert result.library_version == 1
    assert result.untested_version == 2
    assert kinds(ports, "apply") == [("apply", 1), ("apply", 2), ("apply", 1)]


def test_ai_failure_after_fix_restores_last_tested():
    ports = FakePorts([proposal(), proposal("needs_fix", "改"),
                       AiProviderError("斷線")],
                      runs=[RunOutcome("time_up"), RunOutcome("time_up")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "ai_failed"
    assert result.library_version == 2
    assert result.untested_version is None
    assert kinds(ports, "apply")[-1] == ("apply", 2)


def test_no_restore_when_nothing_tested_yet():
    class StopFirstReturn(FakePorts):
        def run_return(self):
            self.stop_after = True
            return RunOutcome("stopped")
    ports = StopFirstReturn([proposal()])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "stopped"
    assert result.library_version is None
    assert kinds(ports, "apply") == [("apply", 1)]


class InterruptReturn(FakePorts):
    def __init__(self, *a, interrupts=1, **k):
        super().__init__(*a, **k)
        self.left = interrupts

    def run_return(self):
        if self.left:
            self.left -= 1
            self.calls.append(("return",))
            return RunOutcome("interrupted", "規則「測謊」觸發")
        return super().run_return()


def test_interrupted_return_is_not_return_failure():
    ports = InterruptReturn([proposal(), proposal("success")])
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "success"
    assert ("ask", "return_fix", False) not in ports.calls
    assert len(kinds(ports, "return")) == 2


def test_interrupted_return_twice_ends():
    ports = InterruptReturn([proposal()], interrupts=2)
    result = run_demo_loop(rec(), ports, max_rounds=3)
    assert result.status == "interrupted"
    assert kinds(ports, "run") == []
