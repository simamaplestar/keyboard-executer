"""版本單一來源（pyproject ↔ __init__）與 CLI --version（M5 發布識別）。"""
import tomllib
from pathlib import Path

import pytest

import keyboard_executor
from keyboard_executor.cli import main


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == keyboard_executor.__version__
    # 版本號由 packaging/release.py 每次發布遞增，這裡只檢查格式（X.Y.Z）
    from keyboard_executor.core.update.release import parse_version
    parse_version(keyboard_executor.__version__)


def test_cli_version_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"keyboard-executor {keyboard_executor.__version__}" in out
