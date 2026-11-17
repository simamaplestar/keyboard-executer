import json
import logging

from keyboard_executor.core.discord_notify import make_notifier, post_discord


def test_post_discord_posts_content_json_to_url():
    captured = {}

    def fake_poster(url, data, timeout, content_type):
        captured["url"] = url
        captured["data"] = data
        captured["timeout"] = timeout

    post_discord("https://discord.com/api/webhooks/1/a", "嗨", poster=fake_poster)
    assert captured["url"] == "https://discord.com/api/webhooks/1/a"
    assert json.loads(captured["data"].decode("utf-8")) == {"content": "嗨"}
    assert captured["timeout"] == 5.0


def test_post_discord_truncates_to_2000_chars():
    captured = {}
    post_discord("https://x/webhooks/1/a", "x" * 5000,
                 poster=lambda u, d, t, c: captured.setdefault("data", d))
    assert len(json.loads(captured["data"].decode("utf-8"))["content"]) == 2000


def test_make_notifier_no_webhook_only_calls_base():
    calls = []
    n = make_notifier(lambda m: calls.append(("base", m)), "",
                      dispatch=lambda fn: fn(),
                      sender=lambda *a: calls.append(("send", a)))
    n("嗨")
    assert calls == [("base", "嗨")]          # 無 webhook → 不送 Discord


def test_make_notifier_with_webhook_sends_raw_message():
    # 只送原訊息，不附加時間戳。
    sent = []
    n = make_notifier(lambda m: None, "https://discord.com/api/webhooks/1/a",
                      dispatch=lambda fn: fn(),
                      sender=lambda url, content, image_png=None: sent.append((url, content)))
    n("驗證碼出現了")
    assert sent == [("https://discord.com/api/webhooks/1/a", "驗證碼出現了")]


def test_make_notifier_send_failure_is_isolated(caplog):
    calls = []

    def boom(*a, **k):
        raise RuntimeError("網路掛了")

    n = make_notifier(lambda m: calls.append(m),
                      "https://discord.com/api/webhooks/1/a",
                      dispatch=lambda fn: fn(), sender=boom)
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        n("嗨")                                # 不應拋例外
    assert calls == ["嗨"]                     # base 仍執行
    assert "Discord" in caplog.text            # 失敗有記 log
    assert "https://discord.com" not in caplog.text   # log 不得洩漏 webhook 網址
    assert "嗨" not in caplog.text                      # log 不得洩漏訊息內容


def test_make_notifier_does_not_leak_url_on_httperror(caplog):
    import urllib.error
    url = "https://discord.com/api/webhooks/1/secret"

    def raising_sender(webhook_url, content, image_png=None):
        raise urllib.error.HTTPError(url=webhook_url, code=404, msg="Not Found",
                                     hdrs=None, fp=None)

    n = make_notifier(lambda m: None, url, dispatch=lambda fn: fn(),
                      sender=raising_sender)
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        n("嗨")                              # 不應拋例外
    assert url not in caplog.text            # 即使真實 HTTPError 帶 url 也不得洩漏
    assert "/secret" not in caplog.text


def test_urllib_request_sets_user_agent_to_avoid_403():
    # Discord/Cloudflare 會擋 urllib 預設的 "Python-urllib/x.y" User-Agent（回 403），
    # 必須自帶 User-Agent。此測 _build_request 帶對的標頭（不觸網路）。
    from keyboard_executor.core.discord_notify import _build_request
    req = _build_request("https://discord.com/api/webhooks/1/a", b"{}")
    ua = req.get_header("User-agent")
    assert ua and "urllib" not in ua.lower()          # 有帶 UA、且非 urllib 預設
    assert req.get_header("Content-type") == "application/json"


def test_post_discord_with_image_sends_multipart():
    captured = {}

    def poster(url, data, timeout, content_type):
        captured["data"] = data
        captured["content_type"] = content_type

    post_discord("https://x/webhooks/1/a", "嗨", image_png=b"\x89PNGdata",
                 poster=poster)
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="payload_json"' in captured["data"]
    assert b'filename="screenshot.png"' in captured["data"]
    assert b"\x89PNGdata" in captured["data"]           # 影像 bytes 有進 body


def test_make_notifier_forwards_image_png_to_sender():
    sent = []
    n = make_notifier(lambda m: None, "https://x/webhooks/1/a",
                      dispatch=lambda fn: fn(),
                      sender=lambda url, content, image_png=None: sent.append(image_png))
    n("嗨", image_png=b"PNGDATA")
    assert sent == [b"PNGDATA"]
