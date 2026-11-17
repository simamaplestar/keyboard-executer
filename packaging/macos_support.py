"""Mac 建置前置檢查；只用標準函式庫，在安裝原生套件前也能執行。"""
from __future__ import annotations

import platform
import sys


def validate_host(*, platform_name: str, machine: str, mac_version: str,
                  python_version: tuple[int, ...]) -> None:
    if platform_name != "darwin":
        raise ValueError("macOS .app 必須在原生 Mac 建置，Windows／WSL 無法交叉打包。")
    if machine != "arm64":
        raise ValueError("需要原生 Apple Silicon arm64 Python；不支援 Intel 或 Rosetta。")
    try:
        major = int(mac_version.split(".")[0])
    except ValueError:
        major = 0
    if major < 14:
        raise ValueError("需要 macOS 14 以上（ONNX Runtime 1.30.0 的最低需求）。")
    if python_version < (3, 11):
        raise ValueError("需要 Python 3.11 以上。")


def main() -> int:
    try:
        validate_host(platform_name=sys.platform, machine=platform.machine(),
                      mac_version=platform.mac_ver()[0], python_version=sys.version_info[:2])
    except ValueError as exc:
        print(f"無法建置：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
