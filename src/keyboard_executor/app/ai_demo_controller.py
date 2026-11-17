"""AI 示範錄製的控制器：把 run_demo_loop 的 ports 接到 AI 供應商、回放與存檔。

整個循環在一個 Worker 背景執行緒內阻塞執行；Qt signal 跨執行緒自動排入 GUI。
使用**獨立的** RunController：共用主視窗那一個時 build_job 會覆寫 stop_event，
可能停錯對象（spec §5）。
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from keyboard_executor.app.ai_demo_capture import FrameSampler, read_dot
from keyboard_executor.app.naming import numbered_name
from keyboard_executor.app.run_controller import RunController
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.manual import build_demo_system_prompt
from keyboard_executor.core.ai.provider import AiProviderError
from keyboard_executor.core.ai.tools import TOOL_DEMO, demo_tools_anthropic, demo_tools_openai
from keyboard_executor.core.ai_demo.frames import MAX_SENT_EDGE, Frame, read_image
from keyboard_executor.core.ai_demo.loop import DemoLoopResult, run_demo_loop
from keyboard_executor.core.ai_demo.outcome import RunOutcome
from keyboard_executor.core.ai_demo.prompt import (
    DemoRecording, fix_message, initial_message, return_fix_message,
)
from keyboard_executor.core.ai_demo.proposal import (
    DemoProposal, DemoProposalError, parse_demo_proposal,
)
from keyboard_executor.core.models import ScriptValidationError, script_from_dict, script_to_dict

logger = logging.getLogger(__name__)

RETURN_MAX_SECONDS = 60.0
EXTERNAL_WAIT_MAX_SEC = 300.0     # 規則動作最久等這麼久（避免完成事件遺失時卡死）
_MANUAL_STOP = "已手動停止"


def _rename_templates(node, mapping: dict[str, str]):
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "template" and isinstance(value, str) and value in mapping:
                out[key] = mapping[value]
            else:
                out[key] = _rename_templates(value, mapping)
        return out
    if isinstance(node, list):
        return [_rename_templates(item, mapping) for item in node]
    return node


class AiDemoController(QObject):
    progress = Signal(dict)
    finished = Signal(object)          # DemoLoopResult
    reset_needed = Signal(str)
    active_changed = Signal(bool)
    scripts_changed = Signal()

    def __init__(self, *, get_settings, auth_service, script_storage, templates, sessions,
                 get_platform, provider_factory=make_provider,
                 run_controller_factory=RunController, worker_factory=Worker,
                 sampler_factory=FrameSampler, capture_factory=None, dot_reader=read_dot,
                 notifier=None, parent=None):
        super().__init__(parent)
        self._get_settings = get_settings
        self._auth_service = auth_service
        self._storage = script_storage
        self._templates = templates
        self._sessions = sessions
        self._get_platform = get_platform
        self._provider_factory = provider_factory
        self._run_controller_factory = run_controller_factory
        self._worker_factory = worker_factory
        self._sampler_factory = sampler_factory
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._capture_factory = capture_factory
        self._dot_reader = dot_reader
        if notifier is None:
            from keyboard_executor.core.discord_notify import post_discord
            notifier = post_discord
        self._notifier = notifier
        self.max_sent_edge = MAX_SENT_EDGE
        self.external_settle_sec = 1.0     # 規則動作結束後再等一下，讓畫面穩定
        self._external_busy = threading.Event()
        self._worker = None
        self._stop = threading.Event()
        self._reset_event = threading.Event()
        self._reset_answer = False
        self._run_lock = threading.Lock()
        self._rc = None
        self._running = False
        self._timer_fired = False
        self._interrupt_reason = ""
        # 單次循環的狀態
        self._rec: DemoRecording | None = None
        self._win = None
        self._session: Path | None = None
        self._frames: dict[str, Frame] = {}
        self._scales: dict[str, float] = {}
        self._main_name = ""
        self._return_name = ""
        self._run_count = 0
        self._capture = None
        self._wm = None
        self._report = None

    # ---------- 對外 ----------

    @property
    def active(self) -> bool:
        return self._worker is not None

    @property
    def session(self) -> Path | None:
        return self._session

    def start_loop(self, rec: DemoRecording, win, session: Path | None = None) -> Path:
        if self._worker is not None:
            raise RuntimeError("示範試跑已在進行中")
        self._stop.clear()
        self._reset_event.clear()
        self._rec, self._win = rec, win
        self._session = session if session is not None else self._sessions.create()
        self._frames = {f.id: f for f in rec.frames}
        self._scales = {}
        self._main_name = self._return_name = ""
        self._run_count = 0
        settings = self._get_settings()
        self._rc = self._run_controller_factory(
            self._storage, self._templates.load_template, get_platform=self._get_platform,
            stop_key=settings.stop_key, corner_failsafe=settings.corner_failsafe)
        max_rounds = settings.ai_demo_max_rounds
        ports = _Ports(self)

        def job(progress):
            ports.progress = progress
            ports.bind()
            try:
                return run_demo_loop(rec, ports, max_rounds=max_rounds)
            finally:
                ports.close()

        worker = self._worker_factory(job)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self.active_changed.emit(True)
        worker.start()
        return self._session

    def stop(self) -> None:
        self._stop.set()
        self._reset_answer = False
        self._reset_event.set()
        self._stop_current_run()

    def interrupt(self, reason: str) -> None:
        """規則觸發等外部事件：中斷目前這一輪試跑（不算輪數）。"""
        with self._run_lock:
            if not self._running:
                return
            self._interrupt_reason = reason
        self._stop_current_run()

    def set_external_busy(self, busy: bool) -> None:
        """監看規則觸發的腳本正在跑（主視窗依 fire / fire_done 事件呼叫）。"""
        if busy:
            self._external_busy.set()
        else:
            self._external_busy.clear()

    def _wait_external_quiet(self) -> bool:
        """等規則觸發的動作做完再操作角色；停止時回傳 False。"""
        if not self._external_busy.is_set():
            return not self._stop.is_set()
        self._emit_report({"stage": "wait_rule", "round": 0})
        deadline = time.monotonic() + EXTERNAL_WAIT_MAX_SEC
        while self._external_busy.is_set() and time.monotonic() < deadline:
            if self._stop.wait(0.2):
                return False
        if self._stop.wait(self.external_settle_sec):
            return False
        return True

    def _emit_report(self, event: dict) -> None:
        report = self._report
        if report is not None:
            report(event)

    def resume_after_reset(self, proceed: bool) -> None:
        self._reset_answer = proceed
        self._reset_event.set()

    def apply_version(self, session: Path, version: int) -> str:
        data = self._sessions.load_version(session, version)
        main = script_from_dict(data["main"])
        self._storage.save(main)
        if data.get("return"):
            self._storage.save(script_from_dict(data["return"]))
        self.scripts_changed.emit()
        return main.name

    def shutdown(self) -> None:
        self.stop()
        if self._worker is not None:
            self._worker.wait()

    # ---------- Worker 回呼（GUI 執行緒） ----------

    def _on_progress(self, event: dict) -> None:
        if event.get("stage") == "wait_reset" and "message" in event:
            self.reset_needed.emit(event["message"])
        self.progress.emit(event)

    def _finish(self, result: DemoLoopResult) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and hasattr(worker, "wait"):
            worker.wait()
        self.active_changed.emit(False)
        self.finished.emit(result)

    def _on_finished(self, result) -> None:
        if result is None:
            result = DemoLoopResult("stopped", "已停止")
        self._finish(result)

    def _on_failed(self, message: str) -> None:
        self._finish(DemoLoopResult("ai_failed", message))

    # ---------- 給 ports 用（背景執行緒） ----------

    def _stop_current_run(self) -> None:
        rc = self._rc
        if rc is not None:
            rc.stop()

    def _on_time_up(self) -> None:
        self._timer_fired = True
        self._stop_current_run()

    def _make_provider(self):
        s = self._get_settings()
        if s.ai_auth_mode == "subscription":
            profile = (self._auth_service.resolve_profile(s)
                       if self._auth_service is not None else None)
            if profile is None:
                raise AiProviderError("訂閱登入已失效，請到設定重新連結")
            provider = self._provider_factory(s.ai_provider, "", s.ai_model,
                                              auth_mode="subscription", auth_profile=profile)
        else:
            provider = self._provider_factory(s.ai_provider, s.ai_api_key, s.ai_model)
        if provider is None:
            raise AiProviderError("AI 尚未設定，請先到設定頁選擇 AI 供應商")
        return provider, s

    def _run_script(self, name: str, max_seconds: float, prefix: str) -> RunOutcome:
        if not self._wait_external_quiet():
            return RunOutcome("stopped")
        try:
            job = self._rc.build_job(name)
        except ScriptValidationError as exc:
            return RunOutcome("aborted", str(exc))
        with self._run_lock:
            if self._stop.is_set():
                return RunOutcome("stopped")
            self._timer_fired = False
            self._interrupt_reason = ""
            self._running = True
        timer = threading.Timer(max_seconds, self._on_time_up)
        timer.daemon = True
        sampler = self._sampler_factory(self._capture_factory, self._window_manager(), self._win,
                                        self._rec.minimap_region, self._session / "frames",
                                        prefix, t0_ms=int(time.monotonic() * 1000))
        events: list[dict] = []
        sampler.start()
        timer.start()
        try:
            result = job(events.append)
        finally:
            timer.cancel()
            frames = sampler.stop()
            with self._run_lock:
                self._running = False
        for frame in frames:
            self._frames[frame.id] = frame
        trace = [(f.t_ms, f.dot) for f in frames]
        if self._stop.is_set():
            ended, reason = "stopped", ""
        elif self._interrupt_reason:
            ended, reason = "interrupted", self._interrupt_reason
        elif self._timer_fired:
            ended, reason = "time_up", ""
        elif result.ok:
            ended, reason = "finished", ""
        elif result.error == _MANUAL_STOP:
            # 不是我們停的：F10／滑鼠甩角落 → 使用者要整個停下來
            self._stop.set()
            ended, reason = "stopped", ""
        else:
            ended, reason = "aborted", result.error or ""
        return RunOutcome(ended, reason, frames, events, trace)

    def _window_manager(self):
        if self._wm is None and self._get_platform is not None:
            self._wm = self._get_platform().window_manager
        return self._wm

    def _read_dot(self):
        if self._capture is None:
            self._capture = self._capture_factory()
        try:
            return self._dot_reader(self._capture, self._window_manager(), self._win,
                                    self._rec.minimap_region)
        except Exception:
            return None

    def _ask_ai(self, kind: str, payload: dict) -> DemoProposal:
        provider, settings = self._make_provider()
        limit = settings.ai_demo_max_frames
        out = self._session / "sent"
        rec = self._rec
        if kind == "initial":
            message, scales, sizes = initial_message(rec, limit, out, self.max_sent_edge)
        elif kind == "fix":
            previous = self._sessions.load_version(self._session, payload["version"])["main"]
            message, scales, sizes = fix_message(rec, payload["run"], previous, limit, out,
                                                 self.max_sent_edge)
        else:
            previous = self._sessions.load_version(self._session, payload["version"])["return"]
            message, scales, sizes = return_fix_message(
                rec, previous, payload.get("end_dot"), payload.get("dot_trace") or [], out,
                self.max_sent_edge)
        if payload.get("error"):
            message["content"] += (f"\n\n上一次的提案被拒絕：{payload['error']}\n"
                                   "請修正後只用 propose_demo_scripts 回覆。")
        self._scales.update(scales)
        tools = demo_tools_anthropic() if settings.ai_provider == "anthropic" else demo_tools_openai()
        result = provider.stream_chat([message], system=build_demo_system_prompt(), tools=tools,
                                      on_delta=lambda _text: None, should_abort=self._stop.is_set)
        call = result.tool_call
        if call is None or call.name != TOOL_DEMO:
            raise DemoProposalError("AI 沒有提出腳本，必須呼叫 propose_demo_scripts")
        return parse_demo_proposal(call.args, sent_sizes=sizes,
                                   require_main=kind != "return_fix",
                                   require_return=kind in ("initial", "return_fix"))

    def _save_version(self, proposal: DemoProposal, version: int) -> None:
        previous = (self._sessions.load_version(self._session, version - 1)
                    if version > 1 else {})
        if not self._main_name:
            existing = self._storage.list_names()
            self._main_name = numbered_name(proposal.main_script.name, existing)
            self._return_name = numbered_name(f"{self._main_name}-回起點",
                                              [*existing, self._main_name])
        mapping = {}
        for crop in proposal.templates:
            frame = self._frames[crop.frame_id]
            scale = self._scales.get(crop.frame_id, 1.0)
            image = read_image(frame.path)
            if image is None:
                raise DemoProposalError(f"讀不到截圖 {crop.frame_id}")
            x, y, w, h = (round(v * scale) for v in crop.rect)
            name = f"{self._main_name}-{crop.name}"
            self._templates.save_template(name, image[y:y + h, x:x + w].copy())
            mapping[crop.name] = name

        def finalize(script, fallback, name):
            if script is None:
                return fallback
            data = _rename_templates(script_to_dict(script), mapping)
            data["name"] = name
            return script_to_dict(script_from_dict(data))

        data = {
            "goal": proposal.goal, "verdict": proposal.verdict, "changes": proposal.changes,
            "main": finalize(proposal.main_script, previous.get("main"), self._main_name),
            "return": finalize(proposal.return_script, previous.get("return"),
                               self._return_name),
        }
        self._sessions.save_version(self._session, version, data)


class _Ports:
    """DemoPorts 實作；所有方法在 Worker 背景執行緒呼叫。"""

    def __init__(self, controller: AiDemoController):
        self.c = controller
        self.progress = None

    def ask_ai(self, kind, payload):
        return self.c._ask_ai(kind, payload)

    def save_version(self, proposal, version):
        self.c._save_version(proposal, version)

    def apply_version(self, version):
        return self.c.apply_version(self.c._session, version)

    def run_main(self, max_seconds):
        self.c._run_count += 1
        return self.c._run_script(self.c._main_name, max_seconds, f"R{self.c._run_count}-")

    def run_return(self):
        self.c._run_count += 1
        return self.c._run_script(self.c._return_name, RETURN_MAX_SECONDS,
                                  f"B{self.c._run_count}-")

    def read_dot(self):
        return self.c._read_dot()

    def wait_user_reset(self, message):
        c = self.c
        c._reset_event.clear()
        self.report({"stage": "wait_reset", "round": 0, "message": message})
        webhook = c._get_settings().discord_webhook_url
        if webhook:
            try:
                c._notifier(webhook, f"AI 示範試跑暫停：{message}")
            except Exception as exc:           # 通知失敗不影響流程
                logger.warning("示範試跑暫停通知失敗：%s", exc)
        # 定時檢查停止：stop() 可能早在 clear() 之前送達
        while not c._reset_event.wait(0.2):
            if c._stop.is_set():
                return False
        return c._reset_answer and not c._stop.is_set()

    def report(self, event):
        if self.progress is not None:
            self.progress(event)

    def bind(self) -> None:
        self.c._report = self.report

    def stopped(self):
        return self.c._stop.is_set()

    def close(self):
        capture, self.c._capture = self.c._capture, None
        close = getattr(capture, "close_current_thread", None)
        if close is not None:
            close()
