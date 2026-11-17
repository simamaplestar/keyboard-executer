from pathlib import Path

import cv2
import numpy as np

from keyboard_executor.app.ai_demo_controller import AiDemoController
from keyboard_executor.app.settings import Settings
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.provider import ChatProvider, ChatResult, ToolCall
from keyboard_executor.core.ai.tools import TOOL_DEMO
from keyboard_executor.core.ai_demo.frames import Frame, make_thumb
from keyboard_executor.core.ai_demo.prompt import DemoRecording
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import PlayResult
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.storage.ai_demo_sessions import AiDemoSessionStore
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.templates import TemplateStore

AI_ON = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k", ai_privacy_ack=True)
WIN = WindowInfo(handle=object(), title="MapleStory Worlds", app_name="msw.exe",
                 x=0, y=0, width=320, height=240, is_active=True)


class SyncWorker(Worker):
    def start(self):
        self.run()


def script(name, template=None):
    actions = [{"type": "key_press", "key": "x"}]
    if template:
        actions.insert(0, {"type": "wait_image", "template": template, "timeout_ms": 100,
                           "on_timeout": "continue"})
    return {"name": name, "target_window": {"title_pattern": "MapleStory"},
            "actions": actions}


def call(**args):
    return ChatResult(text="", tool_call=ToolCall(TOOL_DEMO, args))


class QueueProvider(ChatProvider):
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.calls.append({"messages": messages, "system": system, "tools": tools})
        return self.results.pop(0)


class FakeRunController:
    instances = []

    def __init__(self, storage, templates, **kwargs):
        self.storage = storage
        self.ran = []
        self.stopped = 0
        self.on_run = None            # 可注入：在執行中呼叫（模擬停止/中斷）
        FakeRunController.instances.append(self)

    def build_job(self, name):
        self.storage.load(name)
        self.stopped = 0              # 真的 RunController 每個 job 都有新的 stop_event

        def job(progress):
            self.ran.append(name)
            progress({"kind": "step", "index": 0, "total": 1, "type": "key_press",
                      "label": "按鍵 x"})
            if self.on_run is not None:
                self.on_run(name)
            if self.stopped:
                return PlayResult(ok=False, actions_run=1, error="已手動停止")
            return PlayResult(ok=True, actions_run=1)
        return job

    def stop(self):
        self.stopped += 1


class FakeSampler:
    def __init__(self, capture_factory, wm, win, region, out_dir, prefix, *, t0_ms, **kw):
        self.prefix = prefix

    def start(self):
        pass

    def stop(self):
        return []


def make_frames(tmp_path, count=3):
    frames = []
    for i in range(count):
        img = np.full((480, 640, 3), 40 * i, np.uint8)
        path = tmp_path / f"D{i + 1}.png"
        cv2.imwrite(str(path), img)
        frames.append(Frame(f"D{i + 1}", i * 500, path, (640, 480), (100.0, 40.0),
                            make_thumb(img)))
    return frames


def make_rec(tmp_path):
    return DemoRecording(frames=make_frames(tmp_path), holds=[], mouse=[], event_times_ms=[],
                         duration_ms=1000, start_dot=(100.0, 40.0),
                         minimap_region=(0, 0, 200, 100), window_title="MapleStory Worlds",
                         goal_text="")


def make_controller(tmp_path, provider, dots=None, settings=AI_ON):
    FakeRunController.instances.clear()
    storage = ScriptStorage(tmp_path / "scripts")
    templates = TemplateStore(tmp_path / "scripts")
    dots = list(dots or [])
    controller = AiDemoController(
        get_settings=lambda: settings, auth_service=None, script_storage=storage,
        templates=templates, sessions=AiDemoSessionStore(tmp_path / "data"),
        get_platform=None, provider_factory=lambda *a, **k: provider,
        run_controller_factory=FakeRunController, worker_factory=SyncWorker,
        sampler_factory=FakeSampler, capture_factory=lambda: None,
        dot_reader=lambda *a: dots.pop(0) if dots else (100.0, 40.0))
    return controller, storage, templates


def run(controller, tmp_path):
    results = []
    controller.finished.connect(results.append)
    session = controller.start_loop(make_rec(tmp_path), WIN)
    return results[0], session


