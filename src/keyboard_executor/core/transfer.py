"""腳本／規則的匯出包：相依解析 ＋ 單一 JSON 的建構與解析（純邏輯，不碰檔案）。

匯出的目的是「把一個檔傳給別人就能用」，所以光複製腳本／規則 JSON 不夠——它們會
引用不在自己檔案裡的東西，漏掉任一項對方匯入後就是壞的：

- 腳本的 wait_image / if_image / click_image → 模板圖片
- 腳本的 run_script → 另一支腳本（可再引用下去，需遞迴）
- 規則的 image 條件 → 模板圖片
- 規則的 run_script 觸發 → 腳本（同樣要遞迴）

而且巢狀動作（loop 的 actions、if_* 的 then/else）裡的引用一樣算數，只看第一層會漏。

模板圖片以 base64 內嵌（使用者選定單一 JSON 格式）。體積代價是原始位元組的約 4/3，
但只有「真的被引用到」的模板會進包——沒被任何腳本或規則用到的模板不會佔空間。

設定檔（settings.json）一律不進匯出包：裡面有 Discord webhook 與 AI 金鑰，
匯出等於把憑證一起交出去。
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

from keyboard_executor.core.models import (
    NESTED_ACTION_KEYS,
    Rule,
    Script,
    ScriptValidationError,
    rule_from_dict,
    rule_to_dict,
    script_from_dict,
    script_to_dict,
)

FORMAT_ID = "keyboard-executor-export"
FORMAT_VERSION = 1

# 這些動作的 params["template"] 指向 templates/<名稱>.png
_TEMPLATE_ACTIONS = ("wait_image", "if_image", "click_image")


def walk_actions(actions):
    """逐一走訪動作，含 loop 的 actions 與 if_* 的 then/else（深度優先）。

    只看第一層會漏掉迴圈或條件分支裡的圖像動作，那些引用一樣要打包。
    """
    for action in actions or ():
        yield action
        for key in NESTED_ACTION_KEYS:
            nested = action.params.get(key)
            if nested:
                yield from walk_actions(nested)


def template_names_in_script(script: Script) -> set[str]:
    """腳本（含巢狀動作）引用到的模板名稱。"""
    names = set()
    for action in walk_actions(script.actions):
        if str(action.type) in _TEMPLATE_ACTIONS:
            name = action.params.get("template")
            if name:
                names.add(str(name))
    return names


def script_names_in_script(script: Script) -> set[str]:
    """腳本（含巢狀動作）以 run_script 引用到的其他腳本名稱。"""
    names = set()
    for action in walk_actions(script.actions):
        if str(action.type) == "run_script":
            name = action.params.get("script_name")
            if name:
                names.add(str(name))
    return names


def template_names_in_rule(rule: Rule) -> set[str]:
    if rule.condition.type == "image" and rule.condition.template:
        return {str(rule.condition.template)}
    return set()


def script_names_in_rule(rule: Rule) -> set[str]:
    return {str(t.script_name) for t in rule.triggers
            if t.type == "run_script" and t.script_name}


@dataclass
class Dependencies:
    """解析結果。missing_* 是「引用到但找不到」的名稱，呼叫端據此警告使用者
    ——照樣讓他匯出（可能是他刻意刪掉的舊引用），但要說清楚哪裡會缺。"""
    scripts: list[Script] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    templates: set[str] = field(default_factory=set)
    missing_scripts: set[str] = field(default_factory=set)


def resolve(script_names, rule_names, load_script, load_rule) -> Dependencies:
    """從使用者勾選的名稱出發，遞迴補齊相依的腳本，並收集所有需要的模板。

    load_script(name) / load_rule(name) 由呼叫端提供（storage 的 load），
    本模組因此不需要碰檔案系統，可完整單元測試。載入失敗的腳本記進
    missing_scripts 而不是中斷——匯出半套好過完全不能匯出。
    """
    deps = Dependencies()
    rules_by_name = {}
    for name in rule_names:
        rule = load_rule(name)
        rules_by_name[name] = rule
        deps.templates |= template_names_in_rule(rule)
    deps.rules = [rules_by_name[n] for n in rule_names]

    # 待處理腳本 = 使用者勾的 ＋ 規則觸發引用的；處理過程中再遞迴加入 run_script 引用
    pending = list(script_names)
    for rule in deps.rules:
        pending.extend(script_names_in_rule(rule))

    seen: set[str] = set()
    scripts_by_name: dict[str, Script] = {}
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        try:
            script = load_script(name)
        except ScriptValidationError:
            deps.missing_scripts.add(name)
            continue
        scripts_by_name[name] = script
        deps.templates |= template_names_in_script(script)
        pending.extend(script_names_in_script(script))

    # 使用者勾的排前面，遞迴帶進來的接在後面（順序穩定，方便比對匯出內容）
    ordered = [n for n in script_names if n in scripts_by_name]
    ordered += [n for n in scripts_by_name if n not in script_names]
    deps.scripts = [scripts_by_name[n] for n in ordered]
    return deps


def build_bundle(scripts, rules, templates: dict[str, bytes], *,
                 app_version: str = "") -> dict:
    """組出匯出包 dict（呼叫端負責 json.dumps 與寫檔）。

    templates 是「模板名稱 → PNG 位元組」，在此轉成 base64 字串。
    """
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "app_version": app_version,
        "scripts": [script_to_dict(s) for s in scripts],
        "rules": [rule_to_dict(r) for r in rules],
        "templates": {name: base64.b64encode(data).decode("ascii")
                      for name, data in sorted(templates.items())},
    }


@dataclass
class Bundle:
    scripts: list[Script] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    templates: dict[str, bytes] = field(default_factory=dict)
    app_version: str = ""


def parse_bundle(data) -> Bundle:
    """解析並驗證匯出包；格式不對一律拋 ScriptValidationError（繁中訊息）。

    每個項目都走既有的 script_from_dict / rule_from_dict 驗證，所以匯入的內容
    與自家存檔受同一套規則把關，不會因為來源是外部檔案就放行壞資料。
    """
    if not isinstance(data, dict):
        raise ScriptValidationError("匯入檔格式錯誤：最外層必須是 JSON 物件")
    if data.get("format") != FORMAT_ID:
        raise ScriptValidationError(
            "這個檔案不是 Keyboard Executor 的匯出檔（缺少正確的 format 標記）")
    version = data.get("version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise ScriptValidationError(
            f"匯入檔版本 {version!r} 超出本程式支援範圍（最高 {FORMAT_VERSION}），請更新程式")

    bundle = Bundle(app_version=str(data.get("app_version") or ""))
    for key, target, parser in (("scripts", bundle.scripts, script_from_dict),
                                ("rules", bundle.rules, rule_from_dict)):
        items = data.get(key) or []
        if not isinstance(items, list):
            raise ScriptValidationError(f"匯入檔格式錯誤：{key} 必須是清單")
        for item in items:
            target.append(parser(item))

    templates = data.get("templates") or {}
    if not isinstance(templates, dict):
        raise ScriptValidationError("匯入檔格式錯誤：templates 必須是 JSON 物件")
    for name, encoded in templates.items():
        try:
            bundle.templates[str(name)] = base64.b64decode(str(encoded), validate=True)
        except (binascii.Error, ValueError) as e:
            raise ScriptValidationError(f"匯入檔的模板圖片 {name!r} 損毀：{e}") from e
    return bundle


def missing_templates(bundle: Bundle) -> set[str]:
    """匯入包裡「有人引用、卻沒附圖」的模板名稱。

    匯入仍可繼續（其他項目照樣可用），但要明白告訴使用者哪些圖像判斷會失效，
    否則腳本跑起來只會靜默比對不到。
    """
    needed: set[str] = set()
    for script in bundle.scripts:
        needed |= template_names_in_script(script)
    for rule in bundle.rules:
        needed |= template_names_in_rule(rule)
    return needed - set(bundle.templates)
