"""腳本步驟編輯模型（純 Python，無 Qt import）。

內部以「正規化 action dict」（action_to_dict(action_from_dict(d)) 的形狀）保存
步驟；所有寫入先過 models.action_from_dict 驗證（繁中錯誤原樣拋
ScriptValidationError 供 GUI 顯示、狀態不變），to_script() 再以 script_from_dict
做整份權威驗證——與存檔格式 round-trip 一致。"""
from __future__ import annotations

import copy

from keyboard_executor.core.sequence_input_config import (
    SequenceInputConfig, sequence_config_from_dict, sequence_config_to_dict,
)
from keyboard_executor.core.chat_reply_config import (
    ChatReplyConfig, chat_config_from_dict, chat_config_to_dict,
)
from keyboard_executor.core.models import (
    Script,
    action_from_dict,
    action_label,
    action_to_dict,
    script_from_dict,
    script_to_dict,
)


def _remap_gotos(d: dict, new_of: dict[int, int]) -> dict:
    """同一層動作重排後，把 goto_index／otherwise_index／branches 改指到新位置。"""
    d = copy.deepcopy(d)
    for key in ("goto_index", "otherwise_index"):
        if isinstance(d.get(key), int) and d[key] in new_of:
            d[key] = new_of[d[key]]
    for branch in d.get("branches") or []:
        if isinstance(branch.get("goto_index"), int) and branch["goto_index"] in new_of:
            branch["goto_index"] = new_of[branch["goto_index"]]
    return d


