"""回放引擎：把 Script 的動作序列執行到目標視窗。

執行模型：同步逐動作執行。stop_event 在每個動作前檢查，供 Ctrl+C 與
緊急停止熱鍵/failsafe（F10、滑鼠甩左上角，見 core/guard.py）隨時中斷；
未注入 sleep 時，delay/window_retry 的等待本身以 stop_event.wait 實作，
停止時提早醒來。每個座標動作前都重新查詢視窗位置（視窗移動也能點對位
置），視窗消失則安全中止、絕不對其他視窗送輸入。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass

from keyboard_executor.core.geometry import Point, Rect, to_absolute
from keyboard_executor.core.models import (
    Action,
    ActionType,
    Script,
    ScriptValidationError,
    action_label,
)
from keyboard_executor.core.vision import find_text, match_template
from keyboard_executor.core.sequence_pause import SequencePause, SequencePauseError
from keyboard_executor.platforms.base import MouseButton, OcrRecognitionError, WindowInfo
from keyboard_executor.platforms.factory import Platform

logger = logging.getLogger(__name__)

_MAX_RUN_SCRIPT_DEPTH = 8
_POLL_INTERVAL_MS = 500  # wait_* 輪詢間隔（毫秒）
# hold_ms=0 點按的實際按住時間：0ms 的按下＋放開會被輪詢式讀鍵
# （DirectInput/GetAsyncKeyState，每幀一次）的遊戲在兩次輪詢間整個漏掉
# （同 input_pynput._COMBO_HOLD 的理由，實測 0ms 在 60Hz 輪詢下漏 3 成）。
# 100ms 對齊實測的實體鍵盤點按下限（raw input 側錄 42 次點按為 95–208ms），
# 也留住「遊戲要求至少按住 N 毫秒」類判定的餘裕。
TAP_HOLD_MS = 100
# 方向鍵組合（例如 下＋空白 下跳）：遊戲要先讀到方向鍵已按住，才把另一鍵
# 當成方向動作；放開也要晚於另一鍵。方向鍵先按、晚放，各留一段時間。
DIRECTION_LEAD_MS = 100
DIRECTION_TRAIL_MS = 100
_DIRECTION_KEYS = frozenset({"up", "down", "left", "right"})
_SHORTCUT_MODIFIERS = frozenset({"ctrl", "control", "cmd", "win", "super"})


def direction_combo(keys):
    """方向鍵在前的按鍵順序與方向鍵數量；不適用時回傳 None。

    Ctrl/Cmd 類快捷鍵（Ctrl+左 跳字等）與純方向鍵組合維持原本同時按下。
    """
    names = [k.strip().lower() for k in keys]
    arrows = [k for k, n in zip(keys, names) if n in _DIRECTION_KEYS]
    others = [k for k, n in zip(keys, names) if n not in _DIRECTION_KEYS]
    if not arrows or not others or _SHORTCUT_MODIFIERS & set(names):
        return None
    return arrows + others, len(arrows)


@dataclass(frozen=True)
class PlayResult:
    ok: bool
    actions_run: int
    error: str | None = None


class _PlayerAbort(Exception):
    """內部中止訊號；訊息即 PlayResult.error。"""


class _SequenceRequested(Exception):
    """Unwind a checked mouse operation before handling on the input owner."""


@dataclass
class _BranchDecision:
    epoch: tuple[int, int]
    committed: bool = False


class _RetryVisualBranch(Exception):
    def __init__(self, decision):
        self.decision = decision


@dataclass(frozen=True)
class _Goto:
    """_run_one 的控制訊號：跳到同層動作清單的 index（不 +1）。"""
    index: int


class Player:
    """storage 供 run_script 載入子腳本；sleep/rng/stop_event 注入供測試。

    stop 語義：Player 不會自動清除 stop_event。重用同一實例（或共用同一
    stop_event 的新實例）再次 play 前，呼叫端需自行 stop_event.clear()，
    否則第二次 play 會立即以「已手動停止」中止。未注入 sleep 時，預設等待
    以 stop_event.wait 實作：delay / window_retry 等待途中設 stop_event
    會提早醒來，並在下一個停止檢查點（_check_stop）中止。

    視覺動作（wait_/if_/click_）需 platform 提供 screen_capture、ocr_engine，
    模板動作另需 templates loader；缺任一則安全中止。輪詢間隔
    `_POLL_INTERVAL_MS`（500ms）以可中斷 `_sleep` 等待。
    """

    def __init__(self, platform: Platform, storage=None, stop_event=None,
                 sleep=None, rng=None, templates=None, clock=time.monotonic,
                 on_step=None, on_action_boundary=None):
        self._platform = platform
        self._storage = storage
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._raw_sleep = sleep if sleep is not None else (
            lambda seconds: self._stop.wait(seconds) and None)
        self._rng = rng if rng is not None else random.Random()
        self._templates = templates
        self._clock = clock
        self._on_step = on_step
        self._on_action_boundary = on_action_boundary
        self._actions_run = 0
        self._script_stack: list[str] = []
        self._current_depth = 0
        self._pause = None
        self._action_context = None
        self._branch_decisions = []
        self._current_index = 0

    def _sleep(self, seconds):
        if self._pause is not None and self._action_context is not None:
            self._pause.wait(seconds, *self._action_context)
        else:
            self._raw_sleep(seconds)

    def _direction_combo(self, backend, keys, lead_keys, hold):
        """方向鍵先按住，另一鍵按完放開後方向鍵才放；finally 保證全部放鍵。"""
        pressed = []
        try:
            for key in keys[:lead_keys]:
                pressed.append(key)
                backend.key_down(key)
            self._sleep(DIRECTION_LEAD_MS / 1000)
            if self._stop.is_set():
                return
            for key in keys[lead_keys:]:
                pressed.append(key)
                backend.key_down(key)
            self._sleep(hold)
            while len(pressed) > lead_keys:
                backend.key_up(pressed.pop())
            if not self._stop.is_set():
                self._sleep(DIRECTION_TRAIL_MS / 1000)
        finally:
            while pressed:
                backend.key_up(pressed.pop())

    def _sequence_epoch(self):
        return (self._pause.count if self._pause else 0,
                getattr(self._on_action_boundary, 'sequence_epoch', 0))

    def _validate_branch_decisions(self):
        for decision in self._branch_decisions:
            if not decision.committed and decision.epoch != self._sequence_epoch():
                raise _RetryVisualBranch(decision)

    def _commit_effect(self):
        self._validate_branch_decisions()
        for decision in self._branch_decisions:
            decision.committed = True

    def _sequence_checkpoint(self):
        paused = False
        if self._pause is not None and self._action_context is not None:
            paused = self._pause.checkpoint(*self._action_context)
        self._validate_branch_decisions()
        return paused

    def _pause_window_state(self, win):
        fresh = self._platform.window_manager.refresh(win)
        self._check_stop()
        if fresh is None or not fresh.is_active:
            raise SequencePauseError('接續腳本前目標視窗失效或已失焦，已停止')
        return fresh.x, fresh.y, fresh.width, fresh.height

    def _pause_window_geometry(self, win):
        """Checkpoint 握手：只要求視窗存在與幾何穩定。背景偵測到的回合
        由 submitter 在輸入前重新切回前景，不能在此因失焦直接中止。"""
        fresh = self._platform.window_manager.refresh(win)
        self._check_stop()
        if fresh is None:
            raise SequencePauseError('接續腳本前目標視窗已關閉，已停止')
        return fresh.x, fresh.y, fresh.width, fresh.height

    def _action_time(self):
        return self._pause.action_time() if self._pause else self._clock()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop

    def _emit(self, record: dict) -> None:
        if self._on_step is not None:
            self._on_step(record)

    def play(self, script: Script) -> PlayResult:
        self._actions_run = 0
        self._minimap_slide = None
        self._minimap_face = None
        self._script_stack = []
        self._pause = None
        self._action_context = None
        self._branch_decisions = []
        # 定時技能（只看主腳本設定）：開始時全部先放一次。
        self._timed = [[item, self._clock()] for item in script.settings.timed_keys]
        config = script.settings.sequence_input
        runtime = self._on_action_boundary
        if (config is not None and config.enabled
                and callable(getattr(runtime, 'pause_for_sequence', None))
                and callable(getattr(runtime, 'sequence_pending', None))):
            self._pause = SequencePause(runtime, self._stop, self._clock, self._raw_sleep,
                                        validate=self._pause_window_geometry)
        try:
            self._execute_script(script, depth=0)
        except (_PlayerAbort, SequencePauseError) as e:
            return PlayResult(ok=False, actions_run=self._actions_run, error=str(e))
        except Exception as e:  # 平台層/按鍵映射等意外錯誤不可讓回放崩潰
            return PlayResult(ok=False, actions_run=self._actions_run, error=f"未預期錯誤: {e}")
        return PlayResult(ok=True, actions_run=self._actions_run)

    # -- 腳本層（Task 6 會在此加入 repeat 與 run_script 巢狀） --

    def _execute_script(self, script: Script, depth: int) -> None:
        self._check_stop()
        if (script.settings.sequence_input is not None and script.settings.sequence_input.enabled
                and not getattr(self._on_action_boundary, "supports_sequence_input", False)):
            raise _PlayerAbort("此執行環境未初始化圖片順序輸入，請由 GUI 主腳本執行（子腳本沿用主腳本設定）")
        if (script.settings.chat_reply is not None and script.settings.chat_reply.active
                and self._on_action_boundary is None):
            raise _PlayerAbort("此執行環境未初始化 AI 自動回覆；請由 GUI 執行已啟用此功能的主腳本"
                               "（子腳本沿用主腳本設定）")
        if depth > _MAX_RUN_SCRIPT_DEPTH:
            raise _PlayerAbort(f"run_script 巢狀超過 {_MAX_RUN_SCRIPT_DEPTH} 層")
        if script.name in self._script_stack:
            raise _PlayerAbort(f"run_script 循環呼叫: {script.name}")
        previous_depth = self._current_depth
        self._current_depth = depth
        self._script_stack.append(script.name)
        try:
            win = self._acquire_window(script)
            repeat = script.settings.repeat
            done = 0
            while repeat == -1 or done < repeat:
                self._check_stop()
                self._run_actions(script.actions, script, win)
                done += 1
        finally:
            self._script_stack.pop()
            self._current_depth = previous_depth

    def _acquire_window(self, script: Script) -> WindowInfo:
        wm = self._platform.window_manager
        tw = script.target_window
        settings = script.settings
        for attempt in range(settings.window_retry + 1):
            self._check_stop()
            windows = wm.find_windows(title_pattern=tw.title_pattern, app_name=tw.app_name)
            if windows:
                win = windows[0]
                self._sequence_checkpoint()
                self._commit_effect()
                if not wm.activate(win):
                    raise _PlayerAbort(f"無法將視窗切到前景: {win.title}")
                self._platform.input_backend.set_target_window(win)
                return win
            if attempt < settings.window_retry:
                self._sleep(settings.window_retry_interval_ms / 1000)
        raise _PlayerAbort("找不到目標視窗")

    # -- 動作層 --

    def _run_actions(self, actions, script: Script, win: WindowInfo) -> None:
        i = 0
        while i < len(actions):
            self._check_stop()
            if self._on_action_boundary is not None:
                self._on_action_boundary(script, win)
                self._check_stop()
            self._fire_timed_keys(script, win)
            self._current_index = i
            if self._on_step is not None:
                action = actions[i]
                self._on_step({"kind": "step", "index": i, "total": len(actions),
                               "type": str(action.type), "label": action_label(action)})
            signal = self._run_one(actions[i], script, win)
            self._actions_run += 1
            if isinstance(signal, _Goto):
                if not 0 <= signal.index < len(actions):
                    raise _PlayerAbort(f"goto_index 超出範圍: {signal.index}")
                i = signal.index
            else:
                i = i + 1

    def _fire_timed_keys(self, script, win) -> None:
        """到時間的定時技能在動作之間按下；下次時間從按完那一刻起算。"""
        for entry in getattr(self, "_timed", ()):
            item, due = entry
            if self._clock() < due:
                continue
            logger.info("定時技能：按 %s（每 %g 秒）", item.key, item.interval_sec)
            if self._on_step is not None:
                self._on_step({"kind": "timed_key", "key": item.key,
                               "label": f"定時技能 {item.key}"})
            self._run_one(Action(type=ActionType.KEY_PRESS,
                                 params={"key": item.key, "hold_ms": item.hold_ms}), script, win)
            if item.wait_ms:
                self._sleep(item.wait_ms / 1000)
            self._check_stop()
            entry[1] = self._clock() + item.interval_sec

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise _PlayerAbort("已手動停止")

    def _to_screen(self, win: WindowInfo, rel_x: int, rel_y: int) -> tuple[int, int]:
        fresh = self._platform.window_manager.refresh(win)
        if fresh is None:
            raise _PlayerAbort("目標視窗已關閉")
        point = to_absolute(Point(fresh.x, fresh.y), Point(rel_x, rel_y))
        return point.x, point.y

    def _ensure_alive(self, win: WindowInfo) -> None:
        """鍵盤動作前的輕量存活檢查：視窗關閉即安全中止，不對焦點視窗誤送輸入。"""
        if not self._platform.window_manager.is_alive(win):
            raise _PlayerAbort("目標視窗已關閉")

    def _require_capture(self):
        cap = self._platform.screen_capture
        if cap is None:
            raise _PlayerAbort("此動作需要螢幕擷取能力，但平台未提供")
        return cap

    def _region_rect(self, win: WindowInfo, region):
        """region（視窗相對，點；None=整個視窗）→ 螢幕絕對實體像素 Rect，並回傳
        (Rect, rx, ry, scale) 供命中中心換算。"""
        fresh = self._platform.window_manager.refresh(win)
        if fresh is None:
            raise _PlayerAbort("目標視窗已關閉")
        cap = self._require_capture()
        scale = cap.scale_factor()
        if region is None:
            rx, ry, rw, rh = 0, 0, fresh.width, fresh.height
        else:
            rx, ry, rw, rh = region
        rect = Rect(round((fresh.x + rx) * scale), round((fresh.y + ry) * scale),
                    round(rw * scale), round(rh * scale))
        return rect, rx, ry, scale, fresh

    def _center_to_screen(self, fresh, rx, ry, scale, cx, cy) -> tuple[int, int]:
        """命中中心（region 相對，實體像素）→ 螢幕絕對點。"""
        rel = Point(rx + round(cx / scale), ry + round(cy / scale))
        pt = to_absolute(Point(fresh.x, fresh.y), rel)
        return pt.x, pt.y

    def _load_template(self, name: str):
        if self._templates is None:
            raise _PlayerAbort("此動作需要模板來源，但未提供")
        return self._templates(name)

    def _sequence_match(self, matcher):
        while True:
            self._sequence_checkpoint()
            epoch = self._pause.count if self._pause else 0
            hit = matcher()
            self._sequence_checkpoint()
            if self._pause is None or self._pause.count == epoch:
                return hit

    def _match_once_text(self, win, region, pattern, mode):
        return self._sequence_match(lambda: self._read_text_hit(win, region, pattern, mode))

    def _read_text_hit(self, win, region, pattern, mode):
        rect, rx, ry, scale, fresh = self._region_rect(win, region)
        cap = self._require_capture()
        ocr = self._platform.ocr_engine
        if ocr is None:
            raise _PlayerAbort("此動作需要 OCR 能力，但平台未提供")
        image = cap.capture(rect)
        try:
            boxes = ocr.recognize(image)
        except OcrRecognitionError as exc:
            # Generic visual actions historically treat transient inference failure
            # as a miss. Sequence/chat services still receive the error and fail closed.
            logger.warning('文字比對略過本次 OCR 推論失敗：%s', exc)
            return None
        hit = find_text(boxes, pattern, mode)
        if hit is None:
            return None
        cx = hit.x + hit.width // 2
        cy = hit.y + hit.height // 2
        return self._center_to_screen(fresh, rx, ry, scale, cx, cy)

    def _match_once_image(self, win, region, template_name, threshold, mirror=False,
                          log=False):
        return self._sequence_match(
            lambda: self._read_image_hit(win, region, template_name, threshold, mirror, log))

    def _read_image_hit(self, win, region, template_name, threshold, mirror=False, log=False):
        rect, rx, ry, scale, fresh = self._region_rect(win, region)
        cap = self._require_capture()
        image = cap.capture(rect)
        template = self._load_template(template_name)
        m = match_template(image, template, threshold=threshold, mirror=mirror)
        if log:
            # 只在 if_image 記錄：之後可從日誌分辨「當時沒有目標」或「相似度不足/位置不對」。
            logger.info("若出現圖像「%s」：相似度 %.2f（門檻 %.2f），最佳位置 (%d, %d) → %s",
                        template_name, m.confidence, threshold, rx + round(m.x / scale),
                        ry + round(m.y / scale), "符合" if m.found else "不符合")
        if not m.found:
            return None
        return self._center_to_screen(fresh, rx, ry, scale, m.x, m.y)

    def _poll_until(self, matcher, timeout_ms) -> tuple[int, int] | None:
        """輪詢 matcher() 直到回傳座標或逾時；stop_event 於 _sleep 途中提早醒來。
        逾時回傳 None。matcher 的暫時性例外（擷取/OCR/比對失敗）視為本輪不中：
        記錄並跳過該輪（spec §10），不中止整個回放；_PlayerAbort（缺能力、
        視窗關閉）仍上拋中止。"""
        deadline = self._action_time() + timeout_ms / 1000
        while True:
            self._check_stop()
            try:
                hit = matcher()
            except (_PlayerAbort, SequencePauseError, _RetryVisualBranch):
                raise
            except Exception as e:
                logger.warning("wait 動作本輪擷取或辨識失敗，已跳過：%s", e)
                hit = None
            if hit is not None:
                return hit
            if self._action_time() + 1e-9 >= deadline:
                return None
            self._sleep(_POLL_INTERVAL_MS / 1000)

    def _run_wait(self, action: Action, win: WindowInfo) -> _Goto | None:
        self._commit_effect()
        p = action.params
        index = self._current_index
        # 只有在有人收事件時才讀時鐘：多讀一次會改變注入時鐘的序列
        started = self._action_time() if self._on_step is not None else 0.0
        if action.type is ActionType.WAIT_TEXT:
            hit = self._poll_until(
                lambda: self._match_once_text(win, p["region"], p["pattern"], p["mode"]),
                p["timeout_ms"])
        else:  # WAIT_IMAGE
            hit = self._poll_until(
                lambda: self._match_once_image(win, p["region"], p["template"], p["threshold"]),
                p["timeout_ms"])
        if self._on_step is not None:
            self._emit({"kind": "wait_result", "index": index, "type": str(action.type),
                        "matched": hit is not None,
                        "elapsed_ms": int(round((self._action_time() - started) * 1000)),
                        "on_timeout": None if hit is not None else p["on_timeout"]})
        if hit is not None:
            return None
        on_timeout = p["on_timeout"]
        if on_timeout == "continue":
            return None
        if on_timeout == "goto":
            return _Goto(p["goto_index"])
        raise _PlayerAbort(f"動作 {action.type} 等待逾時（{p['timeout_ms']}ms）")

    def _run_if(self, action: Action, script: Script, win: WindowInfo) -> None:
        p = action.params
        index = self._current_index
        while True:
            if action.type is ActionType.IF_TEXT:
                hit = self._match_once_text(win, p['region'], p['pattern'], p['mode'])
            else:
                hit = self._match_once_image(win, p['region'], p['template'], p['threshold'],
                                             p.get('mirror', False), log=True)
            branch = p['then'] if hit is not None else p['else']
            self._emit({"kind": "branch", "index": index, "type": str(action.type),
                        "taken": "then" if hit is not None else "else"})
            if self._pause is None:
                self._run_actions(branch, script, win)
                return
            decision = _BranchDecision(self._sequence_epoch())
            self._branch_decisions.append(decision)
            try:
                self._run_actions(branch, script, win)
                return
            except _RetryVisualBranch as retry:
                if retry.decision is not decision:
                    raise
                # No effect has committed this branch; re-read after the handoff.
            finally:
                self._branch_decisions.pop()

    def _sequence_mouse(self, win, operation, *, drag=False):
        while True:
            self._sequence_checkpoint()
            expected = self._pause_window_state(win)
            started = False
            def before_press():
                nonlocal started
                started = True
            def check():
                self._check_stop()
                if self._pause.pending:
                    raise _SequenceRequested()
                fresh = self._pause_window_state(win)
                if self._pause.pending:
                    raise _SequenceRequested()
                if fresh != expected:
                    raise SequencePauseError('滑鼠操作前目標視窗已移動，已停止')
                self._commit_effect()
            try:
                operation(check, before_press)
                return
            except _SequenceRequested:
                # Native checked drag has already released its button in finally.
                self._sequence_checkpoint()
                if drag and started:
                    self._stop.set()
                    raise SequencePauseError('拖曳曾被中斷，圖片處理後停止，請確認畫面再執行')

    def _run_click(self, action: Action, win: WindowInfo) -> None:
        p = action.params
        def click(check=None, before_press=None):
            if action.type is ActionType.CLICK_TEXT:
                hit = self._match_once_text(win, p['region'], p['pattern'], p['mode'])
            else:
                hit = self._match_once_image(win, p['region'], p['template'], p['threshold'])
            if hit is not None:
                backend = self._platform.input_backend
                if check:
                    backend.mouse_click_checked(*hit, MouseButton.LEFT, 1, check=check)
                else:
                    backend.mouse_click(*hit, MouseButton.LEFT, 1)
        if self._pause:
            self._sequence_mouse(win, click)
        else:
            click()

    def _run_one(self, action: Action, script: Script, win: WindowInfo) -> _Goto | None:
        previous, self._action_context = self._action_context, (script, win)
        try:
            self._sequence_checkpoint()
            result = self._dispatch_one(action, script, win)
            self._sequence_checkpoint()
            return result
        finally:
            self._action_context = previous

    def _dispatch_one(self, action: Action, script: Script, win: WindowInfo) -> _Goto | None:
        backend = self._platform.input_backend
        p = action.params
        atype = action.type
        if atype is ActionType.KEY_PRESS:
            self._ensure_alive(win)
            self._sequence_checkpoint()
            if self._pause:
                self._commit_effect()
                self._pause.hold([p['key']], (p['hold_ms'] or TAP_HOLD_MS) / 1000,
                                 script, win, backend, repeat=p['hold_ms'] > 0,
                                 restore=p['hold_ms'] > 0)
            elif p["hold_ms"] > 0:
                # hold 由 Player 掌管：用可中斷的 _sleep 撐住，finally 保證放鍵，
                # 停止途中不卡鍵、放鍵後由下一個 _check_stop 中止。需要模擬
                # 硬體自動重複的後端可要求分段等待並在段間重送 key-down。
                backend.key_down(p["key"])
                try:
                    remaining = p["hold_ms"] / 1000
                    interval = backend.key_repeat_interval(p["key"])
                    if interval is None:
                        self._sleep(remaining)
                    else:
                        while remaining > 1e-9 and not self._stop.is_set():
                            step = min(interval, remaining)
                            self._sleep(step)
                            remaining -= step
                            if remaining > 1e-9 and not self._stop.is_set():
                                consumed = backend.key_repeat(p["key"]) or 0.0
                                remaining -= max(0.0, consumed)
                finally:
                    backend.key_up(p["key"])
            else:
                backend.key_press(p["key"], TAP_HOLD_MS)  # 點按也要撐住最小時長
        elif atype is ActionType.KEY_COMBO:
            self._ensure_alive(win)
            keys = list(p["keys"])
            directional = direction_combo(keys)
            self._sequence_checkpoint()
            if directional:
                keys, lead_keys = directional
                hold = (p['hold_ms'] or TAP_HOLD_MS) / 1000
            if self._pause and directional:
                self._commit_effect()
                self._pause.hold(keys, hold, script, win, backend,
                                 restore=p['hold_ms'] > 0, lead_keys=lead_keys,
                                 lead=DIRECTION_LEAD_MS / 1000,
                                 trail=DIRECTION_TRAIL_MS / 1000)
            elif self._pause:
                self._commit_effect()
                self._pause.hold(keys, p['hold_ms'] / 1000 if p['hold_ms'] else .04,
                                 script, win, backend, restore=p['hold_ms'] > 0)
            elif directional:
                self._direction_combo(backend, keys, lead_keys, hold)
            elif p["hold_ms"] > 0:
                # 長按由 Player 掌管：可中斷 _sleep 撐住，finally 保證放鍵，
                # 停止途中不卡鍵、放鍵後由下一個 _check_stop 中止。
                backend.key_combo_down(keys)
                try:
                    self._sleep(p["hold_ms"] / 1000)
                finally:
                    backend.key_combo_up(keys)
            else:
                backend.key_combo(keys)          # 維持固定 40ms（遊戲偵測）
        elif atype is ActionType.TEXT_INPUT:
            self._ensure_alive(win)
            if self._pause:
                for char in p['text']:
                    self._sequence_checkpoint()
                    self._check_stop()
                    self._commit_effect()
                    backend.type_text(char)
            else:
                backend.type_text(p["text"])
        elif atype is ActionType.MOUSE_MOVE:
            if self._pause:
                def move(check, _):
                    point = self._to_screen(win, p['x'], p['y'])
                    check()
                    backend.mouse_move(*point)
                self._sequence_mouse(win, move)
            else:
                x, y = self._to_screen(win, p['x'], p['y'])
                backend.mouse_move(x, y)
        elif atype is ActionType.MOUSE_CLICK:
            if self._pause:
                def click(check, _):
                    x, y = self._to_screen(win, p['x'], p['y'])
                    backend.mouse_click_checked(x, y, MouseButton(p['button']), 1, check=check)
                for _ in range(p['count']):
                    self._sequence_mouse(win, click)
            else:
                x, y = self._to_screen(win, p['x'], p['y'])
                backend.mouse_click(x, y, MouseButton(p['button']), p['count'])
        elif atype is ActionType.MOUSE_DRAG:
            if self._pause:
                def drag(check, before_press):
                    start = self._to_screen(win, *p['from'])
                    end = self._to_screen(win, *p['to'])
                    backend.mouse_drag_checked(*start, *end, MouseButton(p['button']),
                                               check=check, before_press=before_press)
                self._sequence_mouse(win, drag, drag=True)
            else:
                start = self._to_screen(win, *p['from'])
                end = self._to_screen(win, *p['to'])
                backend.mouse_drag(*start, *end, MouseButton(p['button']))
        elif atype is ActionType.SCROLL:
            if self._pause:
                def scroll(check, _):
                    x, y = self._to_screen(win, p['x'], p['y'])
                    backend.scroll_checked(x, y, p['dx'], p['dy'], check=check)
                self._sequence_mouse(win, scroll)
            else:
                x, y = self._to_screen(win, p['x'], p['y'])
                backend.scroll(x, y, p['dx'], p['dy'])
        elif atype is ActionType.DELAY:
            self._commit_effect()
            self._sleep(self._delay_seconds(p["ms"], script.settings))
        elif atype is ActionType.LOOP:
            count = p["count"]
            done = 0
            while count == -1 or done < count:
                self._check_stop()
                self._run_actions(p["actions"], script, win)
                done += 1
        elif atype is ActionType.RUN_SCRIPT:
            if self._storage is None:
                raise _PlayerAbort("run_script 需要腳本儲存來源，但未提供")
            try:
                sub = self._storage.load(p["script_name"])
            except ScriptValidationError as e:
                raise _PlayerAbort(str(e)) from e
            self._execute_script(sub, self._current_depth + 1)
            fresh = self._platform.window_manager.refresh(win)
            if fresh is None:
                raise _PlayerAbort("目標視窗已關閉")
            if not self._platform.window_manager.activate(fresh):
                raise _PlayerAbort(f"無法將視窗切回前景: {fresh.title}")
            self._platform.input_backend.set_target_window(fresh)
        elif atype in (ActionType.WAIT_TEXT, ActionType.WAIT_IMAGE):
            return self._run_wait(action, win)
        elif atype in (ActionType.IF_TEXT, ActionType.IF_IMAGE):
            self._run_if(action, script, win)
        elif atype in (ActionType.CLICK_TEXT, ActionType.CLICK_IMAGE):
            self._run_click(action, win)
        elif atype is ActionType.MINIMAP_MOVE:
            return self._run_minimap_move(action, win)
        elif atype is ActionType.MINIMAP_GOTO:
            return self._run_minimap_goto(action, win)
        elif atype is ActionType.GOTO:
            return _Goto(action.params["goto_index"])
        else:
            raise _PlayerAbort(f"動作類型尚未支援: {atype}")

    def _run_minimap_move(self, action: Action, win: WindowInfo) -> _Goto | None:
        """依小地圖黃點閉迴路移動；按住期間只用不觸發暫停的原始 sleep，
        所有鍵在停止/失敗/讓出時都會放開（MinimapMover.finally）。"""
        from keyboard_executor.core.minimap import MinimapMover

        p = action.params
        backend = self._platform.input_backend
        self._ensure_alive(win)
        self._sequence_checkpoint()
        self._commit_effect()
        reasons = []
        read = self._minimap_reader(win, p["region"])

        def press(key):
            self._check_stop()
            backend.key_down(key)

        def sleep(seconds):
            self._raw_sleep(seconds)
            self._check_stop()

        def idle():
            self._sequence_checkpoint()
            self._commit_effect()

        gate = None
        if p.get("path_template"):
            template = self._load_template(p["path_template"])

            def gate():
                # 只有偵測範圍（同一層）出現目標怪物才沿路按鍵；擷取失敗視為沒看到。
                try:
                    rect, *_ = self._region_rect(win, p["path_region"])
                    image = self._require_capture().capture(rect)
                except _PlayerAbort:
                    raise
                except Exception as e:
                    logger.warning("怪物偵測擷取失敗，本次不按沿路按鍵：%s", e)
                    return False
                return match_template(image, template, threshold=p["path_threshold"],
                                      mirror=True).found

        mover = MinimapMover(
            read, press, backend.key_up, sleep, self._action_time,
            interrupted=lambda: bool(self._pause and self._pause.pending),
            idle=idle, log=reasons.append, path_key=p.get("path_key"), path_gate=gate,
            path_step=p.get("path_step", 5), hold_keys=p.get("hold_keys", ()),
            face_reverse=p.get("face_reverse", False))
        if self._minimap_face is not None:
            mover.face_reverse = self._minimap_face   # 同一次執行已經試出正確轉身方向
        if self._minimap_slide is not None:
            mover.slide = self._minimap_slide   # 同一次執行沿用（騎乘等速度差異）
        tx, ty = p["target"]
        deadline = self._action_time() + p["timeout_ms"] / 1000
        vertical = max(p["tolerance"], 2)
        if p["method"] == "rope":
            ok = mover.rope(tx, ty, p["tolerance"], vertical, p["jump_key"], deadline)
        elif p["method"] == "down_jump":
            ok = mover.down_jump(ty, vertical, p["jump_key"], deadline,
                                 quick=p.get("quick", False))
        elif p["method"] == "hold":
            ok = mover.hold_move(tx, p["tolerance"], deadline)
            for note in reasons:
                if "轉身" in note or "改用走的" in note:
                    logger.info("小地圖衝刺：%s", note)
            if ok:      # 成功衝到才記住這次的轉身方向（失敗時的換邊可能是誤判）
                self._minimap_face = mover.face_reverse
            if ok and mover.last is not None and abs(mover.last[1] - ty) > max(p["tolerance"], 6):
                ok = False
                reasons.append("X 已到但高度和目標不同，可能掉下平台或目標在另一層")
        else:
            ok = mover.walk(tx, p["tolerance"], deadline)
            self._minimap_slide = mover.slide
            # 走路只對齊 X；高度差太多代表掉下平台或目標在別層，不能算到達。
            if ok and mover.last is not None and abs(mover.last[1] - ty) > max(p["tolerance"], 5):
                ok = False
                reasons.append("X 已對齊但高度和目標不同，可能掉下平台或目標在另一層")
        where = (f"（目前 {mover.last[0]:.0f}, {mover.last[1]:.0f}）"
                 if mover.last is not None else "（找不到黃點）")
        if ok:
            logger.info("小地圖移動完成：目標 (%d, %d)%s", tx, ty, where)
            return None
        reason = reasons[-1] if reasons else (
            "找不到小地圖黃點" if mover.last is None else "逾時未到達")
        logger.warning("小地圖移動失敗：目標 (%d, %d)%s：%s", tx, ty, where, reason)
        if p["on_timeout"] == "continue":
            return None
        if p["on_timeout"] == "goto":
            return _Goto(p["goto_index"])
        raise _PlayerAbort(f"小地圖移動失敗：目標 ({tx}, {ty}){where}：{reason}")

    def _minimap_reader(self, win: WindowInfo, region):
        from keyboard_executor.core.minimap import find_player_dot

        def read():
            try:
                rect, rx, ry, scale, _ = self._region_rect(win, region)
                image = self._require_capture().capture(rect)
            except _PlayerAbort:
                raise
            except Exception as e:
                logger.warning("小地圖擷取失敗，已跳過本次讀取：%s", e)
                return None
            dot = find_player_dot(image, scale)
            return None if dot is None else (rx + dot[0] / scale, ry + dot[1] / scale)
        return read

    def _run_minimap_goto(self, action: Action, win: WindowInfo) -> _Goto | None:
        """等黃點停穩（例如被撞下平台還在掉落），依所在區域跳到對應動作。
        quick：不等停穩直接看目前位置（站在手扶梯上時黃點一直動，等停下就到上層了）。"""
        from keyboard_executor.core.minimap import MinimapMover

        p = action.params
        self._ensure_alive(win)
        self._sequence_checkpoint()

        def sleep(seconds):
            self._raw_sleep(seconds)
            self._check_stop()

        mover = MinimapMover(self._minimap_reader(win, p["region"]), lambda key: None,
                             lambda key: None, sleep, self._action_time)
        pos = mover.peek() if p.get("quick") else mover.settle(limit=3.0, after_input=False)
        if pos is not None:
            for branch in p["branches"]:
                x, y, w, h = branch["area"]
                if x <= pos[0] < x + w and y <= pos[1] < y + h:
                    logger.info("小地圖位置 (%.0f, %.0f) → 跳到動作 %d", *pos, branch["goto_index"])
                    return _Goto(branch["goto_index"])
        where = "找不到黃點" if pos is None else f"({pos[0]:.0f}, {pos[1]:.0f})"
        if p["otherwise"] == "goto":
            logger.info("小地圖位置 %s 不在任何區域 → 跳到動作 %d", where, p["otherwise_index"])
            return _Goto(p["otherwise_index"])
        if p["otherwise"] == "abort":
            raise _PlayerAbort(f"小地圖位置 {where} 不在任何已設定的區域，已停止")
        logger.info("小地圖位置 %s 不在任何區域，繼續下一步", where)
        return None

    def _delay_seconds(self, ms, settings) -> float:
        if isinstance(ms, list):
            base = float(self._rng.randint(ms[0], ms[1]))
        else:
            base = float(ms)
        if settings.humanize_jitter_pct:
            jitter = settings.humanize_jitter_pct
            base *= 1 + self._rng.uniform(-jitter, jitter) / 100
        return base / 1000 / settings.speed
