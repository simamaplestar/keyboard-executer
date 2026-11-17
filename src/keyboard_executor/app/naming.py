"""名稱工具（純邏輯，無 Qt）。"""
from __future__ import annotations


def unique_copy_name(base: str, existing) -> str:
    """回一個不在 existing 內的複製名：「base - 複製」，衝突則加序號 2、3…。"""
    existing = set(existing)
    candidate = f"{base} - 複製"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{candidate} {n}" in existing:
        n += 1
    return f"{candidate} {n}"


def numbered_name(base: str, existing) -> str:
    """名稱衝突自動加序號：base、base 2、base 3…（AI 提案不覆蓋既有項目）。
    比對不分大小寫：Windows 檔名不分大小寫，farm 會蓋掉 Farm.json。"""
    existing = {name.casefold() for name in existing}
    if base.casefold() not in existing:
        return base
    n = 2
    while f"{base} {n}".casefold() in existing:
        n += 1
    return f"{base} {n}"
