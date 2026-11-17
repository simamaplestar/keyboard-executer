"""腳本資料模型與驗證。

所有座標為「目標視窗左上角為原點」的相對座標（平台輸入座標單位，見 geometry.py）。
驗證採嚴格模式：未知動作類型、未知欄位、型別錯誤一律拋 ScriptValidationError，
訊息為繁體中文，供 CLI/GUI 直接顯示。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from keyboard_executor.core.keynames import is_valid_key
from keyboard_executor.core.sequence_input_config import (
    SequenceInputConfig, sequence_config_from_dict, sequence_config_to_dict,
)
from keyboard_executor.core.chat_reply_config import (
    ChatReplyConfig, chat_config_from_dict, chat_config_to_dict,
)


class ScriptValidationError(Exception):
    """腳本 JSON 結構不合法。"""


class ActionType(StrEnum):
    KEY_PRESS = "key_press"
    KEY_COMBO = "key_combo"
    TEXT_INPUT = "text_input"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_DRAG = "mouse_drag"
    SCROLL = "scroll"
    DELAY = "delay"
    LOOP = "loop"
    RUN_SCRIPT = "run_script"
    WAIT_TEXT = "wait_text"
    WAIT_IMAGE = "wait_image"
    IF_TEXT = "if_text"
    IF_IMAGE = "if_image"
    CLICK_TEXT = "click_text"
    CLICK_IMAGE = "click_image"
    MINIMAP_MOVE = "minimap_move"
    MINIMAP_GOTO = "minimap_goto"
    GOTO = "goto"


@dataclass(frozen=True)
class Action:
    type: ActionType
    params: dict[str, Any] = field(default_factory=dict)


_MOUSE_BUTTONS = {"left", "right", "middle"}


def _err(message: str) -> None:
    raise ScriptValidationError(message)


def _check_no_extra(params: dict, label: str, allowed: set[str]) -> None:
    extra = set(params) - allowed
    if extra:
        _err(f"{label} 不支援的欄位: {', '.join(sorted(extra))}")


def _get_int(params: dict, label: str, name: str, *, minimum: int | None = None,
             default: int | None = None, required: bool = True) -> int:
    if name not in params:
        if required:
            _err(f"{label} 缺少欄位 {name}")
        return default
    value = params[name]
    if not isinstance(value, int) or isinstance(value, bool):
        _err(f"{label} 欄位 {name} 型別錯誤：必須是整數")
    if minimum is not None and value < minimum:
        _err(f"{label} 欄位 {name} 必須 >= {minimum}")
    return value


def _get_str(params: dict, label: str, name: str) -> str:
    if name not in params:
        _err(f"{label} 缺少欄位 {name}")
    value = params[name]
    if not isinstance(value, str) or not value.strip():
        _err(f"{label} 欄位 {name} 型別錯誤：必須是非空字串")
    return value


def _get_button(params: dict, atype: str) -> str:
    button = params.get("button", "left")
    if button not in _MOUSE_BUTTONS:
        _err(f"動作 {atype} 欄位 button 必須是 left/right/middle")
    return button


def _get_point(params: dict, atype: str, name: str) -> list[int]:
    if name not in params:
        _err(f"動作 {atype} 缺少欄位 {name}")
    value = params[name]
    ok = (isinstance(value, (list, tuple)) and len(value) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in value))
    if not ok:
        _err(f"動作 {atype} 欄位 {name} 必須是兩個整數的座標 [x, y]")
    return [value[0], value[1]]


def _validate_key_press(p: dict) -> dict:
    _check_no_extra(p, "動作 key_press", {"key", "hold_ms"})
    key = _get_str(p, "動作 key_press", "key")
    if not is_valid_key(key):
        _err(f"動作 key_press 欄位 key 不是可用的按鍵名稱: {key!r}")
    return {"key": key,
            "hold_ms": _get_int(p, "動作 key_press", "hold_ms", minimum=0, default=0,
                                required=False)}


def _validate_key_combo(p: dict) -> dict:
    _check_no_extra(p, "動作 key_combo", {"keys", "hold_ms"})
    keys = p.get("keys")
    if not isinstance(keys, list) or not keys:
        _err("動作 key_combo 欄位 keys 必須是至少一個按鍵的清單")
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            _err("動作 key_combo 欄位 keys 型別錯誤：每個按鍵必須是非空字串")
        if not is_valid_key(k):
            _err(f"動作 key_combo 欄位 keys 不是可用的按鍵名稱: {k!r}")
    return {"keys": list(keys),
            "hold_ms": _get_int(p, "動作 key_combo", "hold_ms", minimum=0, default=0,
                                required=False)}


def _validate_text_input(p: dict) -> dict:
    _check_no_extra(p, "動作 text_input", {"text"})
    if "text" not in p:
        _err("動作 text_input 缺少欄位 text")
    if not isinstance(p["text"], str):
        _err("動作 text_input 欄位 text 型別錯誤：必須是字串")
    return {"text": p["text"]}


def _validate_mouse_move(p: dict) -> dict:
    _check_no_extra(p, "動作 mouse_move", {"x", "y"})
    return {"x": _get_int(p, "動作 mouse_move", "x"), "y": _get_int(p, "動作 mouse_move", "y")}


def _validate_mouse_click(p: dict) -> dict:
    _check_no_extra(p, "動作 mouse_click", {"x", "y", "button", "count"})
    return {"x": _get_int(p, "動作 mouse_click", "x"),
            "y": _get_int(p, "動作 mouse_click", "y"),
            "button": _get_button(p, "mouse_click"),
            "count": _get_int(p, "動作 mouse_click", "count", minimum=1, default=1,
                              required=False)}


def _validate_mouse_drag(p: dict) -> dict:
    _check_no_extra(p, "動作 mouse_drag", {"from", "to", "button"})
    return {"from": _get_point(p, "mouse_drag", "from"),
            "to": _get_point(p, "mouse_drag", "to"),
            "button": _get_button(p, "mouse_drag")}


def _validate_scroll(p: dict) -> dict:
    _check_no_extra(p, "動作 scroll", {"x", "y", "dx", "dy"})
    return {"x": _get_int(p, "動作 scroll", "x"), "y": _get_int(p, "動作 scroll", "y"),
            "dx": _get_int(p, "動作 scroll", "dx", default=0, required=False),
            "dy": _get_int(p, "動作 scroll", "dy", default=0, required=False)}


def _validate_delay(p: dict) -> dict:
    _check_no_extra(p, "動作 delay", {"ms"})
    if "ms" not in p:
        _err("動作 delay 缺少欄位 ms")
    ms = p["ms"]
    if isinstance(ms, int) and not isinstance(ms, bool):
        if ms < 0:
            _err("動作 delay 欄位 ms 必須 >= 0")
        return {"ms": ms}
    ok = (isinstance(ms, (list, tuple)) and len(ms) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in ms)
          and 0 <= ms[0] <= ms[1])
    if not ok:
        _err("動作 delay 欄位 ms 必須是 >=0 的整數，或 [min, max]（0 <= min <= max）")
    return {"ms": [ms[0], ms[1]]}


def _validate_loop(p: dict) -> dict:
    _check_no_extra(p, "動作 loop", {"count", "actions"})
    count = _get_int(p, "動作 loop", "count")
    if count != -1 and count < 1:
        _err("動作 loop 欄位 count 必須是 -1（無限）或 >= 1")
    actions = p.get("actions")
    if not isinstance(actions, list) or not actions:
        _err("動作 loop 欄位 actions 必須是至少一個動作的清單")
    return {"count": count, "actions": [action_from_dict(a) for a in actions]}


def _validate_run_script(p: dict) -> dict:
    _check_no_extra(p, "動作 run_script", {"script_name"})
    return {"script_name": _get_str(p, "動作 run_script", "script_name")}


_MODES = {"contains", "regex"}
_ON_TIMEOUT = {"abort", "continue", "goto"}


def _get_region(params: dict, label: str):
    """region：None（整個視窗）或 [x, y, w, h] 四整數（視窗相對，w/h > 0）。"""
    region = params.get("region")
    if region is None:
        return None
    ok = (isinstance(region, (list, tuple)) and len(region) == 4
          and all(isinstance(v, int) and not isinstance(v, bool) for v in region)
          and region[2] > 0 and region[3] > 0)
    if not ok:
        _err(f"{label} 欄位 region 必須是 null 或 [x, y, w, h] 四整數（w、h > 0）")
    return [region[0], region[1], region[2], region[3]]


def _get_mode(params: dict, label: str) -> str:
    mode = params.get("mode", "contains")
    if mode not in _MODES:
        _err(f"{label} 欄位 mode 必須是 contains 或 regex")
    return mode


def _get_threshold(params: dict, label: str) -> float:
    threshold = params.get("threshold", 0.85)
    if (not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
            or not 0 < threshold <= 1):
        _err(f"{label} 欄位 threshold 必須是 (0, 1] 的數字")
    return float(threshold)


def _get_int_in(params: dict, label: str, name: str, lo: int, hi: int,
                 default: int | None = None) -> int:
    if name not in params:
        if default is None:
            _err(f"{label} 缺少欄位 {name}")
        return default
    v = params[name]
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        _err(f"{label} 欄位 {name} 必須是 {lo}–{hi} 的整數")
    return v


def _get_bool(params: dict, label: str, name: str, default: bool = False) -> bool:
    v = params.get(name, default)
    if not isinstance(v, bool):
        _err(f"{label} 欄位 {name} 必須是布林值")
    return v


def _get_wait_common(p: dict, label: str) -> dict:
    """wait_* 共用：timeout_ms、on_timeout、goto_index。"""
    timeout_ms = _get_int(p, label, "timeout_ms", minimum=0, default=5000, required=False)
    on_timeout = p.get("on_timeout", "abort")
    if on_timeout not in _ON_TIMEOUT:
        _err(f"{label} 欄位 on_timeout 必須是 abort、continue 或 goto")
    if on_timeout == "goto":
        if "goto_index" not in p:
            _err(f"{label} on_timeout=goto 時必須提供 goto_index")
        goto_index = _get_int(p, label, "goto_index", minimum=0)
    else:
        if p.get("goto_index") is not None:
            _err(f"{label} 欄位 goto_index 只在 on_timeout=goto 時允許")
        goto_index = None
    return {"timeout_ms": timeout_ms, "on_timeout": on_timeout, "goto_index": goto_index}


def _validate_pattern_regex(atype: str, pattern: str, mode: str) -> None:
    """Minor #2：mode == regex 時，於驗證階段就地 re.compile 一次，仿照
    _validate_target_window 對 title_pattern 的既有作法：不合法 regex 應該在
    載入腳本當下就失敗，而不是等到 wait_/if_/click_ 動作真正執行時才報錯。"""
    if mode == "regex":
        try:
            re.compile(pattern)
        except re.error as e:
            _err(f"動作 {atype} 欄位 pattern 不是合法 regex: {e}")


def _get_then_else(p: dict, atype: str) -> dict:
    then = p.get("then")
    if not isinstance(then, list) or not then:
        _err(f"動作 {atype} 欄位 then 必須是至少一個動作的清單")
    els = p.get("else", [])
    if not isinstance(els, list):
        _err(f"動作 {atype} 欄位 else 必須是動作清單")
    return {"then": [action_from_dict(a) for a in then],
            "else": [action_from_dict(a) for a in els]}


def _validate_wait_text(p: dict) -> dict:
    _check_no_extra(p, "動作 wait_text",
                    {"region", "pattern", "mode", "timeout_ms", "on_timeout", "goto_index"})
    pattern = _get_str(p, "動作 wait_text", "pattern")
    mode = _get_mode(p, "動作 wait_text")
    _validate_pattern_regex("wait_text", pattern, mode)
    result = {"region": _get_region(p, "動作 wait_text"), "pattern": pattern, "mode": mode}
    result.update(_get_wait_common(p, "動作 wait_text"))
    return result


def _validate_wait_image(p: dict) -> dict:
    _check_no_extra(p, "動作 wait_image",
                    {"region", "template", "threshold", "timeout_ms", "on_timeout", "goto_index"})
    result = {"region": _get_region(p, "動作 wait_image"),
              "template": _get_str(p, "動作 wait_image", "template"),
              "threshold": _get_threshold(p, "動作 wait_image")}
    result.update(_get_wait_common(p, "動作 wait_image"))
    return result


def _validate_if_text(p: dict) -> dict:
    _check_no_extra(p, "動作 if_text", {"region", "pattern", "mode", "then", "else"})
    pattern = _get_str(p, "動作 if_text", "pattern")
    mode = _get_mode(p, "動作 if_text")
    _validate_pattern_regex("if_text", pattern, mode)
    result = {"region": _get_region(p, "動作 if_text"), "pattern": pattern, "mode": mode}
    result.update(_get_then_else(p, "if_text"))
    return result


def _validate_if_image(p: dict) -> dict:
    _check_no_extra(p, "動作 if_image",
                    {"region", "template", "threshold", "mirror", "then", "else"})
    result = {"region": _get_region(p, "動作 if_image"),
              "template": _get_str(p, "動作 if_image", "template"),
              "threshold": _get_threshold(p, "動作 if_image"),
              "mirror": _get_bool(p, "動作 if_image", "mirror")}
    result.update(_get_then_else(p, "if_image"))
    return result


def _validate_click_text(p: dict) -> dict:
    _check_no_extra(p, "動作 click_text", {"region", "pattern", "mode"})
    pattern = _get_str(p, "動作 click_text", "pattern")
    mode = _get_mode(p, "動作 click_text")
    _validate_pattern_regex("click_text", pattern, mode)
    return {"region": _get_region(p, "動作 click_text"), "pattern": pattern, "mode": mode}


def _validate_click_image(p: dict) -> dict:
    _check_no_extra(p, "動作 click_image", {"region", "template", "threshold"})
    return {"region": _get_region(p, "動作 click_image"),
            "template": _get_str(p, "動作 click_image", "template"),
            "threshold": _get_threshold(p, "動作 click_image")}


_MINIMAP_METHODS = {"walk", "rope", "down_jump", "hold"}


def _validate_minimap_move(p: dict) -> dict:
    label = "動作 minimap_move"
    _check_no_extra(p, label, {"region", "target", "method", "tolerance", "jump_key",
                               "path_key", "path_template", "path_region", "path_threshold",
                               "path_step", "hold_keys", "face_reverse", "quick",
                               "timeout_ms", "on_timeout", "goto_index"})
    region = _get_region(p, label)
    if region is None:
        _err(f"{label} 缺少欄位 region（小地圖範圍）")
    target = _get_point(p, "minimap_move", "target")
    x, y, w, h = region
    if not (x <= target[0] < x + w and y <= target[1] < y + h):
        _err(f"{label} 欄位 target 必須在小地圖範圍內")
    method = p.get("method", "walk")
    if method not in _MINIMAP_METHODS:
        _err(f"{label} 欄位 method 必須是 walk、rope、down_jump 或 hold")
    jump_key = p.get("jump_key", "space")
    if not isinstance(jump_key, str) or not is_valid_key(jump_key):
        _err(f"{label} 欄位 jump_key 不是可用的按鍵名稱: {jump_key!r}")
    path_key = p.get("path_key")
    if path_key is not None and (not isinstance(path_key, str) or not is_valid_key(path_key)
                                 or path_key.strip().lower() in {"up", "down", "left", "right"}):
        _err(f"{label} 欄位 path_key 必須是方向鍵以外的可用按鍵: {path_key!r}")
    path_template = p.get("path_template")
    path_region = None
    if path_template is not None:
        path_template = _get_str(p, label, "path_template")
        if path_key is None:
            _err(f"{label} 設定 path_template 時必須同時設定 path_key（看到怪物要按的鍵）")
        raw = p.get("path_region")
        if raw is None:
            _err(f"{label} 設定 path_template 時必須提供 path_region（偵測範圍）")
        path_region = _get_region({"region": raw}, f"{label} path_region")
    elif p.get("path_region") is not None:
        _err(f"{label} 欄位 path_region 只在設定 path_template 時使用")
    path_threshold = _get_threshold({"threshold": p.get("path_threshold", .62)},
                                    f"{label} path_threshold")
    hold_keys = p.get("hold_keys", [])
    if not isinstance(hold_keys, list) or any(
            not isinstance(k, str) or not is_valid_key(k)
            or k.strip().lower() in {"up", "down", "left", "right"} for k in hold_keys):
        _err(f"{label} 欄位 hold_keys 必須是方向鍵以外的可用按鍵清單: {hold_keys!r}")
    if hold_keys and method not in ("walk", "hold"):
        _err(f"{label} 欄位 hold_keys 只在走路（walk）或按住攻擊鍵移動（hold）時使用")
    face_reverse = p.get("face_reverse", False)
    if not isinstance(face_reverse, bool):
        _err(f"{label} 欄位 face_reverse 必須是布林值")
    if method == "hold" and not hold_keys:
        _err(f"{label} 按住攻擊鍵移動（hold）必須設定 hold_keys，例如 [\"c\"]")
    quick = _get_quick(p, label)
    if quick and method != "down_jump":
        _err(f"{label} 欄位 quick（立即下跳）只在下跳（down_jump）時使用")
    common = dict(p)
    common.setdefault("timeout_ms", 15000)
    result = {"region": region, "target": target, "method": method,
              "tolerance": _get_int_in(p, label, "tolerance", 0, 40, default=1),
              "jump_key": jump_key, "path_key": path_key, "path_template": path_template,
              "path_region": path_region, "path_threshold": path_threshold,
              "path_step": _get_int_in(p, label, "path_step", 1, 100, default=5),
              "hold_keys": list(hold_keys), "face_reverse": face_reverse}
    if quick:
        result["quick"] = True
    result.update(_get_wait_common(common, label))
    return result


def _get_quick(p: dict, label: str) -> bool:
    """quick：不等黃點停下就判斷（手扶梯、移動平台上用）。預設 False，存檔時省略。"""
    quick = p.get("quick", False)
    if not isinstance(quick, bool):
        _err(f"{label} 欄位 quick 必須是布林值")
    return quick


def _validate_minimap_goto(p: dict) -> dict:
    label = "動作 minimap_goto"
    _check_no_extra(p, label, {"region", "branches", "otherwise", "otherwise_index", "quick"})
    region = _get_region(p, label)
    if region is None:
        _err(f"{label} 缺少欄位 region（小地圖範圍）")
    branches = p.get("branches")
    if not isinstance(branches, list) or not branches:
        _err(f"{label} 欄位 branches 必須是至少一個 {{area, goto_index}} 的清單")
    parsed = []
    for i, branch in enumerate(branches):
        if not isinstance(branch, dict) or set(branch) != {"area", "goto_index"}:
            _err(f"{label} branches[{i}] 必須只有 area 與 goto_index")
        area = _get_region({"region": branch["area"]}, f"{label} branches[{i}].area")
        if area is None:
            _err(f"{label} branches[{i}].area 必須是 [x, y, w, h]")
        parsed.append({"area": area,
                       "goto_index": _get_int(branch, f"{label} branches[{i}]", "goto_index",
                                              minimum=0)})
    otherwise = p.get("otherwise", "continue")
    if otherwise not in _ON_TIMEOUT:
        _err(f"{label} 欄位 otherwise 必須是 abort、continue 或 goto")
    otherwise_index = None
    if otherwise == "goto":
        if p.get("otherwise_index") is None:
            _err(f"{label} otherwise=goto 時必須提供 otherwise_index")
        otherwise_index = _get_int(p, label, "otherwise_index", minimum=0)
    elif p.get("otherwise_index") is not None:
        _err(f"{label} 欄位 otherwise_index 只在 otherwise=goto 時允許")
    result = {"region": region, "branches": parsed, "otherwise": otherwise,
              "otherwise_index": otherwise_index}
    if _get_quick(p, label):
        result["quick"] = True
    return result


def _validate_goto(p: dict) -> dict:
    label = "動作 goto"
    _check_no_extra(p, label, {"goto_index"})
    return {"goto_index": _get_int(p, label, "goto_index", minimum=0)}


_VALIDATORS = {
    ActionType.KEY_PRESS: _validate_key_press,
    ActionType.KEY_COMBO: _validate_key_combo,
    ActionType.TEXT_INPUT: _validate_text_input,
    ActionType.MOUSE_MOVE: _validate_mouse_move,
    ActionType.MOUSE_CLICK: _validate_mouse_click,
    ActionType.MOUSE_DRAG: _validate_mouse_drag,
    ActionType.SCROLL: _validate_scroll,
    ActionType.DELAY: _validate_delay,
    ActionType.LOOP: _validate_loop,
    ActionType.RUN_SCRIPT: _validate_run_script,
    ActionType.WAIT_TEXT: _validate_wait_text,
    ActionType.WAIT_IMAGE: _validate_wait_image,
    ActionType.IF_TEXT: _validate_if_text,
    ActionType.IF_IMAGE: _validate_if_image,
    ActionType.CLICK_TEXT: _validate_click_text,
    ActionType.CLICK_IMAGE: _validate_click_image,
    ActionType.MINIMAP_MOVE: _validate_minimap_move,
    ActionType.MINIMAP_GOTO: _validate_minimap_goto,
    ActionType.GOTO: _validate_goto,
}


def action_from_dict(data: Any) -> Action:
    if not isinstance(data, dict):
        _err("動作必須是 JSON 物件")
    raw_type = data.get("type")
    try:
        atype = ActionType(raw_type)
    except ValueError:
        _err(f"未知動作類型: {raw_type!r}")
    params = {k: v for k, v in data.items() if k not in ("type", "name")}
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        _err(f"動作 {atype} 欄位 name 型別錯誤：必須是字串")
    validated = _VALIDATORS[atype](params)
    name = (name or "").strip()
    # 名稱只供編輯器/紀錄辨認，不影響執行；空白＝不存，舊腳本序列化結果不變。
    return Action(type=atype, params={"name": name, **validated} if name else validated)


NESTED_ACTION_KEYS = ("actions", "then", "else")
_NESTED_ACTION_KEYS = NESTED_ACTION_KEYS   # 舊名保留；transfer 走訪巢狀動作時共用同一份


def action_to_dict(action: Action) -> dict:
    result: dict[str, Any] = {"type": str(action.type)}
    for key, value in action.params.items():
        if key in _NESTED_ACTION_KEYS:
            result[key] = [action_to_dict(a) for a in value]
        else:
            result[key] = value
    return result


@dataclass(frozen=True)
class TargetWindow:
    title_pattern: str | None = None
    app_name: str | None = None


@dataclass(frozen=True)
class TimedKey:
    """定時技能：每隔 interval_sec 秒按一次（在動作之間插入，不打斷正在做的動作）。"""
    key: str
    interval_sec: float
    hold_ms: int = 100
    wait_ms: int = 500          # 放完技能等動畫結束再繼續


def timed_key_from_dict(data: Any, index: int) -> TimedKey:
    label = f"settings.timed_keys[{index}]"
    if not isinstance(data, dict):
        _err(f"{label} 必須是 JSON 物件")
    _check_no_extra(data, label, {"key", "interval_sec", "hold_ms", "wait_ms"})
    key = data.get("key")
    if not isinstance(key, str) or not is_valid_key(key.strip().lower()):
        _err(f"{label}.key 不是可用的按鍵名稱: {key!r}")
    interval = data.get("interval_sec")
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval < 1:
        _err(f"{label}.interval_sec 必須是 >= 1 的秒數")
    hold = _get_int(data, label, "hold_ms", minimum=0, default=100, required=False)
    wait = _get_int(data, label, "wait_ms", minimum=0, default=500, required=False)
    return TimedKey(key=key.strip().lower(), interval_sec=float(interval), hold_ms=hold,
                    wait_ms=wait)


def timed_key_to_dict(item: TimedKey) -> dict:
    interval = int(item.interval_sec) if item.interval_sec == int(item.interval_sec) \
        else item.interval_sec
    return {"key": item.key, "interval_sec": interval, "hold_ms": item.hold_ms,
            "wait_ms": item.wait_ms}


def timed_keys_from_text(text: str) -> tuple[TimedKey, ...]:
    """「1:120, 2:180」→ 定時技能（按鍵:秒數，可再加 :按住毫秒）。"""
    result = []
    for i, part in enumerate(p.strip() for p in text.replace("，", ",").split(",")):
        if not part:
            continue
        fields = [f.strip() for f in part.replace("：", ":").split(":")]
        if len(fields) not in (2, 3):
            _err(f"定時技能「{part}」格式錯誤，請寫成 按鍵:秒數，例如 1:120")
        data = {"key": fields[0]}
        try:
            data["interval_sec"] = float(fields[1])
            if len(fields) == 3:
                data["hold_ms"] = int(fields[2])
        except ValueError:
            _err(f"定時技能「{part}」的秒數或按住毫秒必須是數字")
        result.append(timed_key_from_dict(data, i))
    return tuple(result)


def timed_keys_to_text(items) -> str:
    parts = []
    for item in items:
        seconds = f"{item.interval_sec:g}"
        parts.append(f"{item.key}:{seconds}" + (f":{item.hold_ms}" if item.hold_ms != 100 else ""))
    return ", ".join(parts)


@dataclass(frozen=True)
class ScriptSettings:
    speed: float = 1.0
    repeat: int = 1
    humanize_jitter_pct: int = 0
    game_input_mode: bool = True
    window_message_mode: bool = False
    scan_pulse_mode: bool = False
    window_retry: int = 0
    window_retry_interval_ms: int = 1000
    hotkey: str = ""
    chat_reply: ChatReplyConfig | None = None
    sequence_input: SequenceInputConfig | None = None
    timed_keys: tuple[TimedKey, ...] = ()


@dataclass(frozen=True)
class Script:
    name: str
    target_window: TargetWindow
    actions: tuple[Action, ...]
    settings: ScriptSettings = field(default_factory=ScriptSettings)


def _validate_target_window(data: Any) -> TargetWindow:
    if not isinstance(data, dict):
        _err("target_window 必須是 JSON 物件")
    _check_no_extra(data, "target_window", {"title_pattern", "app_name"})
    title = data.get("title_pattern")
    app = data.get("app_name")
    for name, value in (("title_pattern", title), ("app_name", app)):
        if value is not None and not isinstance(value, str):
            _err(f"target_window 欄位 {name} 型別錯誤：必須是字串")
    title = title if title and title.strip() else None
    app = app if app and app.strip() else None
    if title is None and app is None:
        _err("target_window 至少要提供 title_pattern 或 app_name 其中一個")
    if title:
        try:
            re.compile(title)
        except re.error as e:
            _err(f"target_window.title_pattern 不是合法 regex: {e}")
    return TargetWindow(title_pattern=title, app_name=app)


def _validate_settings(data: Any) -> ScriptSettings:
    if data is None:
        return ScriptSettings()
    if not isinstance(data, dict):
        _err("settings 必須是 JSON 物件")
    allowed = {"speed", "repeat", "humanize_jitter_pct", "game_input_mode",
               "window_message_mode", "scan_pulse_mode",
               "window_retry", "window_retry_interval_ms", "hotkey", "chat_reply", "sequence_input",
               "timed_keys"}
    _check_no_extra(data, "settings", allowed)
    defaults = ScriptSettings()
    speed = data.get("speed", defaults.speed)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
        _err("settings.speed 必須是 > 0 的數字")
    repeat = data.get("repeat", defaults.repeat)
    if not isinstance(repeat, int) or isinstance(repeat, bool) or (repeat != -1 and repeat < 1):
        _err("settings.repeat 必須是 -1（無限）或 >= 1 的整數")
    jitter = data.get("humanize_jitter_pct", defaults.humanize_jitter_pct)
    if not isinstance(jitter, int) or isinstance(jitter, bool) or not 0 <= jitter <= 100:
        _err("settings.humanize_jitter_pct 必須是 0–100 的整數")
    window_message = data.get("window_message_mode", defaults.window_message_mode)
    if not isinstance(window_message, bool):
        _err("settings.window_message_mode 必須是布林值")
    scan_pulse = data.get("scan_pulse_mode", defaults.scan_pulse_mode)
    if not isinstance(scan_pulse, bool):
        _err("settings.scan_pulse_mode 必須是布林值")
    # 手寫 JSON 只指定任一相容模式=true 時，自動關閉預設為 true 的 game mode；
    # 序列化仍寫出三個旗標。明確同時開啟多個模式則拒絕，避免語意不確定。
    non_game_mode = window_message or scan_pulse
    game_default = False if non_game_mode and "game_input_mode" not in data else defaults.game_input_mode
    game = data.get("game_input_mode", game_default)
    if not isinstance(game, bool):
        _err("settings.game_input_mode 必須是布林值")
    if sum((game, window_message, scan_pulse)) > 1:
        _err("settings 的鍵盤輸入模式不能同時啟用")
    retry = data.get("window_retry", defaults.window_retry)
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        _err("settings.window_retry 必須是 >= 0 的整數")
    interval = data.get("window_retry_interval_ms", defaults.window_retry_interval_ms)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 0:
        _err("settings.window_retry_interval_ms 必須是 >= 0 的整數")
    hotkey = data.get("hotkey", defaults.hotkey)
    if not isinstance(hotkey, str):
        _err("settings.hotkey 必須是字串")
    hotkey_parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    for part in hotkey_parts:
        if not is_valid_key(part):
            _err(f"settings.hotkey 不是可用的按鍵名稱: {part!r}")
    hotkey = "+".join(hotkey_parts)
    raw_timed = data.get("timed_keys", [])
    if not isinstance(raw_timed, list):
        _err("settings.timed_keys 必須是清單")
    timed = tuple(timed_key_from_dict(item, i) for i, item in enumerate(raw_timed))
    return ScriptSettings(timed_keys=timed, speed=float(speed), repeat=repeat, humanize_jitter_pct=jitter,
                          game_input_mode=game, window_message_mode=window_message,
                          scan_pulse_mode=scan_pulse,
                          window_retry=retry,
                          window_retry_interval_ms=interval, hotkey=hotkey,
                          sequence_input=(sequence_config_from_dict(data["sequence_input"])
                                          if data.get("sequence_input") is not None else None),
                          chat_reply=(chat_config_from_dict(data["chat_reply"])
                                      if data.get("chat_reply") is not None else None))


def script_from_dict(data: Any) -> Script:
    if not isinstance(data, dict):
        _err("腳本必須是 JSON 物件")
    _check_no_extra(data, "腳本", {"name", "target_window", "settings", "actions"})
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        _err("腳本欄位 name 必須是非空字串且不含路徑分隔字元")
    if "target_window" not in data:
        _err("腳本缺少欄位 target_window")
    target = _validate_target_window(data["target_window"])
    settings = _validate_settings(data.get("settings"))
    actions_raw = data.get("actions")
    if not isinstance(actions_raw, list) or not actions_raw:
        _err("腳本欄位 actions 必須是至少一個動作的清單")
    actions = tuple(action_from_dict(a) for a in actions_raw)
    return Script(name=name, target_window=target, actions=actions, settings=settings)


def script_to_dict(script: Script) -> dict:
    s = script.settings
    return {
        "name": script.name,
        "target_window": {"title_pattern": script.target_window.title_pattern,
                          "app_name": script.target_window.app_name},
        "settings": {"speed": s.speed, "repeat": s.repeat,
                     "humanize_jitter_pct": s.humanize_jitter_pct,
                     "game_input_mode": s.game_input_mode,
                     "window_message_mode": s.window_message_mode,
                     "scan_pulse_mode": s.scan_pulse_mode,
                     "window_retry": s.window_retry,
                     "window_retry_interval_ms": s.window_retry_interval_ms,
                     "hotkey": s.hotkey,
                     **({"sequence_input": sequence_config_to_dict(s.sequence_input)}
                        if s.sequence_input is not None else {}),
                     **({"chat_reply": chat_config_to_dict(s.chat_reply)}
                        if s.chat_reply is not None else {}),
                     **({"timed_keys": [timed_key_to_dict(t) for t in s.timed_keys]}
                        if s.timed_keys else {})},
        "actions": [action_to_dict(a) for a in script.actions],
    }


# Rule model and validation

@dataclass(frozen=True)
class RuleCondition:
    type: str                       # "text" | "image" | "color"
    pattern: str | None = None
    mode: str = "contains"
    template: str | None = None
    threshold: float = 0.85
    hue: int = 0
    sat: int = 0
    val: int = 0
    hue_tol: int = 10
    sat_tol: int = 80
    val_tol: int = 80
    min_pixels: int = 3
    absent: bool = False


@dataclass(frozen=True)
class RuleTrigger:
    type: str                       # "run_script" | "stop_all" | "notify"
    script_name: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Rule:
    name: str
    target_window: TargetWindow
    condition: RuleCondition
    triggers: tuple[RuleTrigger, ...]
    region: list[int] | None = None
    interval_sec: float = 5.0
    cooldown_sec: float = 60.0
    enabled: bool = True
    attach_screenshot: bool = False

    @property
    def trigger(self) -> RuleTrigger:
        """相容便利：回第一個觸發動作（單一動作規則等同舊 trigger）。"""
        return self.triggers[0]


def _get_positive_number(data: dict, name: str, default: float, *, allow_zero: bool) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _err(f"規則欄位 {name} 必須是數字: {value!r}")
    if allow_zero and value < 0:
        _err(f"規則欄位 {name} 必須 >= 0: {value!r}")
    if not allow_zero and value <= 0:
        _err(f"規則欄位 {name} 必須 > 0: {value!r}")
    return float(value)


def _validate_rule_condition(data: Any) -> RuleCondition:
    if not isinstance(data, dict) or "type" not in data:
        _err("規則 condition 必須是含 type 的 JSON 物件")
    ctype = data["type"]
    if ctype == "text":
        _check_no_extra(data, "規則 condition", {"type", "pattern", "mode", "absent"})
        return RuleCondition(type="text", pattern=_get_str(data, "規則 condition", "pattern"),
                             mode=_get_mode(data, "規則 condition"),
                             absent=_get_bool(data, "規則 condition", "absent"))
    if ctype == "image":
        _check_no_extra(data, "規則 condition", {"type", "template", "threshold", "absent"})
        return RuleCondition(type="image", template=_get_str(data, "規則 condition", "template"),
                             threshold=_get_threshold(data, "規則 condition"),
                             absent=_get_bool(data, "規則 condition", "absent"))
    if ctype == "color":
        _check_no_extra(data, "規則 condition",
                        {"type", "hue", "sat", "val", "hue_tol", "sat_tol",
                         "val_tol", "min_pixels", "absent"})
        return RuleCondition(
            type="color",
            hue=_get_int_in(data, "規則 condition", "hue", 0, 179),
            sat=_get_int_in(data, "規則 condition", "sat", 0, 255),
            val=_get_int_in(data, "規則 condition", "val", 0, 255),
            hue_tol=_get_int_in(data, "規則 condition", "hue_tol", 0, 90, default=10),
            sat_tol=_get_int_in(data, "規則 condition", "sat_tol", 0, 255, default=80),
            val_tol=_get_int_in(data, "規則 condition", "val_tol", 0, 255, default=80),
            min_pixels=_get_int_in(data, "規則 condition", "min_pixels", 1, 10_000_000, default=3),
            absent=_get_bool(data, "規則 condition", "absent"))
    _err(f"規則 condition.type 必須是 text、image 或 color: {ctype!r}")


def _validate_rule_trigger(data: Any) -> RuleTrigger:
    if not isinstance(data, dict) or "type" not in data:
        _err("規則 trigger 必須是含 type 的 JSON 物件")
    ttype = data["type"]
    if ttype == "run_script":
        _check_no_extra(data, "規則 trigger", {"type", "script_name"})
        return RuleTrigger(type="run_script",
                           script_name=_get_str(data, "規則 trigger", "script_name"))
    if ttype == "stop_all":
        _check_no_extra(data, "規則 trigger", {"type"})
        return RuleTrigger(type="stop_all")
    if ttype == "notify":
        _check_no_extra(data, "規則 trigger", {"type", "message"})
        return RuleTrigger(type="notify", message=_get_str(data, "規則 trigger", "message"))
    _err(f"規則 trigger.type 必須是 run_script、stop_all 或 notify: {ttype!r}")


def _trigger_to_dict(trig: RuleTrigger) -> dict:
    d: dict[str, Any] = {"type": trig.type}
    if trig.type == "run_script":
        d["script_name"] = trig.script_name
    elif trig.type == "notify":
        d["message"] = trig.message
    return d


def rule_from_dict(data: Any) -> Rule:
    if not isinstance(data, dict):
        _err("規則必須是 JSON 物件")
    _check_no_extra(data, "規則", {"name", "target_window", "region", "condition",
                                   "interval_sec", "cooldown_sec", "trigger",
                                   "triggers", "enabled", "attach_screenshot"})
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        _err("規則欄位 name 必須是非空字串且不含路徑分隔字元")
    if "target_window" not in data:
        _err("規則缺少欄位 target_window")
    target = _validate_target_window(data["target_window"])
    region = _get_region(data, "規則")
    if "condition" not in data:
        _err("規則缺少欄位 condition")
    condition = _validate_rule_condition(data["condition"])
    if "triggers" in data:
        raw = data["triggers"]
        if not isinstance(raw, list) or not raw:
            _err("規則欄位 triggers 必須是至少一個動作的清單")
        triggers = tuple(_validate_rule_trigger(t) for t in raw)
    elif "trigger" in data:
        triggers = (_validate_rule_trigger(data["trigger"]),)   # 舊格式遷移
    else:
        _err("規則缺少欄位 triggers")
    interval = _get_positive_number(data, "interval_sec", 5.0, allow_zero=False)
    cooldown = _get_positive_number(data, "cooldown_sec", 60.0, allow_zero=True)
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        _err("規則欄位 enabled 必須是布林值")
    attach_screenshot = data.get("attach_screenshot", False)
    if not isinstance(attach_screenshot, bool):
        _err("規則欄位 attach_screenshot 必須是布林值")
    return Rule(name=name, target_window=target, condition=condition, triggers=triggers,
                region=region, interval_sec=interval, cooldown_sec=cooldown, enabled=enabled,
                attach_screenshot=attach_screenshot)


def rule_to_dict(rule: Rule) -> dict:
    if rule.condition.type == "text":
        cond = {"type": "text", "pattern": rule.condition.pattern,
                "mode": rule.condition.mode, "absent": rule.condition.absent}
    elif rule.condition.type == "image":
        cond = {"type": "image", "template": rule.condition.template,
                "threshold": rule.condition.threshold, "absent": rule.condition.absent}
    else:  # color
        c = rule.condition
        cond = {"type": "color", "hue": c.hue, "sat": c.sat, "val": c.val,
                "hue_tol": c.hue_tol, "sat_tol": c.sat_tol, "val_tol": c.val_tol,
                "min_pixels": c.min_pixels, "absent": c.absent}
    return {
        "name": rule.name,
        "target_window": {"title_pattern": rule.target_window.title_pattern,
                          "app_name": rule.target_window.app_name},
        "region": rule.region,
        "condition": cond,
        "triggers": [_trigger_to_dict(t) for t in rule.triggers],
        "interval_sec": rule.interval_sec,
        "cooldown_sec": rule.cooldown_sec,
        "enabled": rule.enabled,
        "attach_screenshot": rule.attach_screenshot,
    }


_BUTTON_LABELS = {"left": "左鍵", "right": "右鍵", "middle": "中鍵"}


def action_label(action: Action) -> str:
    """動作的繁中人類可讀摘要（GUI 步驟表格與 Player 進度回報共用）；有名稱時加在前面。"""
    name = action.params.get("name")
    base = _base_action_label(action)
    return f"{name}：{base}" if name else base


def _base_action_label(action: Action) -> str:
    p = action.params
    t = action.type
    if t is ActionType.KEY_PRESS:
        return f"按鍵 {p['key']}"
    if t is ActionType.KEY_COMBO:
        combo = "組合鍵 " + "+".join(p["keys"])
        return f"{combo}（按住 {p['hold_ms']}ms）" if p["hold_ms"] else combo
    if t is ActionType.TEXT_INPUT:
        text = p["text"]
        return f"輸入文字「{text[:20]}{'…' if len(text) > 20 else ''}」"
    if t is ActionType.MOUSE_MOVE:
        return f"滑鼠移動到 ({p['x']}, {p['y']})"
    if t is ActionType.MOUSE_CLICK:
        return f"滑鼠{_BUTTON_LABELS[p['button']]}點擊 ({p['x']}, {p['y']}) ×{p['count']}"
    if t is ActionType.MOUSE_DRAG:
        return (f"滑鼠{_BUTTON_LABELS[p['button']]}拖曳 "
                f"({p['from'][0]}, {p['from'][1]}) → ({p['to'][0]}, {p['to'][1]})")
    if t is ActionType.SCROLL:
        return f"捲動 ({p['x']}, {p['y']}) dx={p['dx']} dy={p['dy']}"
    if t is ActionType.DELAY:
        ms = p["ms"]
        return f"延遲 {ms[0]}–{ms[1]}ms" if isinstance(ms, list) else f"延遲 {ms}ms"
    if t is ActionType.LOOP:
        count = "無限" if p["count"] == -1 else f"{p['count']} 次"
        return f"迴圈 {count}（{len(p['actions'])} 個動作）"
    if t is ActionType.RUN_SCRIPT:
        return f"執行腳本「{p['script_name']}」"
    if t is ActionType.WAIT_TEXT:
        return f"等待文字「{p['pattern']}」"
    if t is ActionType.WAIT_IMAGE:
        return f"等待圖像「{p['template']}」"
    if t is ActionType.IF_TEXT:
        return f"若出現文字「{p['pattern']}」"
    if t is ActionType.IF_IMAGE:
        return f"若出現圖像「{p['template']}」"
    if t is ActionType.CLICK_TEXT:
        return f"點擊文字「{p['pattern']}」"
    if t is ActionType.MINIMAP_GOTO:
        return f"依小地圖位置跳轉（{len(p['branches'])} 個區域）"
    if t is ActionType.GOTO:
        return f"跳到動作 #{p['goto_index']}"
    if t is ActionType.MINIMAP_MOVE:
        verb = {"walk": "走到", "rope": "爬繩到", "down_jump": "下跳到",
                "hold": "按住衝到"}.get(p["method"], "走到")
        hold = f"（沿路按 {p['path_key']}）" if p.get("path_key") else ""
        if p["method"] == "hold" and p.get("hold_keys"):
            hold = f"（按住 {'+'.join(p['hold_keys'])}）"
        return f"{verb}小地圖 ({p['target'][0]}, {p['target'][1]}){hold}"
    return f"點擊圖像「{p['template']}」"   # CLICK_IMAGE（ActionType 窮舉完畢）
