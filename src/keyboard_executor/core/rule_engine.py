"""監看規則引擎：定時擷取畫面、比對規則條件、命中且不在冷卻期時觸發（spec §8）。

各規則以自身 interval_sec 輪詢；命中觸發 run_script / stop_all / notify。
擷取/OCR/比對例外「記錄並跳過該輪」（spec §10）：單一規則的例外不影響同一輪
其他規則的評估（per-rule isolation），錯誤經 logging 記錄（繁中；GUI 日誌面板
與滾動日誌檔皆可見），不吃掉不留痕跡。
外部依賴全注入，預設真實。
"""
from __future__ import annotations

import logging
import threading
import time

from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.models import Rule, RuleTrigger
from keyboard_executor.core.player import Player
from keyboard_executor.core.vision import count_color_pixels, encode_png, find_text, match_template

logger = logging.getLogger(__name__)


class RuleEngine:
    _FAIL_NOTIFY_STREAK = 3   # 同一規則連續失敗達此次數時以 notifier 通知（spec §10）

    def __init__(self, platform, storage, notifier=None, templates=None,
                 player_factory=Player, stop_event=None, sleep=None,
                 clock=time.monotonic, on_fire=None, on_error=None,
                 on_stop_all=None, on_fire_done=None):
        self._platform = platform
        self._storage = storage
        self._notifier = notifier
        self._templates = templates
        self._player_factory = player_factory
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep if sleep is not None else self.stop_event.wait
        self._clock = clock
        self._on_fire = on_fire
        self._on_error = on_error
        self._on_stop_all = on_stop_all   # 停監看之外，另停其他自動化（執行中的腳本）
        self._on_fire_done = on_fire_done  # 觸發的動作全部做完（AI 示範試跑據此等待）
        self._fail_streak: dict[str, int] = {}
        self._next_due: dict[str, float] = {}
        self._last_fired: dict[str, float] = {}
        self._last_status: dict[str, tuple[str, float]] = {}

    def run(self, rules) -> None:
        """輪詢迴圈，直到 stop_event。以 sleep 讓步（預設 stop_event.wait 可中斷）。"""
        logger.info("開始監看規則: %s", ", ".join(r.name for r in rules if r.enabled))
        try:
            while not self.stop_event.is_set():
                self.evaluate_once(rules)
                self._sleep(0.1)
        finally:
            logger.info("規則監看已停止")

    def _report_status(self, rule, status, message, *args):
        """Persist initial/changed state and a 30 s heartbeat without per-tick spam."""
        now = self._clock()
        previous = self._last_status.get(rule.name)
        if previous is None or previous[0] != status or now - previous[1] >= 30:
            self._last_status[rule.name] = (status, now)
            logger.info("規則 %r: " + message, rule.name, *args)

    def evaluate_once(self, rules) -> None:
        for rule in rules:
            if not rule.enabled:
                continue
            now = self._clock()   # 每條規則各自取時：前一條的慢比對（OCR）已耗掉數秒
            if now < self._next_due.get(rule.name, 0.0):
                continue
            try:
                matched, image = self._matches(rule)
                self._fail_streak[rule.name] = 0
            except Exception as e:
                # 擷取/OCR/比對失敗：記錄並跳過該輪（spec §10），不影響其他規則
                matched, image = False, None
                self._log_failure(rule, e)
                self._record_failure(rule)
            # 下次輪詢以「本輪比對完成後」為基準：文字條件的 OCR 可能比 interval 還久
            # （實測 902×540 約 2.3s），若以開始時間計算會使規則立刻過期、OCR 背靠背
            # 連跑吃滿 CPU。改以完成時間 + interval，保證每次比對之間有真正的空檔。
            self._next_due[rule.name] = self._clock() + rule.interval_sec
            if not matched:
                continue
            last = self._last_fired.get(rule.name)
            if last is not None and now - last < rule.cooldown_sec:
                continue
            self._last_fired[rule.name] = now
            try:
                self._fire(rule, image)
            except Exception as e:
                # 觸發（_fire）例外必須與 _matches 一樣被隔離：run_script 載入失敗、
                # notifier 拋錯等都不可讓 evaluate_once 崩潰、拖垮同一輪其他規則
                # 或整個 watch 迴圈（run_watch 只接 KeyboardInterrupt）。
                self._log_fire_failure(rule, e)

    def _log_failure(self, rule: Rule, error: Exception) -> None:
        logger.warning("規則 %r 本輪擷取或比對失敗，已跳過：%s", rule.name, error)
        self._emit_error(rule, f"本輪擷取或比對失敗，已跳過：{error}")

    def _log_fire_failure(self, rule: Rule, error: Exception) -> None:
        logger.error("規則 %r 觸發失敗，已跳過：%s", rule.name, error)
        self._emit_error(rule, f"觸發失敗，已跳過：{error}")

    def _emit_error(self, rule: Rule, message: str) -> None:
        if self._on_error is None:
            return
        try:
            self._on_error(rule.name, message)
        except Exception:
            pass  # GUI 回呼失敗不可拖垮監看

    def _record_failure(self, rule: Rule) -> None:
        streak = self._fail_streak.get(rule.name, 0) + 1
        self._fail_streak[rule.name] = streak
        if streak == self._FAIL_NOTIFY_STREAK and self._notifier is not None:
            try:
                self._notifier(f"規則「{rule.name}」已連續 {streak} 次擷取或比對失敗，"
                               "請檢查權限與目標視窗")
            except Exception:
                pass  # notifier 失敗不可拖垮監看

    def _matches(self, rule: Rule):
        wm = self._platform.window_manager
        windows = wm.find_windows(title_pattern=rule.target_window.title_pattern,
                                  app_name=rule.target_window.app_name)
        if not windows:
            self._report_status(rule, "window_missing", "找不到目標視窗 (標題=%r, 程序=%r)",
                                rule.target_window.title_pattern, rule.target_window.app_name)
            return False, None
        win = windows[0]
        cap = self._platform.screen_capture
        scale = cap.scale_factor()
        if rule.region is None:
            rx, ry, rw, rh = 0, 0, win.width, win.height
        else:
            rx, ry, rw, rh = rule.region
        rect = Rect(round((win.x + rx) * scale), round((win.y + ry) * scale),
                    round(rw * scale), round(rh * scale))
        image = cap.capture(rect)
        if rule.condition.type == "text":
            boxes = self._platform.ocr_engine.recognize(image)
            present = find_text(boxes, rule.condition.pattern,
                                rule.condition.mode) is not None
            return present != rule.condition.absent, image
        if rule.condition.type == "color":
            c = rule.condition
            count = count_color_pixels(image, c.hue, c.sat, c.val,
                                       c.hue_tol, c.sat_tol, c.val_tol)
            matched = count < c.min_pixels if c.absent else count >= c.min_pixels
            return matched, image
        template = self._templates(rule.condition.template)
        result = match_template(image, template, threshold=rule.condition.threshold)
        present = result.found
        self._report_status(
            rule, "image_present" if present else "image_absent",
            "模板 %r %s, 相似度 %.3f / 門檻 %.3f, 區域=%s, 視窗=%sx%s",
            rule.condition.template, "命中" if present else "未命中",
            result.confidence, rule.condition.threshold, (rx, ry, rw, rh), win.width, win.height)
        return present != rule.condition.absent, image

    def _fire(self, rule: Rule, image) -> None:
        logger.info("規則 %r 命中, 觸發 %s", rule.name, "+".join(t.type for t in rule.triggers))
        if self._on_fire is not None:
            self._on_fire(rule.name, "+".join(t.type for t in rule.triggers))
        try:
            for trig in rule.triggers:
                # 每個動作各自隔離：前面的動作失敗（如 run_script 載入失敗、notifier 拋錯）
                # 不可讓後面的動作漏做——尤其安全性的 stop_all 排在最後。逐一 try/except、
                # 記錄該動作失敗、續做下一個動作。
                try:
                    self._fire_one(rule, trig, image)
                except Exception as e:
                    self._log_fire_failure(rule, e)
        finally:
            if self._on_fire_done is not None:
                try:
                    self._on_fire_done(rule.name)
                except Exception as e:
                    logger.warning("規則 %r 完成回呼失敗：%s", rule.name, e)

    def _fire_one(self, rule: Rule, trig: RuleTrigger, image) -> None:
        if trig.type == "run_script":
            player = self._player_factory(self._platform, storage=self._storage,
                                          templates=self._templates)
            result = player.play(self._storage.load(trig.script_name))
            if not result.ok:
                # PlayResult 不可靜默丟棄（spec §10）：記錄規則、腳本與錯誤，
                # 同時經 on_error 進 GUI 日誌（M4 修正批次既定行為，logging 為 additive）。
                logger.error("規則 %r 觸發腳本 %r 中止：%s",
                             rule.name, trig.script_name, result.error)
                self._emit_error(rule, f"觸發腳本 {trig.script_name!r} 中止：{result.error}")
        elif trig.type == "stop_all":
            self.stop_event.set()
            if self._on_stop_all is not None:
                # 監看的 stop_event 只停監看迴圈與規則觸發的腳本；用「執行」按鈕獨立
                # 跑的腳本有自己的 stop_event，需經此回呼一併停掉（同緊急停止熱鍵）。
                self._on_stop_all()
        elif trig.type == "notify" and self._notifier is not None:
            png = None
            if rule.attach_screenshot and image is not None:
                try:
                    png = encode_png(image)
                except Exception as e:
                    logger.warning("規則 %r 截圖編碼失敗，改送純文字通知：%s", rule.name, e)
                    png = None
            if png is not None:
                self._notifier(trig.message, image_png=png)
            else:
                self._notifier(trig.message)
