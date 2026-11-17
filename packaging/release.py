"""發布新版到公開倉庫（朋友的程式會從這裡自動更新）。

用法（Windows PowerShell）：
    packaging\\release.ps1 0.6.0 "這版改了什麼"
    packaging\\release.ps1 --build-only 1.0.0 "這版改了什麼"   # 只打包訂版，不上傳

步驟：版本號必須大於目前版本 → 完整測試（失敗的測試重跑一次，仍失敗就停）
→ 改版本號 → 打包到 packaging/dist/release-<版本>/ → 產生 .sha256 與 release.json
→ 公開倉庫不存在就建立 → 建立 GitHub Release 並上傳 EXE 與 .sha256。
打包或上傳失敗會把版本號改回原值。不執行原始碼的 git 提交或推送。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

from github_cli import project_environment  # noqa: E402

from keyboard_executor.core.update.release import (  # noqa: E402
    ASSET_NAME, MANIFEST_NAME, REPO, SHA_NAME, is_newer, parse_version,
)

_INIT_RE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
_PROJECT_RE = re.compile(r'(\[project\][^\[]*?^version = ")([^"]+)(")', re.M | re.S)


def _run(cmd, cwd) -> int:
    print(">", " ".join(str(c) for c in cmd), flush=True)
    options = {"env": project_environment(ROOT)} if str(cmd[0]) == "gh" else {}
    return subprocess.run([str(c) for c in cmd], cwd=cwd, **options).returncode


def bump_version_text(init_text: str, pyproject_text: str, new: str) -> tuple[str, str]:
    init, n1 = _INIT_RE.subn(f'__version__ = "{new}"', init_text, count=1)
    pyproject, n2 = _PROJECT_RE.subn(lambda m: f"{m.group(1)}{new}{m.group(3)}",
                                     pyproject_text, count=1)
    if n1 != 1 or n2 != 1:
        raise SystemExit("找不到版本號（__init__.py 的 __version__ 或 pyproject.toml 的 [project] version）")
    return init, pyproject


def sha256_line(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return f"{digest.hexdigest()}  {ASSET_NAME}\n"


def main(argv=None, *, root: Path = ROOT, run=_run) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    build_only = "--build-only" in argv
    argv = [a for a in argv if a != "--build-only"]
    if len(argv) != 2:
        print('用法：release.ps1 <版本 X.Y.Z> "<更新說明>"')
        return 2
    version, notes = argv[0].lstrip("v"), argv[1]
    init_path = root / "src" / "keyboard_executor" / "__init__.py"
    pyproject_path = root / "pyproject.toml"
    init_text = init_path.read_text(encoding="utf-8")
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    match = _INIT_RE.search(init_text)
    current = match.group(1) if match else "0.0.0"
    try:
        parse_version(version)
        if not is_newer(version, current):
            print(f"發布失敗：新版本 {version} 必須大於目前版本 {current}")
            return 2
    except ValueError as e:
        print(f"發布失敗：{e}")
        return 2

    python = sys.executable
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    print(f"[1/5] 完整測試（約 8 分鐘）", flush=True)
    if run([python, "-m", "pytest", "-q"], root) != 0:
        print("有測試失敗，重跑失敗的測試一次…", flush=True)
        if run([python, "-m", "pytest", "-q", "--lf"], root) != 0:
            print("發布失敗：測試沒有通過，版本號未變更")
            return 1

    def revert(reason: str) -> int:
        init_path.write_text(init_text, encoding="utf-8")
        pyproject_path.write_text(pyproject_text, encoding="utf-8")
        print(f"發布失敗：{reason}；版本號已改回 {current}")
        return 1

    print(f"[2/5] 版本號 {current} → {version}", flush=True)
    new_init, new_pyproject = bump_version_text(init_text, pyproject_text, version)
    init_path.write_text(new_init, encoding="utf-8")
    pyproject_path.write_text(new_pyproject, encoding="utf-8")

    print("[3/5] 打包", flush=True)
    dist = f"dist/release-{version}"
    if run([python, "-m", "PyInstaller", "--noconfirm", "--distpath", dist,
            "--workpath", "build/keyboard-executor", "keyboard-executor.spec"],
           root / "packaging") != 0:
        return revert("打包失敗")
    exe = root / "packaging" / dist / ASSET_NAME
    if not exe.is_file():
        return revert(f"找不到打包結果 {exe}")
    sha = exe.with_name(SHA_NAME)
    sha.write_text(sha256_line(exe), encoding="utf-8")
    manifest = exe.with_name(MANIFEST_NAME)    # 朋友的程式靠它判斷新版（不走 GitHub API 額度）
    manifest.write_text(json.dumps({"version": version, "notes": notes,
                                    "size": exe.stat().st_size}, ensure_ascii=False),
                        encoding="utf-8")
    print("      啟動打包好的程式做自我檢查", flush=True)
    if run([exe, "--self-test"], root) != 0:
        return revert("打包好的程式自我檢查失敗（不會上傳）")

    if build_only:
        print(f"完成（只打包，未上傳）：v{version} → {exe}")
        return 0

    print("[4/5] 確認公開倉庫", flush=True)
    if run(["gh", "repo", "view", REPO], root) != 0:
        if run(["gh", "repo", "create", REPO, "--public", "--add-readme",
                "--description", "Keyboard Executor 發布版"], root) != 0:
            return revert("建立公開倉庫失敗（是否已執行 gh auth login？）")

    print("[5/5] 上傳新版", flush=True)
    if run(["gh", "release", "create", f"v{version}", exe, sha, manifest, "--repo", REPO,
            "--title", f"v{version}", "--notes", notes], root) != 0:
        return revert("上傳失敗（是否已執行 gh auth login？）")
    print(f"完成：v{version} 已發布 → https://github.com/{REPO}/releases/tag/v{version}")
    print(f"本機檔案：{exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
