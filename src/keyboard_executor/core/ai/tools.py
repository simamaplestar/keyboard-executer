"""AI 工具（function calling）schema：單一來源，輸出雙供應商格式。"""
from __future__ import annotations

TOOL_NEW = "propose_new_script"
TOOL_EDIT = "propose_edit_current"
TOOL_RULE_NEW = "propose_new_rule"
TOOL_BUNDLE = "propose_automation_bundle"
TOOL_NAMES = (TOOL_NEW, TOOL_EDIT, TOOL_RULE_NEW, TOOL_BUNDLE)

_ACTIONS_SCHEMA = {
    "type": "array",
    "description": "動作清單；每個元素是 {\"type\": 動作類型, ...參數}，"
                   "類型與欄位見 system prompt 的動作說明。",
    "items": {"type": "object"},
}

_SCRIPT_SCHEMA = {
    "type": "object",
    "description": "完整腳本 JSON；欄位與動作格式見 system prompt。",
    "properties": {
        "name": {"type": "string"},
        "target_window": {"type": "object"},
        "settings": {"type": "object"},
        "actions": _ACTIONS_SCHEMA,
    },
    "required": ["name", "target_window", "actions"],
}

_RULE_SCHEMA = {
    "type": "object",
    "description": "完整監看規則 JSON；condition/triggers 格式見 system prompt。",
    "properties": {
        "name": {"type": "string"},
        "target_window": {"type": "object"},
        "region": {"type": ["array", "null"]},
        "condition": {"type": "object"},
        "triggers": {"type": "array", "items": {"type": "object"}},
        "interval_sec": {"type": "number"},
        "cooldown_sec": {"type": "number"},
        "enabled": {"type": "boolean"},
        "attach_screenshot": {"type": "boolean"},
    },
    "required": ["name", "target_window", "condition", "triggers"],
}

_TOOLS = [
    {
        "name": TOOL_NEW,
        "description": "提案建立一個新腳本。使用者會先預覽、按「套用」才會儲存。",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "腳本名稱（不含 / 與 \\）"},
                "target_title_regex": {"type": "string",
                                       "description": "目標視窗標題的 regex"},
                "actions": _ACTIONS_SCHEMA,
            },
            "required": ["name", "target_title_regex", "actions"],
        },
    },
    {
        "name": TOOL_EDIT,
        "description": "提案修改目前選中的腳本：以 actions 整份取代其動作清單。"
                       "使用者會先預覽、按「套用」才會儲存。",
        "schema": {
            "type": "object",
            "properties": {"actions": _ACTIONS_SCHEMA},
            "required": ["actions"],
        },
    },
    {
        "name": TOOL_RULE_NEW,
        "description": "提案建立一條新監看規則。使用者會先預覽、按套用才會儲存。",
        "schema": {
            "type": "object",
            "properties": {"rule": _RULE_SCHEMA},
            "required": ["rule"],
        },
    },
    {
        "name": TOOL_BUNDLE,
        "description": "一次提案建立互相配合的多個腳本與監看規則；"
                       "規則可用 run_script 觸發同一提案中的腳本。",
        "schema": {
            "type": "object",
            "properties": {
                "scripts": {"type": "array", "items": _SCRIPT_SCHEMA},
                "rules": {"type": "array", "items": _RULE_SCHEMA},
            },
            "required": ["scripts", "rules"],
        },
    },
]


def as_anthropic() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["schema"]} for t in _TOOLS]


def as_openai() -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["schema"]}} for t in _TOOLS]


# ---------- AI 示範錄製專用（不放進 _TOOLS，一般聊天不提供） ----------
TOOL_DEMO = "propose_demo_scripts"

_DEMO_TOOL = {
    "name": TOOL_DEMO,
    "description": "依使用者的示範（或試跑結果）提出練功腳本與回起點腳本。"
                   "程式會直接存檔並在遊戲裡試跑。",
    "schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "一句話描述示範的目的"},
            "verdict": {"type": "string", "enum": ["success", "needs_fix"],
                        "description": "試跑判定；第一次產生腳本時省略"},
            "changes": {"type": "string", "description": "這一輪改了什麼（給使用者看）"},
            "main_script": _SCRIPT_SCHEMA,
            "return_script": _SCRIPT_SCHEMA,
            "templates": {
                "type": "array",
                "description": "從截圖裁切成模板圖；rect 是送出圖片上的像素座標",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "frame": {"type": "string", "description": "截圖編號，例如 D3"},
                        "rect": {"type": "array", "items": {"type": "integer"},
                                 "description": "[x, y, w, h]"},
                    },
                    "required": ["name", "frame", "rect"],
                },
            },
        },
        "required": ["goal"],
    },
}


def demo_tools_anthropic() -> list[dict]:
    t = _DEMO_TOOL
    return [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]}]


def demo_tools_openai() -> list[dict]:
    t = _DEMO_TOOL
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["schema"]}}]
