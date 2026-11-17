import pytest
from pynput.keyboard import Key, KeyCode

from keyboard_executor.platforms.common.keymap import key_to_name, parse_combo, parse_key


def test_parse_special_keys():
    assert parse_key("ctrl") is Key.ctrl
    assert parse_key("enter") is Key.enter
    assert parse_key("f9") is Key.f9
    assert parse_key("pageup") is Key.page_up


def test_parse_key_aliases():
    assert parse_key("control") is Key.ctrl
    assert parse_key("return") is Key.enter
    assert parse_key("option") is Key.alt
    assert parse_key("win") is Key.cmd


def test_parse_key_is_case_insensitive_and_strips():
    assert parse_key(" F10 ") is Key.f10
    assert parse_key("CTRL") is Key.ctrl


def test_parse_single_char():
    assert parse_key("a") == KeyCode.from_char("a")
    assert parse_key("1") == KeyCode.from_char("1")


def test_parse_unknown_key_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_key("notakey")


def test_parse_combo_from_string():
    assert parse_combo("ctrl+shift+s") == [Key.ctrl, Key.shift, KeyCode.from_char("s")]


def test_parse_combo_from_list():
    assert parse_combo(["cmd", "q"]) == [Key.cmd, KeyCode.from_char("q")]


def test_parse_combo_empty_string_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_combo("")


def test_parse_combo_trailing_plus_raises():
    with pytest.raises(ValueError, match="無法辨識的按鍵名稱"):
        parse_combo("ctrl+")


def test_special_names_match_keynames_authority():
    from keyboard_executor.core.keynames import SPECIAL_KEY_NAMES
    from keyboard_executor.platforms.common.keymap import NUMPAD_VK, _SPECIAL, UNSUPPORTED_KEYS
    # numpad 不在 _SPECIAL（pynput 沒有 numpad 專屬 Key，改用 vk），兩者聯集才是全集
    assert set(_SPECIAL) | set(NUMPAD_VK) | UNSUPPORTED_KEYS == SPECIAL_KEY_NAMES


def test_every_authoritative_name_parses_and_round_trips():
    """名單裡的每個名稱都要能 parse，且轉回名稱時得到自己。

    錄製→存檔→回放整條路徑靠這個往返一致性；任一端漏掉某個鍵，錄到的動作就會
    在載入驗證或回放時失效。
    """
    from keyboard_executor.core.keynames import SPECIAL_KEY_NAMES
    from keyboard_executor.platforms.common.keymap import UNSUPPORTED_KEYS
    for name in sorted(SPECIAL_KEY_NAMES - UNSUPPORTED_KEYS):
        key = parse_key(name)
        got = key_to_name(key)
        # 別名（control/return/escape/option/win/super）會正規化成 canonical 名
        assert got is not None, f"{name} 無法反查回名稱"
        assert parse_key(got) == key, f"{name} → {got} 往返不一致"


def test_numpad_is_distinct_from_main_row_digits():
    from keyboard_executor.platforms.common.keymap import NUMPAD_VK
    assert parse_key("num7") != parse_key("7")
    assert key_to_name(parse_key("num7")) == "num7"
    assert key_to_name(parse_key("7")) == "7"
    # 主鍵盤字母/數字的 vk 不得落在 numpad vk 範圍內，否則會被誤判成 numpad
    assert not ({KeyCode.from_char(c).vk for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
                - {None}) & set(NUMPAD_VK.values())


def test_newly_added_special_keys_parse():
    if not hasattr(Key, "insert"):
        pytest.skip("此平台沒有 Windows 系統鍵")
    assert parse_key("insert") is Key.insert
    assert parse_key("capslock") is Key.caps_lock
    assert parse_key("printscreen") is Key.print_screen
    assert parse_key("menu") is Key.menu
    assert key_to_name(Key.insert) == "insert"
    assert key_to_name(Key.num_lock) == "numlock"


def test_key_to_name_modifier_variants_collapse_to_canonical():
    assert key_to_name(Key.ctrl_l) == "ctrl"
    assert key_to_name(Key.ctrl_r) == "ctrl"
    assert key_to_name(Key.shift_r) == "shift"
    assert key_to_name(Key.alt_gr) == "alt"
    assert key_to_name(Key.cmd_r) == "cmd"


def test_key_to_name_special_keys_use_canonical_names():
    assert key_to_name(Key.f9) == "f9"
    assert key_to_name(Key.enter) == "enter"
    assert key_to_name(Key.esc) == "esc"
    assert key_to_name(Key.page_up) == "pageup"


def test_key_to_name_char_lowercases():
    assert key_to_name(KeyCode.from_char("A")) == "a"
    assert key_to_name(KeyCode.from_char("1")) == "1"


def test_key_to_name_unknown_returns_none():
    assert key_to_name(Key.media_play_pause) is None
    assert key_to_name(KeyCode(vk=255)) is None
    assert key_to_name(None) is None


def test_key_to_name_round_trips_with_parse_key():
    for key in (Key.ctrl, Key.shift, Key.alt, Key.cmd, Key.enter, Key.esc,
                Key.tab, Key.space, Key.page_up, Key.f1, Key.f20):
        assert parse_key(key_to_name(key)) is key
    assert parse_key(key_to_name(KeyCode.from_char("a"))) == KeyCode.from_char("a")


def test_key_to_name_folds_control_char_from_ctrl_combo():
    assert key_to_name(KeyCode.from_char("\x13")) == "s"  # Ctrl+S 回報的控制字元
    assert key_to_name(KeyCode.from_char("\x01")) == "a"


def test_key_to_name_non_printable_returns_none():
    assert key_to_name(KeyCode.from_char("\x7f")) is None  # DEL，非控制區間也非可列印


def test_key_to_name_family_heads_are_canonical():
    assert key_to_name(Key.ctrl) == "ctrl"
    assert key_to_name(Key.shift) == "shift"
    assert key_to_name(Key.alt) == "alt"
    assert key_to_name(Key.cmd) == "cmd"
