"""匯出／匯入的檔案面協調：把 core/transfer 的純邏輯接上三個 storage。

分層理由同其他 storage：core/transfer 只管相依解析與格式（可完整單元測試、不碰
磁碟），這裡負責讀寫，GUI 對話框則只剩選檔與詢問覆蓋。

覆蓋政策：apply_bundle 預設**不覆蓋**任何同名項目，要蓋的名稱得由呼叫端明列。
匯入來源是別人給的檔案，靜默蓋掉使用者自己的腳本是不可接受的資料遺失。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from keyboard_executor import __version__
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.transfer import (
    Bundle,
    build_bundle,
    missing_templates,
    parse_bundle,
    resolve,
)


@dataclass
class ExportSummary:
    path: Path | None = None
    scripts: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    missing_scripts: list[str] = field(default_factory=list)
    missing_templates: list[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.missing_scripts or self.missing_templates)


@dataclass
class Conflicts:
    scripts: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.scripts or self.rules or self.templates)

    @property
    def all_names(self) -> list[str]:
        return self.scripts + self.rules + self.templates


@dataclass
class ImportSummary:
    scripts: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    missing_templates: list[str] = field(default_factory=list)


class TransferService:
    def __init__(self, scripts, rules, templates):
        self._scripts = scripts
        self._rules = rules
        self._templates = templates

    # --- 匯出 ---

    def plan(self, script_names, rule_names) -> ExportSummary:
        """先算出「實際會被匯出的東西」，供 UI 在按下匯出前顯示。

        使用者勾了 3 支腳本，實際可能因為 run_script 而帶進第 4 支、因為圖像動作
        而帶進幾張模板——這些要在匯出前就看得到，不是事後才發現。
        """
        deps = resolve(list(script_names), list(rule_names),
                       self._scripts.load, self._rules.load)
        summary = ExportSummary(
            scripts=[s.name for s in deps.scripts],
            rules=[r.name for r in deps.rules],
            missing_scripts=sorted(deps.missing_scripts),
        )
        available = set(self._templates.list_names())
        summary.templates = sorted(deps.templates & available)
        summary.missing_templates = sorted(deps.templates - available)
        return summary

    def export(self, path, script_names, rule_names) -> ExportSummary:
        deps = resolve(list(script_names), list(rule_names),
                       self._scripts.load, self._rules.load)
        summary = self.plan(script_names, rule_names)
        images: dict[str, bytes] = {}
        for name in summary.templates:
            images[name] = self._templates.read_bytes(name)
        data = build_bundle(deps.scripts, deps.rules, images, app_version=__version__)
        path = Path(path)
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        except OSError as e:
            raise ScriptValidationError(f"匯出檔無法寫入: {e}") from e
        summary.path = path
        return summary

    # --- 匯入 ---

    def read(self, path) -> Bundle:
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ScriptValidationError(f"匯入檔無法讀取: {e}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ScriptValidationError(f"匯入檔不是合法 JSON: {e}") from e
        return parse_bundle(data)

    def conflicts(self, bundle: Bundle) -> Conflicts:
        """匯入包中與現有資料同名的項目。"""
        existing_scripts = set(self._scripts.list_names())
        existing_rules = set(self._rules.list_names())
        existing_templates = set(self._templates.list_names())
        return Conflicts(
            scripts=[s.name for s in bundle.scripts if s.name in existing_scripts],
            rules=[r.name for r in bundle.rules if r.name in existing_rules],
            templates=[n for n in sorted(bundle.templates) if n in existing_templates],
        )

    def apply(self, bundle: Bundle, *, overwrite=()) -> ImportSummary:
        """把匯入包寫進儲存區；同名項目只有列在 overwrite 裡才覆蓋，其餘略過。

        單一項目失敗（例如某張圖損毀）不中斷整批——記進 failed 後繼續，
        讓使用者至少拿到能用的部分，並看得到哪幾項沒進來。
        """
        overwrite = set(overwrite)
        conflicts = self.conflicts(bundle)
        summary = ImportSummary(missing_templates=sorted(missing_templates(bundle)))

        # 模板先寫：腳本與規則要靠它才完整
        for name in sorted(bundle.templates):
            if name in conflicts.templates and name not in overwrite:
                summary.skipped.append(name)
                continue
            try:
                self._templates.write_bytes(name, bundle.templates[name])
                summary.templates.append(name)
            except ScriptValidationError:
                summary.failed.append(name)

        for script in bundle.scripts:
            if script.name in conflicts.scripts and script.name not in overwrite:
                summary.skipped.append(script.name)
                continue
            try:
                self._scripts.save(script)
                summary.scripts.append(script.name)
            except ScriptValidationError:
                summary.failed.append(script.name)

        for rule in bundle.rules:
            if rule.name in conflicts.rules and rule.name not in overwrite:
                summary.skipped.append(rule.name)
                continue
            try:
                self._rules.save(rule)
                summary.rules.append(rule.name)
            except ScriptValidationError:
                summary.failed.append(rule.name)
        return summary