class ScriptEditorModel:
    def __init__(self, script: Script):
        data = script_to_dict(script)
        self._name: str = data["name"]
        # 載入既有腳本時記住原始名稱，改名存檔才能刪掉舊名那條（含版面 sidecar），
        # 避免變成新增一條。新腳本（new()）設為 None。
        self._original_name: str | None = data["name"]
        self._target_window: dict = data["target_window"]
        self._settings: dict = data["settings"]
        self._actions: list[dict] = data["actions"]

    @property
    def name(self) -> str:
        return self._name

    @property
    def original_name(self) -> str | None:
        return self._original_name

    def mark_saved(self) -> None:
        """存檔後把 original_name 更新為目前名稱（同一視窗再存以新名為準）。"""
        self._original_name = self._name

    def set_name(self, name: str) -> None:
        self._name = name

    @classmethod
    def new(cls, name: str = "新腳本") -> "ScriptEditorModel":
        """建立空白腳本模型，供 GUI「新增腳本」手動編寫（不需先錄製）。
        target_window 與 actions 先留空；存檔時 to_script 會強制驗證
        （需至少一個目標視窗欄位＋至少一個動作），逼使用者補齊。"""
        obj = cls.__new__(cls)
        obj._name = name
        obj._original_name = None          # 新腳本：無舊名可刪
        obj._target_window = {"title_pattern": None, "app_name": None}
        obj._settings = {"speed": 1.0, "repeat": 1, "humanize_jitter_pct": 0,
                         "game_input_mode": True, "window_message_mode": False,
                         "scan_pulse_mode": False,
                         "window_retry": 0,
                         "window_retry_interval_ms": 1000, "hotkey": ""}
        obj._actions = []
        return obj

    @property
    def target_title(self) -> str:
        return self._target_window.get("title_pattern") or ""

    @property
    def target_app(self) -> str:
        return self._target_window.get("app_name") or ""

    def set_target(self, title: str, app: str) -> None:
        """設定目標視窗（空字串＝該欄位留空）。存檔時 models 會驗證兩者不可皆空。"""
        self._target_window = {"title_pattern": title.strip() or None,
                               "app_name": app.strip() or None}

    @property
    def loop_forever(self) -> bool:
        """整份腳本是否循環執行到手動停止（settings.repeat == -1）。"""
        return self._settings.get("repeat") == -1

    def set_loop_forever(self, on: bool) -> None:
        self._settings["repeat"] = -1 if on else 1

    @property
    def game_input_mode(self) -> bool:
        return bool(self._settings.get("game_input_mode", True))

    def set_game_input_mode(self, on: bool) -> None:
        self._settings["game_input_mode"] = on
        if on:
            self._settings["window_message_mode"] = False
            self._settings["scan_pulse_mode"] = False

    @property
    def input_mode(self) -> str:
        if bool(self._settings.get("window_message_mode", False)):
            return "window_message"
        if bool(self._settings.get("scan_pulse_mode", False)):
            return "scan_pulse"
        return "game" if self.game_input_mode else "normal"

    def set_input_mode(self, mode: str) -> None:
        if mode not in {"normal", "game", "window_message", "scan_pulse"}:
            raise ValueError(f"未知的輸入模式: {mode}")
        self._settings["game_input_mode"] = mode == "game"
        self._settings["window_message_mode"] = mode == "window_message"
        self._settings["scan_pulse_mode"] = mode == "scan_pulse"

    @property
    def hotkey(self) -> str:
        return str(self._settings.get("hotkey", ""))

    def set_hotkey(self, value: str) -> None:
        self._settings["hotkey"] = value or ""

    @property
    def timed_keys_text(self) -> str:
        """定時技能的文字格式（如「1:120, 2:180」）。"""
        from keyboard_executor.core.models import timed_key_from_dict, timed_keys_to_text
        items = [timed_key_from_dict(d, i)
                 for i, d in enumerate(self._settings.get("timed_keys") or [])]
        return timed_keys_to_text(items)

    def set_timed_keys_text(self, text: str) -> None:
        """解析失敗拋 ScriptValidationError（繁中說明格式）；留空＝不使用。"""
        from keyboard_executor.core.models import timed_key_to_dict, timed_keys_from_text
        items = timed_keys_from_text(text or "")
        if items:
            self._settings["timed_keys"] = [timed_key_to_dict(t) for t in items]
        else:
            self._settings.pop("timed_keys", None)

    @property
    def chat_reply(self) -> ChatReplyConfig | None:
        data = self._settings.get("chat_reply")
        return chat_config_from_dict(copy.deepcopy(data)) if data is not None else None

    def set_chat_reply(self, config: ChatReplyConfig | None) -> None:
        """先驗證再替換；回覆操作的可變 params 不與呼叫端共用。"""
        if config is None:
            self._settings.pop("chat_reply", None)
            return
        normalized = chat_config_from_dict(chat_config_to_dict(config))
        self._settings["chat_reply"] = copy.deepcopy(chat_config_to_dict(normalized))

    @property
    def sequence_input(self) -> SequenceInputConfig | None:
        data = self._settings.get("sequence_input")
        return sequence_config_from_dict(copy.deepcopy(data)) if data is not None else None

    def set_sequence_input(self, config: SequenceInputConfig | None) -> None:
        if config is None:
            self._settings.pop("sequence_input", None)
            return
        normalized = sequence_config_from_dict(sequence_config_to_dict(config))
        self._settings["sequence_input"] = sequence_config_to_dict(normalized)

    def __len__(self) -> int:
        return len(self._actions)

    def rows(self) -> list[dict]:
        """[{'type': ..., 'label': ...}] 供表格顯示。"""
        return [{"type": d["type"], "label": action_label(action_from_dict(d))}
                for d in self._actions]

    def action_at(self, index: int) -> dict:
        return copy.deepcopy(self._actions[index])

    def insert(self, index: int, action_dict: dict) -> None:
        normalized = action_to_dict(action_from_dict(action_dict))
        self._actions.insert(max(0, min(index, len(self._actions))), normalized)

    def update(self, index: int, action_dict: dict) -> None:
        normalized = action_to_dict(action_from_dict(action_dict))
        self._actions[index] = normalized

    def remove(self, index: int) -> None:
        del self._actions[index]

    def duplicate(self, index: int) -> None:
        self._actions.insert(index + 1, copy.deepcopy(self._actions[index]))

    def move(self, index: int, delta: int) -> int:
        """步驟上移（delta<0）/下移（delta>0），回傳新位置（邊界夾住）。"""
        target = max(0, min(index + delta, len(self._actions) - 1))
        order = list(range(len(self._actions)))
        order.insert(target, order.pop(index))
        self.reorder(order)
        return target

    def move_to(self, src: int, dst: int) -> int:
        """把 src 位置的動作移到 dst（供拖曳排序）；回傳移動後實際位置。
        dst 為「移除 src 前」的目標插入索引（0..len），內部自動校正。"""
        if src < 0 or src >= len(self._actions):
            return src
        order = list(range(len(self._actions)))
        order.pop(src)
        if dst > src:
            dst -= 1
        dst = max(0, min(dst, len(order)))
        order.insert(dst, src)
        self.reorder(order)
        return dst

    def reorder(self, perm: list[int]) -> None:
        """依 perm（新順序的舊索引清單）整批重排動作；供自由畫布「位置決定順序」用。
        perm 必須是 0..n-1 的一個排列，否則不動作（避免遺失動作）。
        「跳到動作 N」會跟著原本指向的那個動作一起移動。"""
        if sorted(perm) != list(range(len(self._actions))):
            return
        new_of = {old: new for new, old in enumerate(perm)}
        self._actions = [_remap_gotos(self._actions[i], new_of) for i in perm]

    def group_into_loop(self, start: int, end: int, count: int) -> int:
        """把 [start, end] 連續動作包成一個 loop（重複 count 次；-1＝無限），
        回傳 loop 的新索引。供「框選現有動作組成迴圈」用。"""
        if start < 0 or end >= len(self._actions) or start > end:
            return start
        inner = self._actions[start:end + 1]
        loop = action_to_dict(action_from_dict(
            {"type": "loop", "count": count, "actions": inner}))
        self._actions[start:end + 1] = [loop]
        return start

    def ungroup_loop(self, index: int) -> None:
        """把 index 的 loop 拆回其內含動作（非 loop 則不動）。"""
        if 0 <= index < len(self._actions) and self._actions[index].get("type") == "loop":
            inner = self._actions[index]["actions"]
            self._actions[index:index + 1] = [
                action_to_dict(action_from_dict(a)) for a in inner]

    def set_loop_count(self, index: int, count: int) -> None:
        """改 index 迴圈的重複次數（非 loop 則不動）。"""
        d = self._actions[index]
        if d.get("type") == "loop":
            self._actions[index] = action_to_dict(action_from_dict({**d, "count": count}))

    def set_action_name(self, index: int, name: str) -> None:
        """改 index 動作的名稱（空白＝移除名稱）。"""
        d = {k: v for k, v in self._actions[index].items() if k != "name"}
        self._actions[index] = action_to_dict(action_from_dict({**d, "name": name}))

    def is_loop(self, index: int) -> bool:
        return 0 <= index < len(self._actions) and self._actions[index].get("type") == "loop"

    def loop_inner_at(self, index: int, inner_index: int) -> dict:
        """回傳迴圈 index 內第 inner_index 個動作（deepcopy），供編輯迴圈內動作。"""
        inner = self._actions[index].get("actions", [])
        return copy.deepcopy(inner[inner_index])

    def update_loop_inner(self, index: int, inner_index: int, action_dict: dict) -> None:
        """替換迴圈 index 內第 inner_index 個動作（次數不變；整份仍過驗證）。
        讓使用者不必先「解散迴圈」就能編輯框內動作。"""
        d = self._actions[index]
        if d.get("type") != "loop":
            return
        inner = list(d.get("actions", []))
        if not 0 <= inner_index < len(inner):
            return
        inner[inner_index] = action_to_dict(action_from_dict(action_dict))
        self._actions[index] = action_to_dict(action_from_dict(
            {"type": "loop", "count": d.get("count", 1), "actions": inner}))

    def add_to_loop(self, index: int, action_dict: dict) -> None:
        """把動作加到 index 迴圈的 actions 末尾（次數不變；整份仍過驗證）。非 loop 則不動。
        無效動作 → action_from_dict 於改動 self._actions 前拋 ScriptValidationError，狀態不變。"""
        d = self._actions[index]
        if d.get("type") != "loop":
            return
        inner = list(d.get("actions", []))
        inner.append(action_to_dict(action_from_dict(action_dict)))
        self._actions[index] = action_to_dict(action_from_dict(
            {"type": "loop", "count": d.get("count", 1), "actions": inner}))

    def snapshot(self) -> dict:
        """整份內部狀態的深拷貝，供編輯器 undo/redo（不經驗證，存的是已正規化資料）。"""
        return {"name": self._name,
                "target_window": copy.deepcopy(self._target_window),
                "settings": copy.deepcopy(self._settings),
                "actions": copy.deepcopy(self._actions)}

    def restore(self, snap: dict) -> None:
        """還原 snapshot() 取得的狀態（供 undo/redo）。"""
        self._name = snap["name"]
        self._target_window = copy.deepcopy(snap["target_window"])
        self._settings = copy.deepcopy(snap["settings"])
        self._actions = copy.deepcopy(snap["actions"])

    def to_script(self) -> Script:
        return script_from_dict({
            "name": self._name,
            "target_window": copy.deepcopy(self._target_window),
            "settings": copy.deepcopy(self._settings),
            "actions": copy.deepcopy(self._actions),
        })
