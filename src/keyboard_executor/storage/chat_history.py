"""每個角色／玩家各存一份聊天紀錄；不改寫腳本或記錄聊天原文到日誌。"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import unicodedata

from keyboard_executor.core.chat_observer import ChatMessage

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 50


class ChatHistoryError(ValueError):
    """既有紀錄無法辨識，保留原檔供人工處理。"""


def _identity(value: str) -> str:
    if not isinstance(value, str):
        raise ChatHistoryError("聊天紀錄的角色名稱無效")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ChatHistoryError("聊天紀錄的角色名稱無效")
    return normalized


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message_from_dict(data: dict) -> ChatMessage:
    fields = {"id", "channel", "sender", "text", "incoming", "recipient"}
    if (not isinstance(data, dict) or set(data) - fields
            or not fields.difference({"recipient"}).issubset(data)
            or type(data["id"]) is not int or data["id"] < 0
            or data["channel"] not in ("map", "whisper")
            or not isinstance(data["sender"], str)
            or not isinstance(data["text"], str)
            or type(data["incoming"]) is not bool
            or not isinstance(data.get("recipient", ""), str)):
        raise ChatHistoryError("聊天紀錄的訊息格式無效")
    return ChatMessage(**data)


class ChatHistoryStore:
    """名稱經 NFKC 與首尾空白正規化；不同大小寫的玩家仍分開儲存。"""

    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._lock = threading.RLock()

    @staticmethod
    def _read(path: Path, owner: str) -> tuple[str, list[ChatMessage]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ChatHistoryError("聊天紀錄無法讀取，原檔已保留") from exc
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != 1 or data.get("self_name") != owner
                or not isinstance(data.get("player"), str)
                or not isinstance(data.get("messages"), list)):
            raise ChatHistoryError("聊天紀錄的格式無效，原檔已保留")
        player = _identity(data["player"])
        if player != data["player"] or path.stem != _digest(player):
            raise ChatHistoryError("聊天紀錄的玩家資料不符，原檔已保留")
        messages = [_message_from_dict(item) for item in data["messages"]]
        return player, messages[-_HISTORY_LIMIT:]

    def load(self, self_name: str) -> dict[str, list[ChatMessage]]:
        owner = _identity(self_name)
        with self._lock:
            directory = self._root / _digest(owner)
            conversations = {}
            for path in sorted(directory.glob("*.json")):
                try:
                    player, messages = self._read(path, owner)
                except (OSError, ChatHistoryError):
                    logger.warning("一份聊天紀錄無法載入，已保留原檔並略過")
                    continue
                conversations[player] = messages
            return conversations

    def append(self, self_name: str, player: str, message: ChatMessage) -> None:
        owner, player = _identity(self_name), _identity(player)
        if not isinstance(message, ChatMessage):
            raise ChatHistoryError("聊天紀錄的訊息格式無效")
        record = asdict(message)
        _message_from_dict(record)
        with self._lock:
            path = self._root / _digest(owner) / f"{_digest(player)}.json"
            try:
                _, previous = self._read(path, owner)
            except FileNotFoundError:
                previous = []
            data = {"version": 1, "self_name": owner, "player": player,
                    "messages": [asdict(item) for item in previous[-(_HISTORY_LIMIT - 1):]]
                    + [record]}
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=f".{path.stem}.", suffix=".tmp",
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
