"""AI 示範錄製的 session 目錄：截圖、timeline.json、每一輪的腳本版本。"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


class AiDemoSessionStore:
    def __init__(self, root: str | Path, keep: int = 10):
        self._dir = Path(root) / "ai_demos"
        self._keep = max(1, keep)

    def create(self) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        while True:
            ns = time.time_ns()
            # 固定寬度：名稱字典序 = 建立先後
            name = time.strftime("%Y%m%d-%H%M%S", time.localtime(ns / 1e9)) + f"-{ns % 10**9:09d}"
            if not (self._dir / name).exists():
                break
        session = self._dir / name
        session.mkdir()
        self._cleanup(keep_also=session)
        return session

    def _cleanup(self, keep_also: Path) -> None:
        sessions = sorted((p for p in self._dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        for old in sessions[:-self._keep]:
            if old != keep_also:
                shutil.rmtree(old, ignore_errors=True)

    def save_timeline(self, session: Path, data: dict) -> None:
        (session / "timeline.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_version(self, session: Path, version: int, data: dict) -> None:
        (session / f"round_{version}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_version(self, session: Path, version: int) -> dict:
        return json.loads((session / f"round_{version}.json").read_text(encoding="utf-8"))

    def versions(self, session: Path) -> list[int]:
        out = []
        for path in session.glob("round_*.json"):
            try:
                out.append(int(path.stem.split("_", 1)[1]))
            except ValueError:
                continue
        return sorted(out)
