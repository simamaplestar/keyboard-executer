"""自動試跑循環（spec §5）：回起點 → 試跑 → AI 比對 → 修正並套用 → 下一輪。

純邏輯：所有副作用經由 DemoPorts。整個函式在背景執行緒以阻塞方式執行。
腳本庫只保留實際試跑過的版本；最後一輪的修正只存成「未試跑」版本。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

from keyboard_executor.core.ai.provider import AiAborted, AiProviderError
from keyboard_executor.core.ai_demo.outcome import RunOutcome
from keyboard_executor.core.ai_demo.prompt import DemoRecording
from keyboard_executor.core.ai_demo.proposal import DemoProposal, DemoProposalError

_MAX_SAME_INTERRUPTS = 2


class DemoPorts(Protocol):
    def ask_ai(self, kind: str, payload: dict) -> DemoProposal: ...
    def save_version(self, proposal: DemoProposal, version: int) -> None: ...
    def apply_version(self, version: int) -> str: ...
    def run_main(self, max_seconds: float) -> RunOutcome: ...
    def run_return(self) -> RunOutcome: ...
    def read_dot(self) -> tuple[float, float] | None: ...
    def wait_user_reset(self, message: str) -> bool: ...
    def report(self, event: dict) -> None: ...
    def stopped(self) -> bool: ...


@dataclass
class RoundRecord:
    round: int
    version: int
    ended: str
    verdict: str | None
    changes: str


@dataclass
class DemoLoopResult:
    status: str   # success | max_rounds | stopped | interrupted | user_ended | ai_failed
    message: str
    rounds: list[RoundRecord] = field(default_factory=list)
    library_version: int | None = None
    untested_version: int | None = None
    goal: str = ""


class _End(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class _Interrupted(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Loop:
    def __init__(self, rec: DemoRecording, ports: DemoPorts, max_rounds: int,
                 start_radius: float, demo_time_factor: float):
        self.rec = rec
        self.ports = ports
        self.max_rounds = max(1, max_rounds)
        self.radius = start_radius
        self.max_seconds = rec.duration_ms / 1000 * demo_time_factor
        self.version = 0
        self.library: int | None = None
        self.untested: int | None = None
        self.rounds: list[RoundRecord] = []
        self.goal = ""

    def check_stop(self) -> None:
        if self.ports.stopped():
            raise _End("stopped", "已停止")

    def report(self, stage: str, round_no: int = 0, **extra) -> None:
        self.ports.report({"stage": stage, "round": round_no, **extra})

    def ask(self, kind: str, payload: dict) -> DemoProposal:
        self.check_stop()
        try:
            try:
                return self.ports.ask_ai(kind, payload)
            except DemoProposalError as exc:
                self.check_stop()
                self.report("ai_retry", payload.get("round", 0), error=str(exc))
                return self.ports.ask_ai(kind, {**payload, "error": str(exc)})
        except DemoProposalError as exc:
            self.check_stop()
            raise _End("ai_failed", f"AI 提案不合法：{exc}") from exc
        except AiAborted as exc:
            raise _End("stopped", "已停止") from exc
        except AiProviderError as exc:
            self.check_stop()
            raise _End("ai_failed", str(exc)) from exc

    def new_version(self, proposal: DemoProposal, *, apply: bool) -> None:
        self.version += 1
        self.ports.save_version(proposal, self.version)
        if apply:
            self.ports.apply_version(self.version)

    def at_start(self) -> tuple[bool, tuple[float, float] | None]:
        dot = self.ports.read_dot()
        if dot is None:
            return False, None
        sx, sy = self.rec.start_dot
        return math.hypot(dot[0] - sx, dot[1] - sy) <= self.radius, dot

    def run_return(self, round_no: int) -> RunOutcome:
        self.check_stop()
        self.report("return", round_no)
        outcome = self.ports.run_return()
        if outcome.ended == "stopped":
            raise _End("stopped", "已停止")
        if outcome.ended == "interrupted":
            raise _Interrupted(outcome.reason)
        return outcome

    def ensure_start(self, round_no: int) -> None:
        outcome = self.run_return(round_no)
        ok, dot = self.at_start()
        if ok:
            return
        self.report("return_fix", round_no)
        proposal = self.ask("return_fix", {"round": round_no, "version": self.version,
                                           "end_dot": dot, "dot_trace": outcome.dot_trace})
        self.new_version(proposal, apply=True)
        self.run_return(round_no)
        if self.at_start()[0]:
            return
        self.check_stop()
        self.report("wait_reset", round_no)
        if not self.ports.wait_user_reset("角色沒有回到示範起點，請手動帶回起點後按「繼續」"):
            self.check_stop()
            raise _End("user_ended", "使用者結束了試跑")
        self.check_stop()

    def run(self) -> DemoLoopResult:
        self.check_stop()
        self.report("ai_initial")
        first = self.ask("initial", {})
        self.goal = first.goal
        self.new_version(first, apply=True)
        round_no = 1
        last_interrupt, interrupts = "", 0
        while True:
            try:
                self.ensure_start(round_no)
                self.check_stop()
                self.report("running", round_no)
                outcome = self.ports.run_main(self.max_seconds)
                if outcome.ended == "stopped":
                    raise _End("stopped", "已停止")
                if outcome.ended == "interrupted":
                    raise _Interrupted(outcome.reason)
            except _Interrupted as exc:      # 規則等外部中斷：這一輪不算，重跑
                interrupts = interrupts + 1 if exc.reason == last_interrupt else 1
                last_interrupt = exc.reason
                if interrupts >= _MAX_SAME_INTERRUPTS:
                    raise _End("interrupted", f"試跑連續被中斷：{exc.reason}") from exc
                continue
            last_interrupt, interrupts = "", 0
            self.library = self.version
            self.report("ai_fix", round_no)
            fix = self.ask("fix", {"round": round_no, "version": self.version, "run": outcome})
            self.rounds.append(RoundRecord(round_no, self.version, outcome.ended,
                                           fix.verdict, fix.changes))
            if fix.verdict == "success":
                return self.result("success", f"第 {round_no} 輪試跑與示範一致")
            last = round_no >= self.max_rounds
            self.new_version(fix, apply=not last)
            if last:
                self.untested = self.version
                return self.result("max_rounds",
                                   f"已試跑 {round_no} 輪仍需修正；腳本庫保留第 {self.library} 版")
            round_no += 1

    def result(self, status: str, message: str) -> DemoLoopResult:
        return DemoLoopResult(status, message, self.rounds, self.library, self.untested, self.goal)


def run_demo_loop(rec: DemoRecording, ports: DemoPorts, *, max_rounds: int,
                  start_radius: float = 8.0, demo_time_factor: float = 2.0) -> DemoLoopResult:
    loop = _Loop(rec, ports, max_rounds, start_radius, demo_time_factor)
    try:
        result = loop.run()
    except _End as end:
        if loop.library is not None and loop.version > loop.library:
            # 中途結束時腳本庫可能是還沒試跑的修正版：退回最後試跑過的版本
            try:
                ports.apply_version(loop.library)
                loop.untested = loop.version
            except Exception as exc:     # 存檔失敗不可蓋掉原本的結束原因
                end = _End(end.status, f"{end.message}（退回第 {loop.library} 版失敗：{exc}）")
        result = loop.result(end.status, end.message)
    ports.report({"stage": "done", "round": len(loop.rounds), "status": result.status})
    return result
