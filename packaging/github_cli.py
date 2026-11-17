"""專案專用 GitHub CLI 入口；可供 Git credential helper 與發布腳本共用。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CONFIG_KEY = "keyboardExecutor.githubConfigDir"


def project_environment(root: Path = ROOT) -> dict[str, str]:
    environment = os.environ.copy()
    configured = subprocess.run(
        ["git", "config", "--local", "--get", CONFIG_KEY], cwd=root,
        capture_output=True, text=True, check=False,
    )
    value = configured.stdout.strip()
    if configured.returncode != 0 or not value:
        return environment
    config_dir = Path(value)
    if not config_dir.is_absolute():
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True,
        ).strip()
        config_dir = (root / common / config_dir).resolve()
    environment["GH_CONFIG_DIR"] = str(config_dir)
    environment["GH_HOST"] = "github.com"
    # gh 的環境 token 優先於帳號設定；只在本子程序移除，確保使用專案指定登入。
    environment.pop("GH_TOKEN", None)
    environment.pop("GITHUB_TOKEN", None)
    return environment


def main(argv=None, *, root: Path = ROOT, which=shutil.which, run=subprocess.run) -> int:
    executable = which("gh") or which("gh.exe")
    if executable is None:
        print("找不到 GitHub CLI，請先安裝 gh。", file=sys.stderr)
        return 1
    return run([executable, *(sys.argv[1:] if argv is None else argv)],
               cwd=root, env=project_environment(root)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
