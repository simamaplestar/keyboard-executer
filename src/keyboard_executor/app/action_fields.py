"""Action 編輯表單的欄位規格與字串值解析（純 Python，無 Qt import）。

每個 ActionType 對應一組 (欄位名, 型別代號) 規格；表單（script_editor.ActionForm）
依此宣告式產生輸入元件，commit 時把字串值經 to_action_dict 轉為 action dict，
最終仍由 models.action_from_dict 做權威驗證。巢狀動作（loop/if 的
actions/then/else）以 JSON 文字欄位編輯（M4 取捨：視覺化巢狀編輯列 v2）。

型別代號：int、float、str、text（原樣字串，可空）、keys（"ctrl+shift+s"）、
point（"x, y"）、region（"x, y, w, h"，留空＝整個視窗）、ms（int 或 "min, max"）、
actions_json（JSON 動作清單）、choice:a/b/c（下拉）、bool（是/否下拉）。
"""
from __future__ import annotations

import json

from keyboard_executor.core.models import ScriptValidationError

FIELD_SPECS: dict[str, list[tuple[str, str]]] = {
    "key_press": [("key", "key"), ("hold_ms", "int")],
    "key_combo": [("keys", "keys"), ("hold_ms", "int")],
    "text_input": [("text", "text")],
    "mouse_move": [("x", "int"), ("y", "int")],
    "mouse_click": [("x", "int"), ("y", "int"),
                    ("button", "choice:left/right/middle"), ("count", "int")],
    "mouse_drag": [("from", "point"), ("to", "point"),
                   ("button", "choice:left/right/middle")],
    "scroll": [("x", "int"), ("y", "int"), ("dx", "int"), ("dy", "int")],
    "delay": [("ms", "ms")],
    "loop": [("count", "int"), ("actions", "actions_json")],
    "run_script": [("script_name", "str")],
    "wait_text": [("region", "region"), ("pattern", "str"),
                  ("mode", "choice:contains/regex"), ("timeout_ms", "int"),
                  ("on_timeout", "choice:abort/continue/goto"),
                  ("goto_index", "int")],
    "wait_image": [("region", "region"), ("template", "str"),
                   ("threshold", "float"), ("timeout_ms", "int"),
                   ("on_timeout", "choice:abort/continue/goto"),
                   ("goto_index", "int")],
    "if_text": [("region", "region"), ("pattern", "str"),
                ("mode", "choice:contains/regex"),
                ("then", "actions_json"), ("else", "actions_json")],
    "if_image": [("region", "region"), ("template", "str"),
                 ("threshold", "float"), ("mirror", "bool"),
                 ("then", "actions_json"), ("else", "actions_json")],
    "click_text": [("region", "region"), ("pattern", "str"),
                   ("mode", "choice:contains/regex")],
    "click_image": [("region", "region"), ("template", "str"),
                    ("threshold", "float")],
    "minimap_move": [("region", "region"), ("target", "point"),
                     ("method", "choice:walk/rope/down_jump/hold"), ("tolerance", "int"),
                     ("jump_key", "key"), ("hold_keys", "keys"), ("face_reverse", "bool"),
                     ("path_key", "key"), ("path_step", "int"),
                     ("path_template", "str"),
                     ("path_region", "region"), ("path_threshold", "float"),
                     ("quick", "bool"), ("timeout_ms", "int"),
                     ("on_timeout", "choice:abort/continue/goto"),
                     ("goto_index", "int")],
    "goto": [("goto_index", "int")],
    "minimap_goto": [("region", "region"), ("branches", "actions_json"),
                     ("otherwise", "choice:continue/abort/goto"),
                     ("otherwise_index", "int"), ("quick", "bool")],
}
# 每種動作第一欄都是可留空的名稱（編輯器方塊與紀錄顯示用，不影響執行）。
for _spec in FIELD_SPECS.values():
    _spec.insert(0, ("name", "str"))


ACTION_TYPE_LABELS: dict[str, str] = {
    "key_press": "按鍵", "key_combo": "組合鍵", "text_input": "輸入文字",
    "mouse_move": "滑鼠移動", "mouse_click": "滑鼠點擊", "mouse_drag": "滑鼠拖曳",
    "scroll": "捲動", "delay": "延遲", "loop": "迴圈", "run_script": "執行腳本",
    "wait_text": "等待文字出現", "wait_image": "等待圖像出現",
    "if_text": "若出現文字", "if_image": "若出現圖像",
    "click_text": "點擊文字", "click_image": "點擊圖像",
    "minimap_move": "走到小地圖位置",
    "minimap_goto": "依小地圖位置跳轉",
    "goto": "跳到動作",
}

