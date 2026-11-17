"""Pure visual checks for the game's public chat channel."""
from __future__ import annotations

import cv2
import numpy as np

from keyboard_executor.platforms.base import TextBox


_PUBLIC_LABELS = {"對所有人", "對所有人7", "對所有人▼"}
_MENU_SIBLINGS = {
    "對好友", "對群組", "對隊伍", "對遠征隊", "對公會", "對聯盟", "對職業", "對頻道",
}
# OCR may emit mixed traditional/simplified glyphs for the same fixed caption.
# Normalize only UI-label comparisons; preserve TextBox and all player/chat text.
_UI_LABEL_VARIANTS = str.maketrans({
    "请": "請", "输": "輸", "语": "語", "对": "對", "组": "組", "队": "隊",
    "远": "遠", "会": "會", "联": "聯", "职": "職", "业": "業", "频": "頻",
})


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1).tolist(),
                    np.flatnonzero(edges == -1).tolist()))


def _white_mask(pixels: np.ndarray) -> np.ndarray:
    low, high = pixels.min(axis=2), pixels.max(axis=2)
    return ((low >= 245) & (high - low <= 15)).astype(np.uint8)


def white_bars(image: np.ndarray, white: np.ndarray | None = None) -> list[tuple[int, int, int, int]]:
    """所有像輸入框的白色長條（聊天輸入框、密語對象名字欄都算）。"""
    if image.ndim != 3 or image.shape[2] < 3 or not image.size:
        return []
    if white is None:
        white = _white_mask(image[:, :, :3])
    _, _, stats, _ = cv2.connectedComponentsWithStats(white)
    bars = []
    for x, y, w, h, area in stats[1:]:
        x, y, w, h = map(int, (x, y, w, h))
        if w < 120 or h < 12 or not 6 <= w / h <= 25 or area < w*h*.60:
            continue
        bars.append((x, y, w, h))
    return bars


