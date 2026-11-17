"""規則編輯模型（純 Python，無 Qt import）。

欄位皆為「表單友善」型（字串/布林），to_rule() 組 dict 後交 rule_from_dict
權威驗證——Task 1 label 化後的「規則 …」繁中訊息可原樣顯示在 GUI。"""
from __future__ import annotations

from keyboard_executor.app.action_fields import parse_int_list
from keyboard_executor.core.models import Rule, ScriptValidationError, rule_from_dict


def _parse_number(name: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ScriptValidationError(f"規則欄位 {name} 必須是數字: {raw!r}") from None


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ScriptValidationError(f"規則欄位 {name} 必須是整數: {raw!r}") from None


class RuleEditorModel:
    def __init__(self):
        # 載入既有規則時記住原始名稱，改名存檔才能刪掉舊名那條（避免變成新增一條）。
        # 新規則為 None。
        self.original_name = None
        self.name = ""
        self.title_pattern = ""
        self.app_name = ""
        self.region_text = ""            # "x, y, w, h"；留空＝整個視窗
        self.condition_type = "text"     # "text" | "image" | "color"
        self.pattern = ""
        self.mode = "contains"
        self.template = ""
        self.threshold = "0.85"
        self.hue = "0"
        self.sat = "0"
        self.val = "0"
        self.hue_tol = "10"
        self.min_pixels = "3"
        self.absent = False
        self.interval_sec = "5"
        self.cooldown_sec = "60"
        self.notify_enabled = True       # 新規則預設「顯示通知」
        self.stop_all_enabled = False
        self.run_script_enabled = False
        self.script_name = ""
        self.message = ""
        self.attach_screenshot = False
        self.enabled = True

    @classmethod
    def from_rule(cls, rule: Rule) -> "RuleEditorModel":
        model = cls()
        model.original_name = rule.name   # 記住原始名稱以支援改名（見 __init__）
        model.name = rule.name
        model.title_pattern = rule.target_window.title_pattern or ""
        model.app_name = rule.target_window.app_name or ""
        model.region_text = (", ".join(str(v) for v in rule.region)
                             if rule.region is not None else "")
        model.condition_type = rule.condition.type
        model.pattern = rule.condition.pattern or ""
        model.mode = rule.condition.mode
        model.template = rule.condition.template or ""
        model.threshold = str(rule.condition.threshold)
        if rule.condition.type == "color":
            model.hue = str(rule.condition.hue)
            model.sat = str(rule.condition.sat)
            model.val = str(rule.condition.val)
            model.hue_tol = str(rule.condition.hue_tol)
            model.min_pixels = str(rule.condition.min_pixels)
        model.interval_sec = str(rule.interval_sec)
        model.cooldown_sec = str(rule.cooldown_sec)
        model.notify_enabled = any(t.type == "notify" for t in rule.triggers)
        model.stop_all_enabled = any(t.type == "stop_all" for t in rule.triggers)
        model.run_script_enabled = any(t.type == "run_script" for t in rule.triggers)
        for t in rule.triggers:
            if t.type == "notify":
                model.message = t.message or ""
            elif t.type == "run_script":
                model.script_name = t.script_name or ""
        model.attach_screenshot = rule.attach_screenshot
        model.absent = rule.condition.absent
        model.enabled = rule.enabled
        return model

    def to_dict(self) -> dict:
        data: dict = {"name": self.name.strip(), "target_window": {},
                      "enabled": self.enabled}
        if self.title_pattern.strip():
            data["target_window"]["title_pattern"] = self.title_pattern.strip()
        if self.app_name.strip():
            data["target_window"]["app_name"] = self.app_name.strip()
        if self.region_text.strip():
            data["region"] = parse_int_list("region", self.region_text, 4)
        if self.condition_type == "text":
            data["condition"] = {"type": "text", "pattern": self.pattern,
                                 "mode": self.mode, "absent": self.absent}
        elif self.condition_type == "image":
            data["condition"] = {"type": "image", "template": self.template,
                                 "threshold": _parse_number("threshold",
                                                            self.threshold),
                                 "absent": self.absent}
        else:  # color
            data["condition"] = {
                "type": "color",
                "hue": _parse_int("hue", self.hue),
                "sat": _parse_int("sat", self.sat),
                "val": _parse_int("val", self.val),
                "hue_tol": _parse_int("hue_tol", self.hue_tol),
                "min_pixels": _parse_int("min_pixels", self.min_pixels),
                "absent": self.absent}
        data["interval_sec"] = _parse_number("interval_sec", self.interval_sec)
        data["cooldown_sec"] = _parse_number("cooldown_sec", self.cooldown_sec)
        triggers = []
        if self.notify_enabled:
            triggers.append({"type": "notify", "message": self.message})
        if self.run_script_enabled:
            triggers.append({"type": "run_script", "script_name": self.script_name})
        if self.stop_all_enabled:
            triggers.append({"type": "stop_all"})
        data["triggers"] = triggers      # 空清單 → rule_from_dict 拒絕（存檔會顯示錯誤）
        data["attach_screenshot"] = self.attach_screenshot
        return data

    def to_rule(self) -> Rule:
        return rule_from_dict(self.to_dict())
