"""腳本清單狀態與摘要（純 Python，無 Qt import）。"""
from __future__ import annotations

import dataclasses

from keyboard_executor.app.naming import unique_copy_name
from keyboard_executor.core.models import ScriptValidationError


class ScriptListController:
    def __init__(self, storage):
        self._storage = storage
        self._names: list[str] = []
        self._selected: str | None = None

    def refresh(self) -> list[str]:
        self._names = self._storage.list_names()
        if self._selected not in self._names:
            self._selected = None
        return list(self._names)

    @property
    def names(self) -> list[str]:
        return list(self._names)

    def select(self, name: str) -> None:
        if name not in self._names:
            raise ValueError(f"未知腳本: {name!r}")
        self._selected = name

    @property
    def selected(self) -> str | None:
        return self._selected

    def delete_selected(self) -> str:
        if self._selected is None:
            raise ValueError("尚未選取腳本")
        name = self._selected
        self._storage.delete(name)
        self.refresh()
        return name

    def duplicate_selected(self) -> str:
        if self._selected is None:
            raise ValueError("尚未選取腳本")
        name = self._selected
        new = unique_copy_name(name, self._storage.list_names())
        self._storage.save(dataclasses.replace(self._storage.load(name), name=new))
        layout = self._storage.load_layout(name)
        if layout is not None:
            self._storage.save_layout(new, layout)   # 版面（node 位置）一併複製
        self.refresh()
        return new


def summary_for_script(storage, name: str) -> str:
    """右側摘要文字；載入失敗回繁中錯誤字串（不拋，GUI 直接顯示）。"""
    try:
        script = storage.load(name)
    except ScriptValidationError as e:
        return f"腳本載入失敗：{e}"
    target = script.target_window.title_pattern or script.target_window.app_name
    repeat = "無限" if script.settings.repeat == -1 else f"{script.settings.repeat} 次"
    return (f"腳本「{script.name}」：{len(script.actions)} 個步驟，"
            f"目標視窗 {target}，重複 {repeat}")


def script_list_label(storage, name: str) -> str:
    """腳本列表項目文字：有設啟動快捷鍵時加「   [Ctrl+Shift+1]」後綴（每段首字大寫）。
    載入失敗（腳本損毀）→ 只顯示名稱。"""
    try:
        hotkey = storage.load(name).settings.hotkey
    except ScriptValidationError:
        hotkey = ""
    if not hotkey:
        return name
    pretty = "+".join(part.capitalize() for part in hotkey.split("+"))
    return f"{name}   [{pretty}]"