def locate_recipient_input(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Locate the modal's white field, blue heading and green action buttons.

    This only proposes geometry. The caller must OCR the heading before typing;
    similar game dialogs must never be treated as a whisper recipient prompt.
    """
    if image.ndim != 3 or image.shape[2] < 3 or not image.size:
        return None
    pixels = image[:, :, :3]
    white = _white_mask(pixels)
    candidates = []
    for x, y, w, h in white_bars(image, white):
        # A selected name can split the white field into disconnected pieces.
        # Bridge horizontal glyph/selection gaps, retaining the blank margins.
        padding = 8*h
        band = np.pad(white[y:y+h], ((0, 0), (padding, padding)))
        joined = cv2.morphologyEx(band, cv2.MORPH_CLOSE,
                                 np.ones((1, padding+1), dtype=np.uint8))
        columns = joined[:, padding:-padding].mean(axis=0) >= .70
        spans = [(left, right) for left, right in _runs(columns)
                 if left <= x and right >= x+w]
        if len(spans) != 1:
            continue
        x, right = spans[0]
        w = right-x
        if not 6 <= w/h <= 25:
            continue
        top, bottom = max(0, y-3*h), min(image.shape[0], y+3*h)
        header = pixels[top:y-h//2, x:x+w].astype(np.int16)
        buttons = pixels[y+h:bottom, x+w//2:x+w].astype(np.int16)
        if not header.size or not buttons.size:
            continue
        blue = ((header[:, :, 0] > header[:, :, 2]+40)
                & (header[:, :, 1] > header[:, :, 2]+30)
                & (header[:, :, 0] > 100))
        green = ((buttons[:, :, 1] > 110)
                 & (buttons[:, :, 1] > buttons[:, :, 0]+45)
                 & (buttons[:, :, 2] > 70))
        if blue.mean() >= .45 and green.mean() >= .04:
            if (x, y, w, h) not in candidates:
                candidates.append((x, y, w, h))
    return candidates[0] if len(candidates) == 1 else None


def _recipient_caption(label: str) -> bool:
    # 遊戲視窗較小時字也小，OCR 會讀錯一兩個字（實測 1296x759：讀輸入密語封象）。
    # 輸入框、藍色標題、綠色按鈕的版面已另外確認；文字要求「密語」正確、
    # 七個字最多錯兩個。
    label = label.rstrip('。.:：·')
    return (len(label) == 7 and label[3:5] == '密語'
            and sum(a != b for a, b in zip(label, '請輸入密語對象')) <= 2)


def is_recipient_prompt(boxes: list[TextBox]) -> bool:
    return any(_trusted(box) and _recipient_caption(_label(box)) for box in boxes)


def locate_channel_button(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return an OCR/click rectangle in image pixels, or decline uncertain UI.

    The lower part of the chat crop must contain a wide white input with a
    neutral gray recipient button immediately to its left. Neither OCR text
    elsewhere in the chat nor an assumed fixed screen coordinate is sufficient.
    """
    if image.ndim != 3 or image.shape[2] < 3 or not image.size:
        return None
    height, width = image.shape[:2]
    low, high = image[:, :, :3].min(axis=2), image[:, :, :3].max(axis=2)
    neutral = high - low <= 15
    white = neutral & (low >= 235)
    gray = neutral & (low >= 55) & (high <= 230)
    minimum_width = max(100, int(width * .30))
    white_spans: dict[int, tuple[int, int]] = {}
    for y in range(int(height * .55), height):
        spans = [(left, right) for left, right in _runs(white[y])
                 if left >= 35 and right - left >= minimum_width]
        if spans:
            white_spans[y] = max(spans, key=lambda span: span[1] - span[0])

    active_rows = np.zeros(height, dtype=bool)
    active_rows[list(white_spans)] = True
    candidates = []
    for top, bottom in _runs(active_rows):
        band_height = bottom - top
        if band_height < 12:
            continue
        spans = [white_spans[y] for y in range(top, bottom)]
        # Text may move the longest white run rightwards on glyph rows. The
        # blank top/bottom margins still reveal the actual input's left edge.
        left = int(np.percentile([span[0] for span in spans], 10))
        right = int(np.median([span[1] for span in spans]))
        if left > width * .45 or right - left < minimum_width:
            continue
        if white[top:bottom, left:right].mean() < .80:
            continue

        columns = gray[top:bottom, :left].mean(axis=0) >= .45
        # White glyph strokes can interrupt an otherwise solid gray button.
        # Bridge only narrow interior gaps, scaled to the observed bar height.
        for start, end in _runs(~columns):
            if start and end < left and end - start <= max(2, band_height * .15):
                columns[start:end] = True
        for button_left, button_right in _runs(columns):
            button_width = left - button_left
            if left - button_right > max(2, band_height * .12):
                continue
            if not max(35, band_height * 1.2) <= button_width <= band_height * 7:
                continue
            if gray[top:bottom, button_left:left].mean() < .70:
                continue
            candidates.append((button_left, top, button_width, band_height))
    return candidates[0] if len(candidates) == 1 else None


def _label(box: TextBox) -> str:
    return "".join(box.text.split()).translate(_UI_LABEL_VARIANTS)


def _trusted(box: TextBox) -> bool:
    return box.confidence >= .70 and box.width > 0 and box.height > 0


def is_public_channel(boxes: list[TextBox]) -> bool:
    """Confirm the exact public label in OCR of the located button crop."""
    return any(_trusted(box) and _label(box) in _PUBLIC_LABELS for box in boxes)


def find_public_menu_item(boxes: list[TextBox]) -> TextBox | None:
    """Find a unique public row with at least two distinct aligned menu peers.

    Coordinates remain relative to the image supplied to OCR. The caller must
    first open the detected button and crop its menu; this helper performs no
    input and never promotes a substring in a chat message to a click target.
    """
    public = [box for box in boxes if _label(box) in _PUBLIC_LABELS]
    if len(public) != 1 or not _trusted(public[0]):
        return None
    target = public[0]
    siblings = []
    for box in boxes:
        if not _trusted(box) or _label(box) not in _MENU_SIBLINGS:
            continue
        row_height = max(box.height, target.height)
        if abs(box.x - target.x) > max(4, row_height * .75):
            continue
        if not box.height * .75 <= target.height <= box.height * 1.5:
            continue
        if not row_height <= target.y - box.y <= row_height * 16:
            continue
        siblings.append(box)
    distinct_rows = any(
        _label(a) != _label(b) and abs(a.y - b.y) >= max(a.height, b.height) * .75
        for i, a in enumerate(siblings) for b in siblings[i + 1:]
    )
    return target if distinct_rows else None


def shows_menu_labels(boxes: list[TextBox]) -> bool:
    """True when any trusted channel-menu caption is visible in the menu crop."""
    return any(_trusted(box) and _label(box) in _MENU_SIBLINGS | _PUBLIC_LABELS
               for box in boxes)


def locate_chat_input(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Locate the inner white editable area beside a confirmed channel button.

    Capture this rectangle before typing, then reuse its coordinates to inspect
    the field after submission. A long draft need not be locatable from scratch.
    The right-hand chat controls are excluded from the returned pixel rectangle.
    """
    button = locate_channel_button(image)
    if button is None:
        return None
    x, y, width, height = button
    edge = x + width
    pixels = image[y:y + height, :, :3]
    low, high = pixels.min(axis=2), pixels.max(axis=2)
    white = (low >= 235) & (high - low <= 15)
    spans = [
        (left, right) for row in white for left, right in _runs(row)
        if abs(left - edge) <= max(3, height * .15)
        and right - left >= max(100, image.shape[1] * .30)
    ]
    if len(spans) < max(3, height * .15):
        return None
    # The blank margins reveal the true left edge; a caret must not move the
    # returned crop rightward and disappear from later submission checks.
    left = max(edge, int(np.percentile([span[0] for span in spans], 25)))
    right = int(np.percentile([span[1] for span in spans], 10))
    if right - left < max(100, image.shape[1] * .30):
        return None
    crop = image[y:y + height, left:right]
    if not _inspect_chat_input(crop)[1]:
        return None
    return left, y, right - left, height


def chat_input_has_text(image: np.ndarray) -> bool | None:
    """Inspect a previously located input crop without OCR or input side effects.

    True means dark glyphs (including punctuation) remain; False means a credible
    white field is empty. Return None for obscured/nonwhite UI or an isolated
    stroke indistinguishable from a caret. A later frame may resolve a blinking
    caret; callers must not treat None as empty.
    """
    return _inspect_chat_input(image)[0]


def _full_height_strokes(ink: np.ndarray) -> list[tuple[int, int]]:
    # Antialiasing can join a caret to the preceding glyph after UI scaling.
    # Its nearly full-height vertical columns still identify the stroke.
    return [(left, right) for left, right in _runs(ink.mean(axis=0) >= .90)
            if right-left <= max(1, int(np.ceil(ink.shape[0] * .10)))]


def _inspect_chat_input(image: np.ndarray) -> tuple[bool | None, bool]:
    """Return (text status, credible field), keeping caret ambiguity separate."""
    if image.ndim != 3 or image.shape[2] < 3 or not image.size:
        return None, False
    height, width = image.shape[:2]
    if height < 12 or width < height * 2:
        return None, False
    # Remove only nearly solid outer frame lines. Blindly trimming edge pixels
    # could erase a short punctuation mark and falsely confirm submission.
    margin = max(1, int(np.ceil(height * .06)))
    low, high = image[:, :, :3].min(axis=2), image[:, :, :3].max(axis=2)
    white = (low >= 235) & (high - low <= 15)
    left, top, right, bottom = 0, 0, width, height
    while top < margin and white[top, left:right].mean() <= .05:
        top += 1
    while height - bottom < margin and white[bottom - 1, left:right].mean() <= .05:
        bottom -= 1
    while left < margin and white[top:bottom, left].mean() <= .05:
        left += 1
    while width - right < margin and white[top:bottom, right - 1].mean() <= .05:
        right -= 1
    inner = image[top:bottom, left:right, :3]
    low, high = inner.min(axis=2), inner.max(axis=2)
    neutral = high - low <= 15
    if np.count_nonzero(~neutral) > max(2, inner.shape[0] * inner.shape[1] * .002):
        return None, False
    white = neutral & (low >= 235)
    if white.mean() < .75:
        # Dense Chinese drafts can cover over a quarter of a valid white
        # field. Require intact horizontal margins in that case, then apply
        # the same glyph/overlay checks below; density alone is not occlusion.
        rim = max(1, round(inner.shape[0] * .08))
        if (white.mean() < .50 or white[:rim].mean() < .95
                or white[-rim:].mean() < .95):
            return None, False

    text = ambiguous = False
    ink = ~white
    for left, right in _full_height_strokes(ink):
        ink[:, left:right] = False
        ambiguous = True
    _, _, components, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8))
    for x, y, component_width, component_height, area in components[1:]:
        thin_stroke = (
            component_width <= max(1, round(height * .07))
            and component_height >= height * .45
            and component_height >= component_width * 5
            and area >= component_width * component_height * .80
        )
        # The real game caret spans the entire field height. Recognize it
        # before rejecting oversized components, or a blink hides valid text
        # and prevents the guarded Enter retry. A caret alone stays ambiguous.
        if thin_stroke:
            ambiguous = True
            continue
        if component_height > height * .90 or component_width > height * 3:
            return None, False
        glyph_area = max(12, (height * .65) ** 2)
        if area > glyph_area or component_width > height:
            # Downscaling can join adjacent Chinese glyphs through gray edge
            # pixels. Allow a small group, but never a solid block/overlay.
            slots = int(np.ceil(component_width / height))
            if (slots <= 1 or area > glyph_area * slots
                    or area >= component_width * component_height * .80):
                return None, False
        text = True
    if text:
        return True, True
    return (None if ambiguous else False), True


def same_chat_input_text(before: np.ndarray, after: np.ndarray) -> bool:
    """Confirm unchanged visible draft pixels despite a blinking trailing caret.

    Both frames must positively contain text in a credible white input. After
    removing only independent tall, thin trailing strokes, the remaining dark
    pixels must match exactly; a high global overlap could hide an edited glyph.
    """
    if before.shape != after.shape:
        return False
    if chat_input_has_text(before) is not True or chat_input_has_text(after) is not True:
        return False
    first = _draft_ink_without_caret(before)
    second = _draft_ink_without_caret(after)
    return bool(first.any() and second.any() and np.array_equal(first, second))


def _draft_ink_without_caret(image: np.ndarray) -> np.ndarray:
    height = image.shape[0]
    ink = image[:, :, :3].max(axis=2) <= 180
    for left, right in _full_height_strokes(ink):
        if not left or ink[:, right:].any():
            continue  # Only a trailing stroke can be a caret here.
        peers = cv2.connectedComponentsWithStats(ink[:, :left].astype(np.uint8))[2][1:]
        if len(peers) and height >= max(box[3] for box in peers) * 1.15:
            ink[:, left:right] = False
    _, labels, components, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8))
    for index, (x, y, width, stroke_height, area) in enumerate(components[1:], 1):
        if not (width <= max(1, round(height * .07))
                and stroke_height >= height * .55
                and stroke_height >= width * 5
                and area >= width * stroke_height * .80):
            continue
        others = [box for i, box in enumerate(components[1:], 1) if i != index]
        # The dot below !/i belongs to the same glyph. Its stem must survive;
        # only a separate stroke beyond all other ink may be a trailing caret.
        if not others or any(other[0] + other[2] > x for other in others):
            continue
        # Ordinary terminal l/I strokes have the same height as their peers.
        if stroke_height < max(other[3] for other in others) * 1.15:
            continue
        ink[labels == index] = False
    return ink
