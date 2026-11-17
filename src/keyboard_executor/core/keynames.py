"""按鍵名稱權威名單（純資料，不依賴 pynput）。

core 層（models 載入驗證、recorder）與 platforms 層（keymap 映射）共用此名單，
確保「載入時驗證通過的名稱」與「keymap 能映射的名稱」一致
（tests/platforms/test_keymap.py 以集合相等測試鎖定）。新增按鍵時兩邊都要改。
"""
from __future__ import annotations

_MODIFIERS = frozenset({"ctrl", "control", "shift", "alt", "option", "cmd", "win", "super"})

_NAVIGATION = frozenset({
    "enter", "return", "esc", "escape", "tab", "space", "backspace", "delete",
    "insert", "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
})

# 切換鍵與系統鍵（pynput 有對應 Key、pydirectinput 也認得的那些）
_TOGGLES = frozenset({
    "capslock", "numlock", "scrolllock", "printscreen", "pause", "menu",
})

_FUNCTION = frozenset(f"f{i}" for i in range(1, 21))

# 數字鍵盤：與主鍵盤數字是不同的實體鍵，遊戲常分別綁定，故獨立命名。
# NumLock 開啟時作業系統對兩者回報相同字元，錄製端只能靠 vk 區分
# （見 platforms/common/keymap.py 的 _NUMPAD_VK_TO_NAME）。
_NUMPAD = frozenset(
    [f"num{i}" for i in range(10)] + ["num+", "num-", "num*", "num/", "num."]
)

SPECIAL_KEY_NAMES: frozenset[str] = (
    _MODIFIERS | _NAVIGATION | _TOGGLES | _FUNCTION | _NUMPAD
)


def is_valid_key(name: str) -> bool:
    """strip+lower 後在名單內，或為單一「可列印」字元，即為合法按鍵名稱。"""
    n = name.strip().lower()
    return n in SPECIAL_KEY_NAMES or (len(n) == 1 and n.isprintable())
