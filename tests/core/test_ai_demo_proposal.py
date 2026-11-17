import pytest

from keyboard_executor.core.ai.tools import (
    TOOL_DEMO, TOOL_NAMES, as_anthropic, demo_tools_anthropic, demo_tools_openai,
)
from keyboard_executor.core.ai_demo.proposal import (
    DemoProposalError, TemplateCrop, parse_demo_proposal,
)

SIZES = {"D1": (1280, 720), "D2": (1280, 720)}


def script(name="練功", actions=None):
    return {"name": name, "target_window": {"title_pattern": "MapleStory"},
            "actions": actions or [{"type": "key_press", "key": "x"}]}


def args(**kw):
    base = {"goal": "左右打怪", "changes": "", "main_script": script(),
            "return_script": script("回起點"), "templates": []}
    base.update(kw)
    return base


def test_valid_first_proposal():
    p = parse_demo_proposal(args(templates=[{"name": "怪", "frame": "D1",
                                             "rect": [10, 20, 30, 40]}]),
                            sent_sizes=SIZES, require_main=True, require_return=True)
    assert p.goal == "左右打怪"
    assert p.main_script.name == "練功"
    assert p.return_script.name == "回起點"
    assert p.templates == (TemplateCrop("怪", "D1", (10, 20, 30, 40)),)
    assert p.verdict is None


def test_missing_return_on_first_raises():
    with pytest.raises(DemoProposalError, match="回起點"):
        parse_demo_proposal(args(return_script=None), sent_sizes=SIZES,
                            require_main=True, require_return=True)


def test_return_optional_on_fix():
    p = parse_demo_proposal(args(return_script=None, verdict="needs_fix"),
                            sent_sizes=SIZES, require_main=True, require_return=False)
    assert p.return_script is None
    assert p.verdict == "needs_fix"


def test_success_verdict_without_main_ok():
    p = parse_demo_proposal({"goal": "g", "verdict": "success"}, sent_sizes=SIZES,
                            require_main=True, require_return=False)
    assert p.verdict == "success"
    assert p.main_script is None


def test_needs_fix_without_main_raises():
    with pytest.raises(DemoProposalError, match="主腳本"):
        parse_demo_proposal({"goal": "g", "verdict": "needs_fix"}, sent_sizes=SIZES,
                            require_main=True, require_return=False)


def test_bad_verdict_raises():
    with pytest.raises(DemoProposalError, match="verdict"):
        parse_demo_proposal(args(verdict="maybe"), sent_sizes=SIZES,
                            require_main=True, require_return=True)


def test_template_out_of_bounds_raises():
    with pytest.raises(DemoProposalError, match="超出"):
        parse_demo_proposal(args(templates=[{"name": "怪", "frame": "D1",
                                             "rect": [1270, 0, 20, 20]}]),
                            sent_sizes=SIZES, require_main=True, require_return=True)


def test_template_too_small_raises():
    with pytest.raises(DemoProposalError, match="8"):
        parse_demo_proposal(args(templates=[{"name": "怪", "frame": "D1",
                                             "rect": [0, 0, 7, 20]}]),
                            sent_sizes=SIZES, require_main=True, require_return=True)


def test_unknown_frame_raises():
    with pytest.raises(DemoProposalError, match="D9"):
        parse_demo_proposal(args(templates=[{"name": "怪", "frame": "D9",
                                             "rect": [0, 0, 20, 20]}]),
                            sent_sizes=SIZES, require_main=True, require_return=True)


def test_duplicate_or_bad_template_name_raises():
    crop = {"name": "怪", "frame": "D1", "rect": [0, 0, 20, 20]}
    with pytest.raises(DemoProposalError, match="重複"):
        parse_demo_proposal(args(templates=[crop, crop]), sent_sizes=SIZES,
                            require_main=True, require_return=True)
    with pytest.raises(DemoProposalError, match="名稱"):
        parse_demo_proposal(args(templates=[dict(crop, name="a/b")]), sent_sizes=SIZES,
                            require_main=True, require_return=True)


def test_invalid_action_type_raises():
    with pytest.raises(DemoProposalError):
        parse_demo_proposal(args(main_script=script(actions=[{"type": "fly"}])),
                            sent_sizes=SIZES, require_main=True, require_return=True)


def test_demo_tool_not_in_general_tools():
    assert TOOL_DEMO not in TOOL_NAMES
    assert TOOL_DEMO not in [t["name"] for t in as_anthropic()]
    assert [t["name"] for t in demo_tools_anthropic()] == [TOOL_DEMO]
    assert [t["function"]["name"] for t in demo_tools_openai()] == [TOOL_DEMO]
    schema = demo_tools_anthropic()[0]["input_schema"]
    assert schema["required"] == ["goal"]
    assert schema["properties"]["verdict"]["enum"] == ["success", "needs_fix"]


def test_subscription_marker_accepts_demo_tool():
    """訂閱登入（Claude CLI / Codex）走文字標記；示範工具必須能被解析。"""
    import json
    from keyboard_executor.core.ai.subscription_protocol import (
        TOOL_MARKER_CLOSE, TOOL_MARKER_OPEN, parse_subscription_output,
    )
    payload = json.dumps({"name": TOOL_DEMO, "args": {"goal": "打怪"}}, ensure_ascii=False)
    result = parse_subscription_output("好的" + TOOL_MARKER_OPEN + payload + TOOL_MARKER_CLOSE)
    assert result.tool_call.name == TOOL_DEMO
    assert result.tool_call.args == {"goal": "打怪"}
