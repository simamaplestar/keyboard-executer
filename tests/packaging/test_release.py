import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ke_release", ROOT / "packaging" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

INIT = '"""pkg"""\n__version__ = "0.5.0"\n'
PYPROJECT = '[build-system]\nrequires = ["x"]\n\n[project]\nname = "keyboard-executor"\nversion = "0.5.0"\n\n[tool.x]\nversion = "9.9.9"\n'


def fake_root(tmp_path):
    (tmp_path / "src" / "keyboard_executor").mkdir(parents=True)
    (tmp_path / "src" / "keyboard_executor" / "__init__.py").write_text(INIT, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "packaging").mkdir()
    return tmp_path


class Runner:
    def __init__(self, root, fail=()):
        self.root = root
        self.fail = list(fail)       # 指令字串片段：符合者回 1
        self.cmds = []

    def __call__(self, cmd, cwd):
        text = " ".join(str(c) for c in cmd)
        self.cmds.append(text)
        if "PyInstaller" in text:     # 模擬打包產出
            dist = self.root / "packaging" / [c for c in cmd if str(c).startswith("dist/")][0]
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "KeyboardExecutor.exe").write_bytes(b"exe-bytes")
        head = " ".join(Path(str(c)).name if i == 0 else str(c) for i, c in enumerate(cmd[:4]))
        for frag in self.fail:
            if frag in head:
                return 1
        return 0


def versions(root):
    return ((root / "src/keyboard_executor/__init__.py").read_text(encoding="utf-8"),
            (root / "pyproject.toml").read_text(encoding="utf-8"))


def test_bump_version_text():
    init, pyproject = release.bump_version_text(INIT, PYPROJECT, "0.6.0")
    assert '__version__ = "0.6.0"' in init
    assert 'version = "0.6.0"' in pyproject
    assert 'version = "9.9.9"' in pyproject          # 其他 table 不動
    assert pyproject.count("0.6.0") == 1


def test_bump_version_text_missing_raises():
    with pytest.raises(SystemExit):
        release.bump_version_text("nothing", PYPROJECT, "0.6.0")


def test_sha256_line(tmp_path):
    exe = tmp_path / "KeyboardExecutor.exe"
    exe.write_bytes(b"abc")
    assert release.sha256_line(exe) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  KeyboardExecutor.exe\n")


def test_rejects_not_newer(tmp_path):
    root = fake_root(tmp_path)
    run = Runner(root)
    assert release.main(["0.5.0", "x"], root=root, run=run) != 0
    assert run.cmds == []


def test_runs_steps_in_order(tmp_path):
    root = fake_root(tmp_path)
    run = Runner(root, fail=["gh repo view"])
    assert release.main(["0.6.0", "修正 A"], root=root, run=run) == 0
    assert "pytest" in run.cmds[0]
    assert "PyInstaller" in run.cmds[1] and "dist/release-0.6.0" in run.cmds[1]
    assert run.cmds[2].endswith("KeyboardExecutor.exe --self-test")
    assert run.cmds[3].startswith("gh repo view simamaplestar/keyboard-executer")
    assert run.cmds[4].startswith("gh repo create simamaplestar/keyboard-executer --public --add-readme")
    assert run.cmds[5].startswith("gh release create v0.6.0 ")
    assert "--repo simamaplestar/keyboard-executer" in run.cmds[5]
    assert "KeyboardExecutor.exe.sha256" in run.cmds[5] and "修正 A" in run.cmds[5]
    assert "release.json" in run.cmds[5]
    import json
    data = json.loads((root / "packaging/dist/release-0.6.0/release.json").read_text(encoding="utf-8"))
    assert data == {"version": "0.6.0", "notes": "修正 A", "size": len(b"exe-bytes")}
    sha = root / "packaging/dist/release-0.6.0/KeyboardExecutor.exe.sha256"
    assert sha.read_text(encoding="utf-8").endswith("  KeyboardExecutor.exe\n")
    assert '"0.6.0"' in versions(root)[0]


def test_existing_repo_not_recreated(tmp_path):
    root = fake_root(tmp_path)
    run = Runner(root)
    assert release.main(["0.6.0", "x"], root=root, run=run) == 0
    assert not any("gh repo create" in c for c in run.cmds)


def test_flaky_test_rerun_once(tmp_path):
    root = fake_root(tmp_path)
    run = Runner(root)
    base = run.__call__

    def flaky(cmd, cwd):
        text = " ".join(str(c) for c in cmd)
        if list(cmd[1:3]) == ["-m", "pytest"] and "--lf" not in cmd:
            run.cmds.append(text)
            return 1
        return base(cmd, cwd)
    assert release.main(["0.6.0", "x"], root=root, run=flaky) == 0
    assert "--lf" in run.cmds[1]


def test_tests_fail_keeps_version(tmp_path):
    root = fake_root(tmp_path)
    before = versions(root)
    run = Runner(root, fail=["pytest"])
    assert release.main(["0.6.0", "x"], root=root, run=run) != 0
    assert versions(root) == before
    assert not any("PyInstaller" in c for c in run.cmds)


def test_upload_fail_reverts_version(tmp_path):
    root = fake_root(tmp_path)
    before = versions(root)
    run = Runner(root, fail=["gh release create"])
    assert release.main(["0.6.0", "x"], root=root, run=run) != 0
    assert versions(root) == before


def test_build_fail_reverts_version(tmp_path):
    root = fake_root(tmp_path)
    before = versions(root)
    run = Runner(root, fail=["PyInstaller"])
    assert release.main(["0.6.0", "x"], root=root, run=run) != 0
    assert versions(root) == before


def test_broken_exe_is_not_uploaded(tmp_path):
    root = fake_root(tmp_path)
    before = versions(root)
    run = Runner(root, fail=["KeyboardExecutor.exe --self-test"])
    assert release.main(["0.6.0", "x"], root=root, run=run) != 0
    assert not any("gh release create" in c for c in run.cmds)
    assert versions(root) == before


def test_build_only_skips_upload(tmp_path):
    root = fake_root(tmp_path)
    run = Runner(root)
    assert release.main(["--build-only", "1.0.0", "正式版"], root=root, run=run) == 0
    assert not any(c.startswith("gh ") for c in run.cmds)
    assert any("--self-test" in c for c in run.cmds)
    assert '"1.0.0"' in versions(root)[0]
    assert (root / "packaging/dist/release-1.0.0/release.json").is_file()


def test_gh_commands_use_project_scoped_authentication(tmp_path, monkeypatch):
    import os
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "--local", "keyboardExecutor.githubConfigDir", "github-simamaplestar"],
                   cwd=tmp_path, check=True)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setenv("GH_CONFIG_DIR", "global-config")
    def run(command, *, cwd, env=None):
        if command[0] == "git":
            return original_run(command, cwd=cwd, env=env, capture_output=True, text=True)
        assert command == ["gh", "repo", "view", "simamaplestar/keyboard-executer"]
        assert env is not None
        assert env["GH_CONFIG_DIR"] == str(tmp_path / ".git/github-simamaplestar")
        return subprocess.CompletedProcess(command, 0)
    original_run = subprocess.run
    # 保留真正的 git config 查詢，只替換外部 gh 程序。
    def boundary(command, **kwargs):
        if command[0] == "gh":
            return run(command, **kwargs)
        return original_run(command, **kwargs)
    monkeypatch.setattr(release.subprocess, "run", boundary)
    assert release._run(["gh", "repo", "view", "simamaplestar/keyboard-executer"], tmp_path) == 0
    assert os.environ["GH_CONFIG_DIR"] == "global-config"
