"""規則 JSON 檔案存取。一個規則一個檔：<root>/rules/<name>.json。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from keyboard_executor.core.models import (
    Rule,
    ScriptValidationError,
    rule_from_dict,
    rule_to_dict,
)

logger = logging.getLogger(__name__)


class RuleStorage:
    def __init__(self, root: str | Path):
        self._dir = Path(root) / "rules"

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or not name.strip():
            raise ScriptValidationError(f"規則名稱不合法: {name!r}")
        return self._dir / f"{name}.json"

    def save(self, rule: Rule) -> Path:
        path = self.path_for(rule.name)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(rule_to_dict(rule), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
        except OSError as e:
            raise ScriptValidationError(f"規則 {rule.name!r} 無法儲存: {e}") from e
        return path

    def load(self, name: str) -> Rule:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到規則 {name!r}（{path}）")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ScriptValidationError(f"規則 {name!r} 不是合法 JSON: {e}") from e
        except (UnicodeDecodeError, OSError) as e:
            raise ScriptValidationError(f"規則 {name!r} 無法讀取: {e}") from e
        return rule_from_dict(data)

    def delete(self, name: str) -> None:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到規則 {name!r}（{path}）")
        try:
            path.unlink()
        except OSError as e:
            raise ScriptValidationError(f"規則 {name!r} 無法刪除: {e}") from e

    def list_names(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def load_enabled(self) -> list[Rule]:
        """載入所有啟用中的規則；防守式逐檔載入——單一規則檔損毀只記錄並跳過該檔，
        不影響其他規則載入（spec §10「腳本 JSON 損壞：載入時 schema 驗證，報錯不崩潰」的
        規則版）。"""
        rules = []
        for name in self.list_names():
            try:
                rule = self.load(name)
            except ScriptValidationError as e:
                logger.warning("規則 %r 載入失敗，已跳過：%s", name, e)
                continue
            if rule.enabled:
                rules.append(rule)
        return rules
