"""Discord webhook 通知（純傳輸，無 Qt、無平台差異，可完整單元測試）。

只用 stdlib（urllib/threading/json），不新增依賴。傳輸例外由呼叫端隔離。"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request

logger = logging.getLogger(__name__)

_MAX_LEN = 2000   # Discord 訊息內容上限
# Discord 在 Cloudflare 後面，會擋 urllib 預設的 "Python-urllib/x.y" User-Agent（回
# 403 Forbidden）。自帶一個產品 UA 才能通過（Discord 也要求請求帶 User-Agent）。
_USER_AGENT = "KeyboardExecutor/1.0"
_BOUNDARY = "----KeyboardExecutorBoundary"


def _build_request(url: str, data: bytes,
                   content_type: str = "application/json") -> urllib.request.Request:
    return urllib.request.Request(
        url, data=data,
        headers={"Content-Type": content_type, "User-Agent": _USER_AGENT})


def _urllib_post(url: str, data: bytes, timeout: float,
                 content_type: str = "application/json") -> None:
    urllib.request.urlopen(_build_request(url, data, content_type), timeout=timeout).close()


def _build_multipart(content: str, image_png: bytes) -> bytes:
    """組 Discord webhook 的 multipart/form-data：payload_json + files[0]=screenshot.png。"""
    b = _BOUNDARY
    payload = json.dumps({"content": content[:_MAX_LEN]}).encode("utf-8")
    return b"".join([
        f"--{b}\r\n".encode(),
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        payload,
        f"\r\n--{b}\r\n".encode(),
        b'Content-Disposition: form-data; name="files[0]"; filename="screenshot.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        image_png,
        f"\r\n--{b}--\r\n".encode(),
    ])


def post_discord(webhook_url: str, content: str, *, image_png: bytes | None = None,
                 poster=None, timeout: float = 5.0) -> None:
    """POST 到 webhook：有 image_png 走 multipart（附截圖），否則 JSON。poster 注入供測試。"""
    poster = poster or _urllib_post
    if image_png is None:
        body = json.dumps({"content": content[:_MAX_LEN]}).encode("utf-8")
        poster(webhook_url, body, timeout, "application/json")
    else:
        body = _build_multipart(content, image_png)
        poster(webhook_url, body, timeout, f"multipart/form-data; boundary={_BOUNDARY}")


def _daemon_dispatch(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _safe_send(sender, webhook_url: str, content: str, image_png: bytes | None = None) -> None:
    try:
        sender(webhook_url, content, image_png=image_png)
    except Exception:
        # 不記 webhook 網址與內容，只記事實（spec §8）；注入的 sender 之例外訊息
        # 也不得含網址/內容，否則 exc_info=True 會連帶洩漏。網路/HTTP 失敗不得中斷監看。
        logger.warning("Discord 通知傳送失敗", exc_info=True)


def make_notifier(base_notifier, webhook_url: str, *, dispatch=None,
                  sender=post_discord):
    """把「只進 GUI」的 notifier 包成扇出：先 base_notifier，再（有 webhook 時）
    非同步送原訊息到 Discord。dispatch/sender 注入供測試，預設 daemon thread。"""
    dispatch = dispatch or _daemon_dispatch

    def notify(message: str, *, image_png: bytes | None = None) -> None:
        base_notifier(message)
        if webhook_url:
            dispatch(lambda: _safe_send(sender, webhook_url, message, image_png))

    return notify
