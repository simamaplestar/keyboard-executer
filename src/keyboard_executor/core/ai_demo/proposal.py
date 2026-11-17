"""propose_demo_scripts 的參數 → 驗證過的提案。錯誤訊息為繁中，會原文回給 AI 重試。"""
from __future__ import annotations

from dataclasses import dataclass

from keyboard_executor.core.models import Script, ScriptValidationError, script_from_dict

_MIN_TEMPLATE_EDGE = 8
_VERDICTS = ("success", "needs_fix")


class DemoProposalError(ScriptValidationError):
    """AI 提案不合法。"""


@dataclass(frozen=True)
class TemplateCrop:
    name: str
    frame_id: str
    rect: tuple[int, int, int, int]       # 送出圖片上的像素座標


@dataclass(frozen=True)
class DemoProposal:
    goal: str
    verdict: str | None
    changes: str
    main_script: Script | None
    return_script: Script | None
    templates: tuple[TemplateCrop, ...]


def _script(data, label: str) -> Script:
    if not isinstance(data, dict):
        raise DemoProposalError(f"{label}必須是腳本 JSON 物件")
    try:
        return script_from_dict(data)
    except ScriptValidationError as exc:
        raise DemoProposalError(f"{label}不合法：{exc}") from exc


def _crop(item, sizes: dict[str, tuple[int, int]]) -> TemplateCrop:
    if not isinstance(item, dict):
        raise DemoProposalError("templates 的每一項必須是物件")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        raise DemoProposalError(f"模板名稱不合法：{name!r}")
    frame = item.get("frame")
    if frame not in sizes:
        raise DemoProposalError(f"模板「{name}」引用了不存在的截圖：{frame}")
    rect = item.get("rect")
    if (not isinstance(rect, list) or len(rect) != 4
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in rect)):
        raise DemoProposalError(f"模板「{name}」的 rect 必須是 4 個整數 [x, y, w, h]")
    x, y, w, h = rect
    if w < _MIN_TEMPLATE_EDGE or h < _MIN_TEMPLATE_EDGE:
        raise DemoProposalError(
            f"模板「{name}」太小：寬高至少 {_MIN_TEMPLATE_EDGE}px")
    fw, fh = sizes[frame]
    if x < 0 or y < 0 or x + w > fw or y + h > fh:
        raise DemoProposalError(
            f"模板「{name}」的範圍超出截圖 {frame}（{fw}×{fh}）")
    return TemplateCrop(name.strip(), frame, (x, y, w, h))


def parse_demo_proposal(args: dict, *, sent_sizes: dict[str, tuple[int, int]],
                        require_main: bool, require_return: bool) -> DemoProposal:
    if not isinstance(args, dict):
        raise DemoProposalError("提案參數必須是物件")
    goal = args.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise DemoProposalError("缺少 goal（示範目的）")
    verdict = args.get("verdict")
    if verdict is not None and verdict not in _VERDICTS:
        raise DemoProposalError(f"verdict 只能是 success 或 needs_fix：{verdict!r}")
    changes = args.get("changes") or ""
    if not isinstance(changes, str):
        raise DemoProposalError("changes 必須是文字")
    main_data = args.get("main_script")
    if main_data is None:
        if require_main and verdict != "success":
            raise DemoProposalError("缺少主腳本 main_script")
        main = None
    else:
        main = _script(main_data, "主腳本")
    return_data = args.get("return_script")
    if return_data is None:
        if require_return:
            raise DemoProposalError("缺少回起點腳本 return_script")
        ret = None
    else:
        ret = _script(return_data, "回起點腳本")
    raw_templates = args.get("templates") or []
    if not isinstance(raw_templates, list):
        raise DemoProposalError("templates 必須是清單")
    crops = tuple(_crop(item, sent_sizes) for item in raw_templates)
    names = [c.name for c in crops]
    if len(set(names)) != len(names):
        raise DemoProposalError("模板名稱不可重複")
    return DemoProposal(goal.strip(), verdict, changes.strip(), main, ret, crops)
