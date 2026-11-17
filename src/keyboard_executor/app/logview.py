"""日誌列格式化（純 Python，無 Qt import）。Task 8 追加等級過濾 should_log。"""
from __future__ import annotations


def format_progress(record: dict) -> str:
    kind = record.get("kind")
    if kind == "step":
        return f"[{record['index'] + 1}/{record['total']}] {record['label']}"
    if kind == "timed_key":
        return f"定時技能：按 {record['key']}"
    if kind == "fire":
        return f"規則「{record['rule']}」觸發（{record['trigger']}）"
    if kind == "notify":
        return f"通知：{record['message']}"
    if kind == "error":
        return f"錯誤：{record['message']}"
    if kind == "wait_result":
        if record["matched"]:
            return f"等待 #{record['index']} 命中（{record['elapsed_ms']}ms）"
        return f"等待 #{record['index']} 逾時（{record['on_timeout']}）"
    if kind == "branch":
        return f"判斷 #{record['index']} 走 {record['taken']}"
    return str(record)


def format_result(result) -> str:
    """PlayResult → 主日誌收尾列（與 CLI 輸出一致的措辭）。"""
    if result.ok:
        return f"回放完成，共執行 {result.actions_run} 個動作"
    return f"回放中止：{result.error}（已執行 {result.actions_run} 個動作）"


_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
_KIND_LEVEL = {"step": "INFO", "timed_key": "INFO", "fire": "WARNING", "notify": "WARNING",
               "error": "ERROR"}


def should_log(record: dict, level: str) -> bool:
    """依設定 log_level 過濾 progress 記錄；未知 kind 視為 DEBUG。"""
    kind_level = _KIND_LEVEL.get(record.get("kind"), "DEBUG")
    return _LEVEL_ORDER[kind_level] >= _LEVEL_ORDER.get(level, 20)
