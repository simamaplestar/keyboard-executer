"""顯式準備所有 OCR 共用的 PP-OCRv6 tiny 模型；app 與 PyInstaller 不下載。

工具沿用舊檔名與快取目錄，相容既有指令；不再限於聊天。

在專案根目錄執行：python packaging/prepare_chat_ocr_models.py
已有下載檔可加 --source-dir <目錄>，完全不連網。
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from keyboard_executor.platforms.common.ocr_rapid import (  # noqa: E402
    RAPID_MODEL_FILES,
    RAPID_MODEL_SHA256,
    RAPID_MODEL_URLS,
    default_model_dir,
)


def _verify(path: Path, filename: str) -> None:
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    expected = RAPID_MODEL_SHA256[filename]
    if actual != expected:
        raise ValueError(
            f"{filename} SHA256 不符：{path}\n"
            f"預期 {expected}，實際 {actual}。請移除錯誤檔案後重新準備。"
        )


def prepare_models(
    source_dir: Path | None = None, destination: Path | None = None,
) -> list[Path]:
    """重用已驗證快取，或將來源模型原子寫入 app 共用目錄。"""
    destination = Path(destination) if destination is not None else default_model_dir()
    source_dir = Path(source_dir) if source_dir is not None else None
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for filename in RAPID_MODEL_FILES:
        target = destination / filename
        if target.exists():
            _verify(target, filename)
            result.append(target)
            continue

        # 與目標同目錄，讓 os.replace 在同一檔案系統中原子發布；Windows 需先關檔。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination, prefix=f".{filename}.", suffix=".tmp", delete=False,
            ) as output:
                temporary = Path(output.name)
                source = (
                    (source_dir / filename).open("rb") if source_dir is not None
                    else urllib.request.urlopen(RAPID_MODEL_URLS[filename], timeout=60)
                )
                with source:
                    shutil.copyfileobj(source, output)
            _verify(temporary, filename)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        result.append(target)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="從本機目錄複製模型，不連網")
    parser.add_argument("--model-dir", type=Path, help="指定目的目錄；預設使用 app 的模型快取")
    args = parser.parse_args(argv)
    try:
        paths = prepare_models(source_dir=args.source_dir, destination=args.model_dir)
    except (OSError, ValueError) as exc:
        print(f"OCR 模型準備失敗：{exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(f"SHA256 已驗證：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