def test_runs_loop_end_to_end_with_fakes(qapp, tmp_path):
    provider = QueueProvider([
        call(goal="打怪", main_script=script("練功"), return_script=script("回去")),
        call(goal="打怪", verdict="success"),
    ])
    controller, storage, _ = make_controller(tmp_path, provider)
    result, session = run(controller, tmp_path)
    assert result.status == "success"
    assert storage.load("練功").name == "練功"
    assert storage.load("練功-回起點").name == "練功-回起點"
    rc = FakeRunController.instances[0]
    assert rc.ran == ["練功-回起點", "練功"]
    assert TOOL_DEMO in str(provider.calls[0]["tools"])
    assert "示範錄製模式" in provider.calls[0]["system"]
    assert not controller.active


def test_uses_own_run_controller(qapp, tmp_path):
    provider = QueueProvider([call(goal="g", main_script=script("練功"),
                                   return_script=script("回去")),
                              call(goal="g", verdict="success")])
    controller, _, _ = make_controller(tmp_path, provider)
    run(controller, tmp_path)
    assert len(FakeRunController.instances) == 1


def test_stop_stops_current_run_and_loop(qapp, tmp_path):
    provider = QueueProvider([call(goal="g", main_script=script("練功"),
                                   return_script=script("回去"))])
    controller, _, _ = make_controller(tmp_path, provider)
    original = FakeRunController.__init__

    def hook(self, *a, **k):
        original(self, *a, **k)
        self.on_run = lambda name: controller.stop() if name == "練功" else None
    FakeRunController.__init__ = hook
    try:
        result, _ = run(controller, tmp_path)
    finally:
        FakeRunController.__init__ = original
    assert result.status == "stopped"
    assert FakeRunController.instances[0].ran == ["練功-回起點", "練功"]
    assert len(provider.calls) == 1


def test_guard_stop_ends_loop(qapp, tmp_path):
    """F10/角落甩滑鼠：RunController 的 guard 直接停回放（不是我們的計時器）→ 整個循環停止。"""
    provider = QueueProvider([call(goal="g", main_script=script("練功"),
                                   return_script=script("回去"))])
    controller, _, _ = make_controller(tmp_path, provider)
    original = FakeRunController.__init__

    def hook(self, *a, **k):
        original(self, *a, **k)
        self.on_run = lambda name: self.stop() if name == "練功" else None
    FakeRunController.__init__ = hook
    try:
        result, _ = run(controller, tmp_path)
    finally:
        FakeRunController.__init__ = original
    assert result.status == "stopped"


def test_interrupt_marks_round_interrupted(qapp, tmp_path):
    provider = QueueProvider([call(goal="g", main_script=script("練功"),
                                   return_script=script("回去"))])
    controller, _, _ = make_controller(tmp_path, provider)
    original = FakeRunController.__init__

    def hook(self, *a, **k):
        original(self, *a, **k)
        self.on_run = (lambda name: controller.interrupt("規則「測謊」觸發")
                       if name == "練功" else None)
    FakeRunController.__init__ = hook
    try:
        result, _ = run(controller, tmp_path)
    finally:
        FakeRunController.__init__ = original
    assert result.status == "interrupted"
    assert "測謊" in result.message


def test_name_conflict_gets_number(qapp, tmp_path):
    provider = QueueProvider([call(goal="g", main_script=script("練功"),
                                   return_script=script("回去")),
                              call(goal="g", verdict="success")])
    controller, storage, _ = make_controller(tmp_path, provider)
    storage.save(script_from_dict(script("練功", None) | {"actions": [
        {"type": "key_press", "key": "z"}]}))
    run(controller, tmp_path)
    assert storage.load("練功").actions[0].params["key"] == "z"
    assert storage.load("練功 2").actions[0].params["key"] == "x"
    assert storage.load("練功 2-回起點")


