"""Read chat messages from OCR and BGR pixels without performing any input.

The first readable frame is context only. Later frames are aligned against the
recent transcript, preserving repeated messages when they appear after overlap.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re
import unicodedata

import cv2
import numpy as np

from keyboard_executor.platforms.base import TextBox

_CONFIRM_READS = 2            # 密語被擠出畫面後，姓名至少要在幾張畫面讀到完全相同
_CONFIRM_RECENT_FRAMES = 60   # 最後一次讀到距今最多幾張畫面（約每秒一張）
_FORGET_SENDER_FRAMES = 300
_ALIAS_MIN_READS = 5          # 穩定姓名至少讀到幾次，才把相近的偶發誤讀併回它
_ALIAS_RATIO = 5              # 而且次數至少是誤讀寫法的幾倍


@dataclass(frozen=True)
class ChatMessage:
    id: int
    channel: str
    sender: str
    text: str
    incoming: bool = True
    recipient: str = ""


@dataclass(frozen=True)
class _Line:
    raw: str
    top: int
    bottom: int
    channel: str
    sender: str
    text: str
    incoming: bool
    eligible: bool
    recipient: str = ""


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _key(text: str) -> str:
    return "".join(_normalize(text).split())


def _same_line(left: _Line, right: _Line) -> bool:
    # Body similarity cannot establish who spoke, to whom, or in which channel.
    # In particular, long identical text from similar names is still distinct.
    identity = lambda line: (line.channel, _normalize(line.sender), line.incoming,
                             _normalize(line.recipient))
    if identity(left) != identity(right):
        return False
    a, b = _key(left.raw), _key(right.raw)
    if a == b:
        return True
    # Short messages and substantial edits must remain distinct. A tiny edit in
    # a long existing line is usually OCR jitter, so avoid replying to it again.
    return (left.channel in {"map", "whisper"} and bool(left.sender)
            and min(len(a), len(b)) >= 24
            and SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.96)


def _one_char_apart(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _similar_name(a: str, b: str) -> bool:
    """可能是同一個姓名的不同讀法（大小寫、增減或讀錯一兩個字）。"""
    a, b = _key(a), _key(b)
    return a.casefold() == b.casefold() or _edit_distance(a, b) <= 2


_ECHO_SCORE = .70     # 地圖訊息與剛送出的回覆相似到這個程度＝自己的回音
_ECHO_MIN_CHARS = 4
_ALIAS_ECHOES = 2     # 同一個名字回音兩次才當成自己（避免把學一次話的玩家當成自己）


def _echo_text(text: str) -> str:
    return "".join(ch for ch in _normalize(text) if ch.isalnum() or ch == "?")


def _echo_score(sent: str, seen: str) -> float:
    """OCR 會把簡體字讀成「?」或讀錯幾個字：「?」視為萬用字元。"""
    a, b = _echo_text(sent), _echo_text(seen)
    if min(len(a), len(b)) < _ECHO_MIN_CHARS:
        return 1.0 if a and a == b else 0.0
    matched = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            matched += i2 - i1
        elif tag == "replace" and i2 - i1 == j2 - j1:
            matched += b[j1:j2].count("?")
    return 2 * matched / (len(a) + len(b))


def _same_person(misread: str, known: str) -> bool:
    """比 _similar_name 嚴格：只用在把偶發誤讀併回長期穩定讀到的姓名。
    短姓名（3 字以下）差一字很可能是不同人，不合併。"""
    a, b = _key(misread), _key(known)
    if min(len(a), len(b)) < 4:
        return False
    return a.casefold() == b.casefold() or _edit_distance(a, b) <= max(1, min(len(a), len(b)) // 5)


def _reread(previous: _Line, current: _Line) -> bool:
    """同一位置、上一兩張畫面才消失的列被讀成相近文字＝OCR 抖動，不是新訊息。
    真的新訊息會出現在下方並把舊列往上推，舊列仍在畫面上。"""
    if (previous.channel != current.channel or previous.incoming != current.incoming
            or not previous.sender or not current.sender):
        return False
    if abs(previous.top - current.top) > max(4, (current.bottom - current.top) / 2):
        return False
    a, b = _key(previous.sender), _key(current.sender)
    if a != b and not _one_char_apart(a, b):
        return False
    x, y = _key(previous.text), _key(current.text)
    return (x in y or y in x
            or SequenceMatcher(None, x, y, autojunk=False).ratio() >= 0.5)


def _align_rows(previous: list[_Line], current: list[_Line]) -> list[tuple[int, int]]:
    """Pairs of previous/current rows matched to the observed transcript."""
    n, m = len(previous), len(current)
    matches = [[_same_line(a, b) for b in current] for a in previous]
    # Anchor at the newest known row still visible. An unconstrained longest
    # subsequence could instead match older repetitions *after* that anchor and
    # incorrectly swallow new messages. Prefix alignment disambiguates repeated
    # occurrences of the anchor itself, preferring the earliest equally good one.
    lengths = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            lengths[i + 1][j + 1] = (1 + lengths[i][j] if matches[i][j]
                                     else max(lengths[i][j + 1], lengths[i + 1][j]))
    matched = []
    while n and m:
        anchor = next((i for i in range(n - 1, -1, -1) if any(matches[i][:m])), None)
        if anchor is None:
            break
        row = max((j for j in range(m) if matches[anchor][j]),
                  key=lambda j: lengths[anchor][j])
        matched.append((anchor, row))
        n, m = anchor, row
    return list(reversed(matched))


def _drop_stray(row: list[TextBox]) -> list[TextBox]:
    """背景物件偶爾被讀成遠離文字、信心很低的一兩個字（實測 'D' 0.42），
    併進密語那一列就讓整列不可信。只丟掉與前一個框距離超過三個字高的這種框。"""
    kept: list[TextBox] = []
    for box in sorted(row, key=lambda b: b.x):
        stray = (kept and box.confidence < .60 and len(box.text.strip()) <= 2
                 and box.x - max(b.x + b.width for b in kept) > 3 * box.height)
        if not stray:
            kept.append(box)
    return kept


def _group_boxes(boxes: list[TextBox]) -> list[list[TextBox]]:
    rows: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda b: (b.y + b.height / 2, b.x)):
        if not box.text.strip() or box.width <= 0 or box.height <= 0:
            continue
        center = box.y + box.height / 2
        for row in reversed(rows):
            anchor = row[0]
            anchor_center = anchor.y + anchor.height / 2
            if abs(center - anchor_center) <= min(box.height, anchor.height) * 0.45:
                row.append(box)
                break
        else:
            rows.append([box])
    return [sorted(row, key=lambda b: b.x) for row in rows]


def _join_boxes(boxes: list[TextBox]) -> str:
    text = ""
    for box in boxes:
        part = _normalize(box.text)
        if text and part and text[-1].isascii() and part[0].isascii():
            if text[-1].isalnum() and part[0].isalnum():
                text += " "
        text += part
    return text


def _foreground_color(image: np.ndarray, boxes: list[TextBox]) -> str:
    """Classify bright glyph strokes, not the dominant background of OCR boxes."""
    if image.ndim != 3 or image.shape[2] < 3:
        return "other"
    height, width = image.shape[:2]
    contrast_count = bright_count = dark_count = green_count = white_count = 0
    for box in boxes:
        x1, y1 = max(0, box.x), max(0, box.y)
        x2, y2 = min(width, box.x + box.width), min(height, box.y + box.height)
        if x1 >= x2 or y1 >= y2:
            continue
        crop = np.ascontiguousarray(image[y1:y2, x1:x2, :3], dtype=np.uint8)
        hue, saturation, value = cv2.split(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV))
        # Scale the filter with line height so ordinary display scaling does not
        # turn thicker glyphs into background. Opening removes narrow bright
        # strokes; closing also exposes dark glyphs on a bright colored banner.
        size = max(3, min(11, (box.height // 4) | 1))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
        bright = cv2.morphologyEx(value, cv2.MORPH_TOPHAT, kernel) >= 30
        dark = cv2.morphologyEx(value, cv2.MORPH_BLACKHAT, kernel) >= 30
        contrast_count += int(np.count_nonzero(bright))
        bright_count += int(np.count_nonzero(bright & (value >= 150)))
        dark_count += int(np.count_nonzero(dark))
        green = (hue >= 35) & (hue <= 90) & (saturation >= 100) & (value >= 150)
        white = (saturation <= 65) & (value >= 180)
        # A solid colored banner can leave small bright islands inside dark
        # glyphs after opening. A color covering most of the box is background.
        if np.count_nonzero(green) / green.size < 0.65:
            green_count += int(np.count_nonzero(bright & green))
        if np.count_nonzero(white) / white.size < 0.65:
            white_count += int(np.count_nonzero(bright & white))
    if bright_count < 8 or contrast_count < dark_count * 0.65:
        return "other"
    if green_count / bright_count >= 0.55:
        return "green"
    if white_count / bright_count >= 0.55:
        return "white"
    return "other"


class ChatObserver:
    """Stateful OCR observer; call from a single chat session thread."""

    def __init__(self, self_name: str, history_limit: int = 50, *,
                 on_message: Callable[[str, ChatMessage], None] | None = None):
        self.self_name = _normalize(self_name)
        self._history_limit = max(1, history_limit)
        self._history: list[ChatMessage] = []
        self._conversations: dict[str, list[ChatMessage]] = {}
        self._images: dict[str, list[tuple[str, np.ndarray]]] = {}
        self._visible_senders: set[tuple[str, str]] = set()
        # 姓名在幾張畫面被完全相同讀到、最後一次是第幾張
        self._sender_reads: dict[tuple[str, str], list[int]] = {}
        self._frame_no = 0
        self._on_message = on_message
        self._restored_baseline = False
        self._seen: list[_Line] = []
        self._recent_frames: list[list[_Line]] = []   # 最近幾張畫面讀到的列
        self._pending_replies: list[tuple[str, str, str]] = []
        # 實機 2026-10-30：換角色玩（畫面顯示 胖胖布丁幻影，設定是 胖胖布丁狂豹），
        # 自己送出的地圖回覆被當成別人說的話，一直自己跟自己對話。
        self._sent_map: list[str] = []          # 最近送出的地圖回覆
        self._echoes: dict[str, int] = {}       # 名字 -> 回音次數
        self._self_aliases: set[str] = set()    # 畫面上其實是自己的名字
        self._next_id = 1

    @property
    def history(self) -> list[ChatMessage]:
        """Bounded recent transcript for diagnostics, not player AI context."""
        return list(self._history)

    @property
    def conversations(self) -> dict[str, list[ChatMessage]]:
        return {player: list(messages) for player, messages in self._conversations.items()}

    def history_for(self, player: str, *, channel: str | None = None) -> list[ChatMessage]:
        return [message for message in self._conversations.get(_normalize(player), [])
                if channel is None or message.channel == channel]

    def sees_incoming_sender(self, player: str, channel: str) -> bool:
        """Require an exact trusted name in the latest frame, not saved context.

        實機：攻擊時「前方沒有可攻擊的怪物」等系統訊息洗版，密語幾秒內就被擠出
        聊天框。最新畫面已看不到時，改要求最近幾張畫面至少兩次讀到完全相同的
        姓名，而且次數至少是任何相近寫法（大小寫、差一兩字）的兩倍。"""
        return not self.sender_doubt(player, channel)

    def sender_doubt(self, player: str, channel: str) -> str:
        """無法確認姓名的原因；空字串表示已確認。"""
        key = (channel, _normalize(player))
        if key in self._visible_senders:
            return ""
        reads = self._sender_reads.get(key)
        if reads is None or self._frame_no - reads[1] > _CONFIRM_RECENT_FRAMES:
            return f"{player} 已不在聊天畫面"
        if reads[0] < _CONFIRM_READS:
            return f"{player} 被擠出畫面前只讀到 {reads[0]} 次"
        rivals = [(other[1], count) for other, (count, _) in self._sender_reads.items()
                  if other != key and other[0] == channel and _similar_name(other[1], key[1])
                  and count * 2 > reads[0]]
        if rivals:
            others = ", ".join(f"{name} {count} 次" for name, count in rivals)
            return f"{player} 讀到 {reads[0]} 次, 但也讀到相近寫法 {others}"
        return ""

    def image_for(self, player: str, *, channel: str | None = None) -> np.ndarray | None:
        """Only this player's trusted OCR rectangles in the latest observed frame."""
        strips = [strip for row_channel, strip in self._images.get(_normalize(player), [])
                  if channel is None or row_channel == channel]
        if not strips:
            return None
        result = np.zeros((sum(strip.shape[0] for strip in strips),
                           max(strip.shape[1] for strip in strips), 3), dtype=np.uint8)
        top = 0
        for strip in strips:
            result[top:top + strip.shape[0], :strip.shape[1]] = strip
            top += strip.shape[0]
        return result

    def _player(self, message: ChatMessage | _Line) -> str:
        if message.channel not in {"map", "whisper"} or not message.sender:
            return ""
        player = _normalize(message.sender if message.incoming else message.recipient)
        return player if player and not self.is_self(player) else ""

    def is_self(self, name: str) -> bool:
        key = _key(name)
        return key == _key(self.self_name) or key in self._self_aliases

    @property
    def self_aliases(self) -> set[str]:
        return set(self._self_aliases)

    def inherit_self(self, other: "ChatObserver") -> None:
        """暫停後重建觀察器時，保留已學到的自己名字與剛送出的回覆。"""
        self._self_aliases |= other._self_aliases
        self._echoes.update(other._echoes)
        self._sent_map = list(other._sent_map)

    def _echo(self, line: _Line) -> bool:
        """地圖上「別人」說的話其實是自己剛送出的回覆。"""
        if line.channel != "map" or not line.incoming or not self._sent_map:
            return False
        best = max(self._sent_map, key=lambda sent: _echo_score(sent, line.text))
        if _echo_score(best, line.text) < _ECHO_SCORE:
            return False
        self._sent_map.remove(best)
        key = _key(line.sender)
        self._echoes[key] = self._echoes.get(key, 0) + 1
        if self._echoes[key] >= _ALIAS_ECHOES:
            self._self_aliases.add(key)
        return True

    def restore_conversations(self, conversations: dict[str, list[ChatMessage]]) -> None:
        """Restore saved player context without publishing it as newly observed."""
        restored: dict[str, list[ChatMessage]] = {}
        for player, messages in conversations.items():
            player = _normalize(player)
            for message in messages:
                self._next_id = max(self._next_id, message.id + 1)
                if player and self._player(message) == player:
                    restored.setdefault(player, []).append(message)
        self._conversations = {player: messages[-self._history_limit:]
                               for player, messages in restored.items()}
        self._history.clear()
        self._seen.clear()
        self._recent_frames.clear()
        self._pending_replies.clear()
        self._images.clear()
        self._visible_senders.clear()
        self._sender_reads.clear()
        self._restored_baseline = True

    def _restored_matches(self, lines: list[_Line]) -> set[int]:
        """Align each player's visible occurrences with its saved conversation."""
        players: dict[str, list[tuple[int, _Line]]] = {}
        for index, line in enumerate(lines):
            if player := self._player(line):
                # CH tags are not part of a conversation's identity or content.
                players.setdefault(player, []).append((index, replace(line, raw=line.text)))
        matched: set[int] = set()
        for player, current in players.items():
            previous = [_Line(message.text, 0, 0, message.channel, message.sender,
                              message.text, message.incoming, message.incoming,
                              message.recipient)
                        for message in self._conversations.get(player, [])]
            matched.update(current[row][0] for _, row in
                           _align_rows(previous, [line for _, line in current]))
        return matched

    def _capture_player_rows(self, image: np.ndarray, rows: list[list[TextBox]],
                             lines: list[_Line]) -> None:
        self._images = {}
        if image.ndim != 3 or image.shape[2] < 3:
            return
        height, width = image.shape[:2]
        for boxes, line in zip(rows, lines):
            player = self._player(line)
            if not player:
                continue
            left = max(0, min(box.x for box in boxes))
            right = min(width, max(box.x + box.width for box in boxes))
            top, bottom = max(0, line.top), min(height, line.bottom)
            if left >= right or top >= bottom:
                continue
            strip = np.zeros((bottom - top, right - left, 3), dtype=np.uint8)
            for box in boxes:
                x1, x2 = max(left, box.x), min(right, box.x + box.width)
                y1, y2 = max(top, box.y), min(bottom, box.y + box.height)
                if x1 < x2 and y1 < y2:
                    # Mask gaps between OCR boxes; they may contain unrelated UI.
                    strip[y1 - top:y2 - top, x1 - left:x2 - left] = image[y1:y2, x1:x2, :3]
            self._images.setdefault(player, []).append((line.channel, strip))

    def _parse(self, image: np.ndarray, boxes: list[TextBox]) -> _Line:
        raw = _join_boxes(boxes)
        color = _foreground_color(image, boxes)
        channel = "other"
        sender, text, recipient = "", raw, ""
        incoming = True
        parsed = None
        if color == "green":
            # 收到密語的格式是 姓名[CH.301]>>（也有 CH-301）；標籤不屬於姓名。
            tagged = re.fullmatch(r"(.+?)\s*[\[|({]CH\s*[.-]\s*\d{1,4}\s*[\]|)}1lI]?\s*>>\s*(.*)",
                                 raw, re.IGNORECASE)
            parsed = tagged or re.fullmatch(r"(.+?)\s*(<<|>>)\s*(.+)", raw)
            if tagged:
                channel = "whisper"
                sender, text = tagged.groups()
                if not text.strip():
                    text = "（OCR 未辨識到訊息內容，請參照聊天截圖）"
            elif parsed:
                channel = "whisper"
                sender, direction, text = parsed.groups()
                incoming = False  # 沒有來源頻道的綠字屬於送出紀錄，不觸發 AI
        elif color == "white":
            parsed = re.fullmatch(r"([^:]+):\s*(.+)", raw)
            if parsed:
                channel = "map"
                sender, text = parsed.groups()
        sender, text = sender.strip(), text.strip()
        # Recipient names are executable input later. Retain uncertain OCR only
        # as context; never invent, repair, or strip characters from a name.
        trusted = (parsed is not None and bool(text)
                   and all(box.confidence >= 0.80 for box in boxes)
                   and re.fullmatch(r"[\w·・]{1,32}", sender) is not None)
        if not trusted:
            sender, text = "", raw
            channel = "other"
        elif not incoming:
            recipient, sender = sender, self.self_name
        elif self.is_self(sender):
            incoming = False
            recipient = sender
        return _Line(raw, min(b.y for b in boxes), max(b.y + b.height for b in boxes),
                     channel, sender, text, incoming,
                     trusted and incoming and channel in {"map", "whisper"}, recipient)

    def _append(self, channel: str, sender: str, text: str, incoming: bool,
                recipient: str = "", *, remember: bool = True) -> ChatMessage:
        message = ChatMessage(self._next_id, channel, sender, text, incoming, recipient)
        self._next_id += 1
        self._history.append(message)
        del self._history[:-self._history_limit]
        if remember and (player := self._player(message)):
            conversation = self._conversations.setdefault(player, [])
            conversation.append(message)
            del conversation[:-self._history_limit]
            if self._on_message is not None:
                self._on_message(player, message)
        return message

    def observe(self, image: np.ndarray, boxes: list[TextBox]) -> list[ChatMessage]:
        rows = [_drop_stray(row) for row in _group_boxes(boxes)]
        lines = [self._canonical_sender(self._parse(image, row)) for row in rows]
        # Even empty/uncertain OCR invalidates the previous visual evidence.
        # Never fuzzy-match names: similar names can belong to different people.
        self._visible_senders = {(line.channel, _normalize(line.sender))
                                 for line in lines if line.eligible}
        self._note_sender_reads()
        self._capture_player_rows(image, rows, lines)
        if not lines:
            # OCR occasionally produces no boxes. Preserve the last transcript,
            # and don't count an empty startup image as the first chat baseline.
            return []
        baseline = not self._seen
        restored = self._restored_matches(lines) if baseline and self._restored_baseline else set()
        self._restored_baseline = False
        # 固定的「對所有人」按鈕與重複公告只能證明自己是舊列，不能把
        # 上方未匹配的新密語一起略過。仍保留公告順序，才能辨別公告後
        # 再次傳送相同內容的密語。
        alignment = _align_rows(self._seen, lines)
        matched = {row for _, row in alignment}
        fresh = [(i, line) for i, line in enumerate(lines) if i not in matched]
        recent = {id(line) for frame in self._recent_frames for line in frame}
        gone = [line for k, line in enumerate(self._seen)
                if id(line) in recent and k not in {p for p, _ in alignment}]
        # 只在「列數不變、只有一列讀法不同」時判斷：真的新訊息會多出一列，
        # 或把整個聊天框往上推（舊列換到別的位置）。
        steady = (len(lines) >= 2 and len(fresh) == 1 and bool(self._recent_frames)
                  and len(lines) == len(self._recent_frames[-1]))
        result = []
        for index, line in fresh:
            if not baseline and steady and any(_reread(old, line) for old in gone):
                continue
            signature = (line.channel, _key(line.recipient), _key(line.text))
            if not line.incoming and signature in self._pending_replies:
                self._pending_replies.remove(signature)
                continue
            if self._echo(line):
                continue
            message = self._append(line.channel, line.sender, line.text, line.incoming,
                                   line.recipient, remember=index not in restored)
            if not baseline and line.eligible:
                result.append(message)
        # 新列可能插在固定按鈕前，也可能是 OCR 補回中間漏列。依畫面
        # 順序插回已讀紀錄，否則下次會把插入位置之後的舊對話再次觸發。
        seen = []
        previous_start = current_start = 0
        for previous, current in alignment:
            seen.extend(self._seen[previous_start:previous])
            seen.extend(lines[current_start:current + 1])
            previous_start, current_start = previous + 1, current + 1
        seen.extend(self._seen[previous_start:])
        seen.extend(lines[current_start:])
        self._seen = seen
        del self._seen[:-max(120, self._history_limit * 3)]
        self._recent_frames = (self._recent_frames + [lines])[-3:]
        return result

    def _canonical_sender(self, line: _Line) -> _Line:
        """實機：胖胖布丁狂豹 讀到 47 次、偶爾讀成 胖胖布丁狂的。偶發誤讀併回穩定姓名，
        否則會變成假的新密語，或因收件人無法確認而略過回覆。"""
        if not line.eligible or line.channel != "whisper":
            return line
        key = (line.channel, _normalize(line.sender))
        own = self._sender_reads.get(key, [0, 0])[0]
        best = None
        for other, (count, _) in self._sender_reads.items():
            if (other != key and other[0] == line.channel and count >= _ALIAS_MIN_READS
                    and count >= _ALIAS_RATIO * max(1, own)
                    and _same_person(line.sender, other[1])
                    and (best is None or count > best[1])):
                best = (other[1], count)
        if best is None:
            return line
        return replace(line, sender=best[0], raw=line.raw.replace(line.sender, best[0], 1))

    def _note_sender_reads(self) -> None:
        self._frame_no += 1
        for key in self._visible_senders:
            reads = self._sender_reads.setdefault(key, [0, 0])
            reads[0] += 1
            reads[1] = self._frame_no
        for key, reads in list(self._sender_reads.items()):
            if self._frame_no - reads[1] > _FORGET_SENDER_FRAMES:
                del self._sender_reads[key]

    def record_reply(self, message: ChatMessage, text: str) -> None:
        """Record only after input has successfully sent this reply."""
        text = text.strip()
        self._append(message.channel, self.self_name, text, False, message.sender)
        recipient = message.sender if message.channel == "whisper" else self.self_name
        self._pending_replies.append((message.channel, _key(recipient), _key(text)))
        del self._pending_replies[:-self._history_limit]
        if message.channel == "map":
            self._sent_map.append(text)
            del self._sent_map[:-10]
