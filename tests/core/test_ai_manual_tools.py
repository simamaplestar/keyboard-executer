"""manual/tools：system prompt 內容與雙供應商工具格式。"""
from keyboard_executor.core.ai.manual import build_system_prompt
from keyboard_executor.core.ai.tools import (
    TOOL_BUNDLE,
    TOOL_EDIT,
    TOOL_NEW,
    TOOL_RULE_NEW,
    as_anthropic,
    as_openai,
)


def test_system_prompt_contains_manual_and_boundary():
    p = build_system_prompt(None)
    for needle in ("key_combo", "wait_text", "loop", "監看規則",
                   "propose_automation_bundle", "圖片理解",
                   "反偵測", "驗證碼", "婉拒"):
        assert needle in p
    assert "目前沒有選中的腳本" in p


def test_system_prompt_embeds_current_script_json():
    p = build_system_prompt('{"name": "打怪"}')
    assert '{"name": "打怪"}' in p and "目前選中的腳本" in p


def test_anthropic_tools_shape():
    tools = as_anthropic()
    names = {t["name"] for t in tools}
    assert names == {TOOL_NEW, TOOL_EDIT, TOOL_RULE_NEW, TOOL_BUNDLE}
    for t in tools:
        assert set(t) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
    new = next(t for t in tools if t["name"] == TOOL_NEW)
    assert set(new["input_schema"]["required"]) == {"name", "target_title_regex", "actions"}
    bundle = next(t for t in tools if t["name"] == TOOL_BUNDLE)
    assert bundle["input_schema"]["required"] == ["scripts", "rules"]


def test_openai_tools_shape():
    tools = as_openai()
    for t in tools:
        assert t["type"] == "function"
        assert set(t["function"]) == {"name", "description", "parameters"}
    edit = next(t for t in tools if t["function"]["name"] == TOOL_EDIT)
    assert edit["function"]["parameters"]["required"] == ["actions"]


def test_manual_documents_every_action_type():
    from keyboard_executor.core.models import ActionType
    p = build_system_prompt(None)
    missing = [t.value for t in ActionType if t.value not in p]
    assert missing == []     # 新增動作類型時要同步寫進 AI 手冊


def test_manual_tells_assistant_to_ask_before_guessing():
    p = build_system_prompt(None)
    for needle in ("先反問", "目標視窗", "攻擊", "小地圖", "goto_index", "從 0 起算", "name"):
        assert needle in p
