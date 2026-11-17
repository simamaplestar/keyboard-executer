from pathlib import Path

import pytest

from keyboard_executor.cli import build_parser, default_scripts_dir


def test_play_parses_name_and_dir():
    args = build_parser().parse_args(["play", "簽到", "--dir", "/tmp/s"])
    assert args.command == "play"
    assert args.name == "簽到"
    assert args.dir == "/tmp/s"


def test_dir_defaults_to_none():
    args = build_parser().parse_args(["play", "x"])
    assert args.dir is None


def test_list_subcommand():
    args = build_parser().parse_args(["list"])
    assert args.command == "list"


def test_command_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_default_scripts_dir_under_home():
    d = default_scripts_dir()
    assert d == Path.home() / ".keyboard-executor" / "scripts"


def test_record_parses_dir_title_and_full_trajectory():
    args = build_parser().parse_args(
        ["record", "--dir", "/tmp/s", "--title", "記事本.*", "--full-trajectory"])
    assert args.command == "record"
    assert args.dir == "/tmp/s"
    assert args.title == "記事本.*"
    assert args.full_trajectory is True


def test_record_defaults():
    args = build_parser().parse_args(["record"])
    assert args.dir is None
    assert args.title is None
    assert args.full_trajectory is False
