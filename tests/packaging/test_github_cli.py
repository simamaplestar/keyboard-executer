import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def github_cli():
    spec = importlib.util.spec_from_file_location("ke_github_cli", ROOT / "packaging/github_cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def configure(repo):
    subprocess.run(["git", "config", "--local", "keyboardExecutor.githubConfigDir", "github-simamaplestar"],
                   cwd=repo, check=True)


def test_project_auth_uses_private_config_and_keeps_global_environment(github_cli, repo, monkeypatch):
    configure(repo)
    monkeypatch.setenv("GH_CONFIG_DIR", "global-config")
    monkeypatch.setenv("GH_TOKEN", "global-token-fixture")
    monkeypatch.setenv("GITHUB_TOKEN", "global-other-fixture")
    environment = github_cli.project_environment(repo)
    assert environment["GH_CONFIG_DIR"] == str(repo / ".git/github-simamaplestar")
    assert environment["GH_HOST"] == "github.com"
    assert "GH_TOKEN" not in environment and "GITHUB_TOKEN" not in environment
    assert os.environ["GH_CONFIG_DIR"] == "global-config"
    assert os.environ["GH_TOKEN"] == "global-token-fixture"


def test_unconfigured_clone_keeps_existing_auth(github_cli, repo, monkeypatch):
    monkeypatch.setenv("GH_CONFIG_DIR", "existing-config")
    monkeypatch.setenv("GH_TOKEN", "existing-token-fixture")
    environment = github_cli.project_environment(repo)
    assert environment["GH_CONFIG_DIR"] == "existing-config"
    assert environment["GH_TOKEN"] == "existing-token-fixture"


def test_cli_forwards_credential_protocol_arguments_and_exit_code(github_cli, repo):
    configure(repo)
    def run(command, *, env, cwd):
        assert command == ["gh-fixture", "auth", "git-credential", "get"]
        assert env["GH_CONFIG_DIR"] == str(repo / ".git/github-simamaplestar")
        assert cwd == repo
        return SimpleNamespace(returncode=7)
    assert github_cli.main(["auth", "git-credential", "get"], root=repo,
                           which=lambda name: "gh-fixture", run=run) == 7


def test_missing_cli_returns_clear_failure(github_cli, repo, capsys):
    assert github_cli.main(["auth", "status"], root=repo, which=lambda name: None) == 1
    assert "GitHub CLI" in capsys.readouterr().err
