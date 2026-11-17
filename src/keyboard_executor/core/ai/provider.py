"""AI 供應商抽象層（純 stdlib：urllib/json，無 Qt、不新增依賴）。

ChatProvider.stream_chat 是唯一介面：messages 用內部通用格式
[{"role": "user"|"assistant", "content": str}, ...]，各實作自行轉自家 payload。
SSE 逐行讀取，on_delta 即時回吐文字；should_abort 於行間檢查（True → AiAborted）。
傳輸/HTTP 例外一律包成 AiProviderError（繁中訊息），由呼叫端（Worker job）隔離。"""
from __future__ import annotations

import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

_USER_AGENT = "KeyboardExecutor/1.0"


class AiProviderError(Exception):
    """AI 供應商呼叫失敗（訊息為繁中、可直接顯示）。"""


class AiAborted(Exception):
    """使用者中止串流。"""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_call: ToolCall | None = None


class ChatProvider(ABC):
    @abstractmethod
    def stream_chat(self, messages: list[dict], *, system: str,
                    tools: list[dict], on_delta: Callable[[str], None],
                    should_abort: Callable[[], bool]) -> ChatResult: ...


def build_request(url: str, body: bytes, headers: dict) -> urllib.request.Request:
    merged = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    merged.update(headers)
    return urllib.request.Request(url, data=body, headers=merged)


def open_streaming(opener, req: urllib.request.Request, timeout: float = 60.0):
    """開啟串流回應；HTTP/網路錯誤 → AiProviderError（繁中）。"""
    try:
        return opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        if code in (401, 403):
            raise AiProviderError("API 金鑰無效或無權限，請檢查設定") from e
        if code == 429:
            raise AiProviderError("已達供應商速率上限，請稍後再試") from e
        raise AiProviderError(f"AI 服務回應錯誤（HTTP {code}）") from e
    except urllib.error.URLError as e:
        raise AiProviderError(f"連線失敗：{e.reason}") from e
    except OSError as e:
        raise AiProviderError(f"連線失敗：{e}") from e


def iter_sse_data(resp, should_abort: Callable[[], bool]) -> Iterator[str]:
    """逐行讀 SSE，yield 每個 `data:` 行的 payload 字串；行間檢查 abort。

    連線中途斷線（readline 拋 OSError，例如 socket 被對端關閉）一律包成
    AiProviderError（繁中訊息），讓呼叫端能與其他傳輸錯誤一致處理，也避免
    UI 直接顯示英文的 socket 錯誤原因（M-1，spec §11）。"""
    while True:
        if should_abort():
            raise AiAborted()
        try:
            raw = resp.readline()
        except OSError as e:
            raise AiProviderError(f"連線中斷：{e}") from e
        if raw == b"":
            return
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith("data:"):
            yield line[5:].strip()
