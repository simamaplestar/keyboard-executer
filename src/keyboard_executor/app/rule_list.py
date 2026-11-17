"""規則清單狀態（純 Python，無 Qt import）：列出、啟用/停用切換、刪除。"""
from __future__ import annotations

import dataclasses

from keyboard_executor.app.naming import unique_copy_name
from keyboard_executor.core.models import ScriptValidationError


class RuleListController:
    def __init__(self, storage):
        self._storage = storage
        self._names: list[str] = []

    def refresh(self) -> list[str]:
        self._names = self._storage.list_names()
        return list(self._names)

    @property
    def names(self) -> list[str]:
        return list(self._names)

    def labels(self) -> list[str]:
        """重新整理並回傳顯示標籤；損毀規則檔標示但仍列出（可刪除）。"""
        labels = []
        for name in self.refresh():
            try:
                rule = self._storage.load(name)
            except ScriptValidationError:
                labels.append(f"{name}（載入失敗）")
                continue
            labels.append(f"{name}（{'啟用' if rule.enabled else '停用'}）")
        return labels

    def toggle_enabled(self, name: str) -> bool:
        rule = self._storage.load(name)
        updated = dataclasses.replace(rule, enabled=not rule.enabled)
        self._storage.save(updated)
        return updated.enabled

    def delete(self, name: str) -> None:
        self._storage.delete(name)

    def duplicate(self, name: str) -> str:
        new = unique_copy_name(name, self._storage.list_names())
        self._storage.save(dataclasses.replace(self._storage.load(name), name=new))
        return new
