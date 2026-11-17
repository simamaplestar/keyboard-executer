"""公開發布倉庫的最新版查詢：版本比對、release.json 解析（純 stdlib）。

不走 api.github.com：未登入每小時只有 60 次，共用網路（熱點、宿舍、網咖）很容易
用完（實測發布當天本機就被擋 403）。改下載每版附上的 release.json，
經 github.com/<repo>/releases/latest/download/ 轉址取得，不受 API 額度限制。"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

REPO = "simamaplestar/keyboard-executer"
ASSET_NAME = "KeyboardExecutor.exe"
SHA_NAME = ASSET_NAME + ".sha256"
MANIFEST_NAME = "release.json"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
LATEST_MANIFEST = f"https://github.com/{REPO}/releases/latest/download/{MANIFEST_NAME}"

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(Exception):
    """更新流程中可預期的失敗（網路、格式、驗證、檔案操作）。"""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    notes: str
    exe_url: str
    exe_size: int
    sha_url: str


def user_agent(current: str) -> str:
    return f"KeyboardExecutor/{current}"


def parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(f"版本號格式不正確（應為 X.Y.Z）: {text!r}")
    return tuple(int(part) for part in match.groups())


def is_newer(remote: str, current: str) -> bool:
    return parse_version(remote) > parse_version(current)


def asset_url(version: str, name: str) -> str:
    """指定版本的附件網址（用 tag 固定版本，下載途中發布新版也不會混到）。"""
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def parse_manifest(data: dict) -> ReleaseInfo:
    try:
        version = ".".join(str(n) for n in parse_version(str(data.get("version", ""))))
    except ValueError as e:
        raise UpdateError(str(e)) from e
    size = data.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise UpdateError(f"release.json 的 size 不正確: {size!r}")
    return ReleaseInfo(version, str(data.get("notes") or ""), asset_url(version, ASSET_NAME),
                       size, asset_url(version, SHA_NAME))


def parse_sha256(text: str) -> str:
    parts = text.strip().split()
    value = parts[0].lower() if parts else ""
    if not _SHA_RE.match(value):
        raise UpdateError(f"sha256 檔內容不正確: {text[:80]!r}")
    return value


def fetch_latest(*, current: str, opener=None, timeout: float = 10.0) -> ReleaseInfo:
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(LATEST_MANIFEST, headers={"User-Agent": user_agent(current)})
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as e:      # URLError/HTTPError/timeout 皆為 OSError
        raise UpdateError(f"查詢最新版失敗: {e}") from e
    if not isinstance(data, dict):
        raise UpdateError("查詢最新版失敗: release.json 不是 JSON 物件")
    return parse_manifest(data)