FIELD_LABELS: dict[str, str] = {
    "key": "按鍵（點欄位再按一下要用的鍵；方向鍵、F 鍵皆可）",
    "hold_ms": "按住時間（毫秒；0＝按一下就放開，>0＝按住這麼久再放開）",
    "keys": "組合鍵（點欄位再按整組，如 Ctrl+Shift+S）", "text": "文字內容",
    # 座標一律是「相對目標視窗左上角」，不是螢幕座標（回放時由 player._to_screen
    # 加回視窗原點）。標籤必須講明，否則使用者會量螢幕座標填進去而永遠點錯位置。
    "x": "X 座標（相對目標視窗左上角）", "y": "Y 座標（相對目標視窗左上角）",
    "button": "滑鼠鍵", "count": "次數",
    "from": "起點（相對視窗 x, y）", "to": "終點（相對視窗 x, y）",
    "dx": "水平捲動量", "dy": "垂直捲動量",
    "ms": "延遲（毫秒；或「min, max」隨機）", "actions": "內含動作（JSON）",
    "script_name": "腳本名稱", "region": "區域 x, y, w, h（留空＝整個視窗）",
    "pattern": "文字內容", "mode": "比對方式", "timeout_ms": "逾時（毫秒）",
    "on_timeout": "逾時處理", "goto_index": "跳到動作（編輯器方塊上的 #序號）",
    "template": "模板名稱", "threshold": "相似度門檻（0~1）",
    "then": "符合時執行（JSON）", "else": "不符合時執行（JSON）",
    "mirror": "左右翻轉也比對（角色/怪物會面向兩邊時選是）",
    "name": "名稱（可留空；例如「回城」「第一層定點」，會顯示在編輯器方塊與紀錄）",
    "target": "目標位置（小地圖上的點，相對視窗 x, y）",
    "method": "移動方式",
    "tolerance": "容許誤差（小地圖像素，預設 1；衝刺技能用一次衝刺距離的一半）",
    "jump_key": "跳躍鍵（下跳用，預設 space）",
    "hold_keys": "一起按住的鍵（例如攻擊 C；按住攻擊鍵移動時必填）",
    "face_reverse": "衝刺前轉身要按反方向（技能往背後衝時選是；跑錯邊會自動改）",
    "path_key": "沿路按鍵（走一段按一下，可留空）",
    "path_step": "沿路按鍵間隔（每走幾格小地圖像素按一次，預設 5，越大越少按）",
    "path_template": "只在看到這個怪物模板時才沿路按鍵（可留空＝一律按）",
    "path_region": "怪物偵測範圍 x, y, w, h（同一層的畫面範圍）",
    "path_threshold": "怪物相似度門檻（0~1，預設 0.62）",
    "branches": "區域對應（黃點在哪個區域 → 跳到哪個動作）",
    "otherwise": "黃點不在任何區域時",
    "otherwise_index": "不在任何區域時跳到動作",
    "quick": "立即判斷（不等黃點停下；站在手扶梯／移動平台上要馬上下跳時選是，下跳方式才有效）",
}


def action_type_label(atype: str) -> str:
    """動作類型代號 → 繁中顯示名（未知代號原樣回傳）。"""
    return ACTION_TYPE_LABELS.get(atype, atype)


def field_label(name: str) -> str:
    """欄位代號 → 繁中顯示名（未知代號原樣回傳）。"""
    return FIELD_LABELS.get(name, name)


# 下拉選單的「值」→ 繁中顯示（動作表單與規則編輯器共用；儲存時仍存原值）。
CHOICE_LABELS: dict[str, str] = {
    "left": "左鍵", "right": "右鍵", "middle": "中鍵",
    "contains": "包含文字", "regex": "正規式 regex",
    "abort": "中止腳本", "continue": "繼續下一步", "goto": "跳到指定動作",
    "text": "文字", "image": "圖像", "color": "顏色",
    "notify": "顯示通知", "run_script": "執行腳本", "stop_all": "全部停止",
    "false": "否", "true": "是",
    "walk": "走路（左右對齊 X）", "rope": "爬繩（上下對齊 Y）",
    "hold": "按住攻擊鍵移動（衝刺技能：轉身後按住 hold_keys）",
    "down_jump": "下跳（下＋跳躍鍵，直到 Y）",
}


def choice_label(value: str) -> str:
    """下拉選單值 → 繁中顯示名（未知值原樣回傳）。"""
    return CHOICE_LABELS.get(value, value)


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ScriptValidationError(f"欄位 {name} 必須是整數: {raw!r}") from None


def parse_int_list(name: str, raw: str, count: int) -> list[int]:
    """"1, 2" / "[1, 2]" → [1, 2]；個數不符或非整數拋 ScriptValidationError。"""
    parts = [p.strip() for p in raw.replace("[", "").replace("]", "").split(",")]
    if len(parts) != count:
        raise ScriptValidationError(
            f"欄位 {name} 必須是 {count} 個以逗號分隔的整數: {raw!r}")
    return [_parse_int(name, p) for p in parts]


def to_action_dict(atype: str, values: dict[str, str]) -> dict:
    """表單字串值 → action dict。空字串（text 除外）＝省略欄位讓 models 帶預設；
    回傳值仍需經 action_from_dict 權威驗證（呼叫端 ScriptEditorModel 會做）。"""
    if atype not in FIELD_SPECS:
        raise ScriptValidationError(f"未知動作類型: {atype!r}")
    result: dict = {"type": atype}
    for name, kind in FIELD_SPECS[atype]:
        if kind == "text":
            result[name] = values.get(name, "")
            continue
        raw = (values.get(name) or "").strip()
        if not raw:
            continue
        if kind == "int":
            result[name] = _parse_int(name, raw)
        elif kind == "float":
            try:
                result[name] = float(raw)
            except ValueError:
                raise ScriptValidationError(
                    f"欄位 {name} 必須是數字: {raw!r}") from None
        elif kind == "bool":
            result[name] = raw.lower() in ("true", "1", "是", "yes")
        elif kind == "str" or kind == "key" or kind.startswith("choice:"):
            result[name] = raw     # key＝擷取到的單一按鍵名稱（如 up/f1/a）
        elif kind == "keys":
            result[name] = [k.strip() for k in raw.split("+") if k.strip()]
        elif kind == "point":
            result[name] = parse_int_list(name, raw, 2)
        elif kind == "region":
            result[name] = parse_int_list(name, raw, 4)
        elif kind == "ms":
            result[name] = (parse_int_list(name, raw, 2) if "," in raw
                            else _parse_int(name, raw))
        elif kind == "actions_json":
            try:
                result[name] = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ScriptValidationError(
                    f"欄位 {name} 不是合法 JSON: {e}") from None
    return result
