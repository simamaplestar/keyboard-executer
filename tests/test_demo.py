import pytest

from keyboard_executor.demo import build_parser, choose_window
from keyboard_executor.platforms.base import WindowInfo


def make_window(title, app="App"):
    return WindowInfo(handle=object(), title=title, app_name=app,
                      x=0, y=0, width=100, height=100, is_active=False)


def test_parser_title_is_optional():
    args = build_parser().parse_args([])
    assert args.title is None


def test_parser_parses_title_and_game_input():
    args = build_parser().parse_args(["--title", "記事本.*", "--game-input"])
    assert args.title == "記事本.*"
    assert args.game_input is True


def test_game_input_defaults_false():
    args = build_parser().parse_args(["--title", "x"])
    assert args.game_input is False


def test_choose_window_picks_by_number():
    w1, w2 = make_window("記事本"), make_window("瀏覽器")
    picked = choose_window([w1, w2], ask=lambda _: "2", echo=lambda _: None)
    assert picked is w2


def test_choose_window_lists_candidates_with_index_and_app():
    outputs = []
    choose_window([make_window("記事本", app="Notepad")], ask=lambda _: "1", echo=outputs.append)
    assert any("1" in line and "記事本" in line and "Notepad" in line for line in outputs)


def test_choose_window_q_cancels():
    picked = choose_window([make_window("A")], ask=lambda _: "q", echo=lambda _: None)
    assert picked is None


def test_choose_window_reprompts_until_valid():
    answers = iter(["abc", "99", "0", "1"])
    w = make_window("A")
    picked = choose_window([w], ask=lambda _: next(answers), echo=lambda _: None)
    assert picked is w


def test_choose_window_skips_untitled_windows():
    w = make_window("有標題")
    picked = choose_window([make_window(""), make_window("   "), w],
                           ask=lambda _: "1", echo=lambda _: None)
    assert picked is w


def test_choose_window_returns_none_when_no_candidates():
    picked = choose_window([make_window("")], ask=lambda _: "1", echo=lambda _: None)
    assert picked is None