def test_template_crop_scaled_back(qapp, tmp_path):
    provider = QueueProvider([
        call(goal="g", main_script=script("練功", template="怪"),
             return_script=script("回去"),
             templates=[{"name": "怪", "frame": "D2", "rect": [10, 10, 20, 20]}]),
        call(goal="g", verdict="success"),
    ])
    controller, storage, templates = make_controller(tmp_path, provider)
    import keyboard_executor.core.ai_demo.frames as frames_mod
    original = frames_mod.MAX_SENT_EDGE
    run(controller, tmp_path)
    saved = templates.load_template("練功-怪")
    assert saved.shape[:2] == (20, 20)          # 640px 未縮放 → sent_scale 1.0
    assert storage.load("練功").actions[0].params["template"] == "練功-怪"
    assert frames_mod.MAX_SENT_EDGE == original


def test_template_crop_uses_sent_scale(qapp, tmp_path):
    provider = QueueProvider([
        call(goal="g", main_script=script("練功", template="怪"),
             return_script=script("回去"),
             templates=[{"name": "怪", "frame": "D2", "rect": [10, 10, 20, 20]}]),
        call(goal="g", verdict="success"),
    ])
    controller, _, templates = make_controller(tmp_path, provider)
    controller.max_sent_edge = 320              # 640 → 320，sent_scale 2.0
    run(controller, tmp_path)
    assert templates.load_template("練功-怪").shape[:2] == (40, 40)


def test_apply_version_restores_old_version(qapp, tmp_path):
    provider = QueueProvider([
        call(goal="g", main_script=script("練功"), return_script=script("回去")),
        call(goal="g", verdict="needs_fix", changes="改",
             main_script=script("練功") | {"actions": [{"type": "key_press", "key": "c"}]}),
        call(goal="g", verdict="success"),
    ])
    controller, storage, _ = make_controller(tmp_path, provider)
    result, session = run(controller, tmp_path)
    assert storage.load("練功").actions[0].params["key"] == "c"
    controller.apply_version(session, 1)
    assert storage.load("練功").actions[0].params["key"] == "x"


def test_no_tool_call_retried_then_fails(qapp, tmp_path):
    provider = QueueProvider([ChatResult(text="我覺得..."), ChatResult(text="還是文字")])
    controller, _, _ = make_controller(tmp_path, provider)
    result, _ = run(controller, tmp_path)
    assert result.status == "ai_failed"
    assert "propose_demo_scripts" in provider.calls[1]["messages"][0]["content"]


def test_missing_ai_settings_fails_cleanly(qapp, tmp_path):
    controller, _, _ = make_controller(tmp_path, None)
    result, _ = run(controller, tmp_path)
    assert result.status == "ai_failed"


def test_wait_user_reset_notifies_discord_and_honours_stop(qapp, tmp_path):
    from dataclasses import replace
    from keyboard_executor.app.ai_demo_controller import _Ports
    sent = []
    settings = replace(AI_ON, discord_webhook_url="https://discord.com/api/webhooks/1/x")
    controller, _, _ = make_controller(tmp_path, None, settings=settings)
    controller._notifier = lambda url, text: sent.append((url, text))
    controller._stop.set()                       # 停止已送出：不可卡在等待
    assert _Ports(controller).wait_user_reset("角色沒有回到起點") is False
    assert sent == [("https://discord.com/api/webhooks/1/x", "AI 示範試跑暫停：角色沒有回到起點")]


def test_wait_user_reset_without_webhook_does_not_notify(qapp, tmp_path):
    import threading
    from keyboard_executor.app.ai_demo_controller import _Ports
    sent = []
    controller, _, _ = make_controller(tmp_path, None)
    controller._notifier = lambda url, text: sent.append(text)
    threading.Timer(0.2, lambda: controller.resume_after_reset(True)).start()
    assert _Ports(controller).wait_user_reset("回不去") is True
    assert sent == []


def test_waits_for_external_rule_action_before_running(qapp, tmp_path):
    import threading
    import time as _time
    controller, _, _ = make_controller(tmp_path, None)
    controller.external_settle_sec = 0.0
    controller.set_external_busy(True)
    threading.Timer(0.3, lambda: controller.set_external_busy(False)).start()
    started = _time.monotonic()
    assert controller._wait_external_quiet() is True
    assert _time.monotonic() - started >= 0.25


def test_external_wait_gives_up_on_stop(qapp, tmp_path):
    controller, _, _ = make_controller(tmp_path, None)
    controller.set_external_busy(True)
    controller._stop.set()
    assert controller._wait_external_quiet() is False
