"""AI 提案 → Script。安全網：一律走既有 script_from_dict 全套驗證，
不支援的動作類型、缺欄位、型別錯誤全數 ScriptValidationError（繁中）。"""
from __future__ import annotations

from keyboard_executor.core.models import (
    Rule,
    Script,
    ScriptValidationError,
    rule_from_dict,
    script_from_dict,
    script_to_dict,
)


def script_from_proposal(name: str, target_title_regex: str,
                         actions: list) -> Script:
    """propose_new_script 的 args → Script（settings 用預設值）。"""
    return script_from_dict({
        "name": name,
        "target_window": {"title_pattern": target_title_regex},
        "actions": actions,
    })


def actions_for_edit(current: Script, actions: list) -> Script:
    """propose_edit_current：保留 current 的 name/target/settings，只換 actions。"""
    data = script_to_dict(current)
    data["actions"] = actions
    return script_from_dict(data)


def rule_from_proposal(data: dict) -> Rule:
    """新規則提案一律走既有 rule_from_dict 全套驗證。"""
    return rule_from_dict(data)


def automation_bundle_from_proposal(scripts, rules) -> tuple[list[Script], list[Rule]]:
    """驗證「腳本＋規則」套組；全部合法才回傳，避免半套提案。"""
    if not isinstance(scripts, list) or not isinstance(rules, list):
        raise ScriptValidationError("自動化套組的 scripts 與 rules 必須是清單")
    if not scripts and not rules:
        raise ScriptValidationError("自動化套組至少要有一個腳本或規則")
    validated_scripts = [script_from_dict(item) for item in scripts]
    validated_rules = [rule_from_dict(item) for item in rules]
    script_names = [item.name for item in validated_scripts]
    rule_names = [item.name for item in validated_rules]
    if len(set(script_names)) != len(script_names):
        raise ScriptValidationError("自動化套組內的腳本名稱不可重複")
    if len(set(rule_names)) != len(rule_names):
        raise ScriptValidationError("自動化套組內的規則名稱不可重複")
    return validated_scripts, validated_rules
