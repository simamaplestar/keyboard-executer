import io
import json
import urllib.error

import pytest

from keyboard_executor.core.update.release import (
    ASSET_NAME, LATEST_MANIFEST, MANIFEST_NAME, RELEASES_PAGE, REPO, SHA_NAME, ReleaseInfo,
    UpdateError, asset_url, fetch_latest, is_newer, parse_manifest, parse_sha256, parse_version,
)

HEX = "ab" * 32


def manifest(**kw):
    data = {"version": "0.6.0", "notes": "修正", "size": 123}
    data.update(kw)
    return data


def test_constants():
    assert REPO == "simamaplestar/keyboard-executer"
    assert SHA_NAME == "KeyboardExecutor.exe.sha256"
    assert RELEASES_PAGE == "https://github.com/simamaplestar/keyboard-executer/releases/latest"
    assert MANIFEST_NAME == "release.json"
    # 不走 api.github.com（未登入每小時 60 次，共用網路容易用完）
    assert LATEST_MANIFEST == (
        "https://github.com/simamaplestar/keyboard-executer/releases/latest/download/release.json")
    assert asset_url("0.6.1", ASSET_NAME) == (
        "https://github.com/simamaplestar/keyboard-executer/releases/download/v0.6.1/KeyboardExecutor.exe")


def test_version_compare():
    assert parse_version("v0.6.0") == (0, 6, 0)
    assert is_newer("0.6.0", "0.5.10") is True
    assert is_newer("0.5.10", "0.5.9") is True
    assert is_newer("v1.0.0", "0.9.9") is True
    assert is_newer("0.5.0", "0.5.0") is False
    assert is_newer("0.4.9", "0.5.0") is False
    with pytest.raises(ValueError):
        parse_version("0.6")
    with pytest.raises(ValueError):
        parse_version("0.6.x")


def test_parse_manifest_builds_tag_urls():
    assert parse_manifest(manifest()) == ReleaseInfo(
        "0.6.0", "修正",
        "https://github.com/simamaplestar/keyboard-executer/releases/download/v0.6.0/KeyboardExecutor.exe",
        123,
        "https://github.com/simamaplestar/keyboard-executer/releases/download/v0.6.0/KeyboardExecutor.exe.sha256")


def test_parse_manifest_missing_notes_is_empty():
    data = manifest()
    del data["notes"]
    assert parse_manifest(data).notes == ""


def test_parse_manifest_bad_version_or_size_raises():
    with pytest.raises(UpdateError):
        parse_manifest(manifest(version="latest"))
    with pytest.raises(UpdateError):
        parse_manifest(manifest(size="big"))
    with pytest.raises(UpdateError):
        parse_manifest(manifest(size=0))


def test_parse_sha256_formats():
    assert parse_sha256(HEX) == HEX
    assert parse_sha256(HEX.upper() + "  KeyboardExecutor.exe\n") == HEX
    with pytest.raises(UpdateError):
        parse_sha256("xyz")
    with pytest.raises(UpdateError):
        parse_sha256("")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_fetch_latest_parses_and_sends_user_agent():
    seen = {}

    def opener(request, timeout):
        seen["ua"] = request.get_header("User-agent")
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return FakeResponse(json.dumps(manifest()).encode())

    info = fetch_latest(current="0.5.0", opener=opener)
    assert info.version == "0.6.0"
    assert seen["ua"] == "KeyboardExecutor/0.5.0"
    assert seen["url"] == (
        "https://github.com/simamaplestar/keyboard-executer/releases/latest/download/release.json")
    assert seen["timeout"] == 10.0


def test_fetch_latest_wraps_http_error():
    def opener(request, timeout):
        raise urllib.error.URLError("offline")
    with pytest.raises(UpdateError, match="offline"):
        fetch_latest(current="0.5.0", opener=opener)


def test_fetch_latest_wraps_bad_json():
    def opener(request, timeout):
        return FakeResponse(b"<html>")
    with pytest.raises(UpdateError):
        fetch_latest(current="0.5.0", opener=opener)
