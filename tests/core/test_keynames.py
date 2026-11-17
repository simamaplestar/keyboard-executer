from keyboard_executor.core.keynames import SPECIAL_KEY_NAMES, is_valid_key


def test_contains_modifiers_and_aliases():
    for name in ("ctrl", "control", "shift", "alt", "option", "cmd", "win", "super"):
        assert name in SPECIAL_KEY_NAMES


def test_contains_navigation_and_editing_keys():
    for name in ("enter", "return", "esc", "escape", "tab", "space", "backspace",
                 "delete", "home", "end", "pageup", "pagedown", "up", "down", "left", "right"):
        assert name in SPECIAL_KEY_NAMES


def test_contains_f1_to_f20_only():
    for i in range(1, 21):
        assert f"f{i}" in SPECIAL_KEY_NAMES
    assert "f21" not in SPECIAL_KEY_NAMES
    assert "f0" not in SPECIAL_KEY_NAMES


def test_is_valid_key_strips_and_lowercases():
    assert is_valid_key(" F10 ") is True
    assert is_valid_key("CTRL") is True


def test_single_char_is_valid():
    assert is_valid_key("a") is True
    assert is_valid_key("1") is True
    assert is_valid_key("哈") is True  # 單一字元一律合法（KeyCode.from_char 可送出）


def test_unknown_names_are_invalid():
    assert is_valid_key("entr") is False
    assert is_valid_key("") is False
    assert is_valid_key("notakey") is False
