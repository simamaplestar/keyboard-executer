"""Local-only, conservative matching of the supported numbered-input prompts."""
import math
from typing import Literal, Sequence
from keyboard_executor.platforms.base import TextBox
from keyboard_executor.core.sequence_input_config import normalize_prompt

PromptState = Literal['present', 'absent', 'unknown']
PROMPTS = tuple(normalize_prompt(text) for text in
                ('請按照號碼順序輸入文字', '請依照編號順序輸入文字', '請按順序輸入文字'))


def normalize_panel_prompt(text: str) -> str:
    return normalize_prompt(text)


def _adjacent(a, b):
    overlap_y = min(a.y+a.height, b.y+b.height) - max(a.y, b.y)
    height = max(a.height, b.height)
    if overlap_y >= min(a.height, b.height) / 2:
        return b.x >= a.x+a.width and b.x-(a.x+a.width) <= 2*height
    overlap_x = min(a.x+a.width, b.x+b.width) - max(a.x, b.x)
    return overlap_x > 0 and 0 <= b.y-(a.y+a.height) <= height


def classify_sequence_prompt(boxes: Sequence[TextBox]) -> PromptState:
    if len(boxes) > 128:
        return 'unknown'
    usable = [b for b in boxes if isinstance(b.text, str) and b.width > 0 and b.height > 0]
    texts = [normalize_panel_prompt(b.text) for b in usable]
    reliable = [type(b.confidence) in (int, float) and math.isfinite(b.confidence)
                and .8 <= b.confidence <= 1 for b in usable]
    uncertain = False
    # Full matches run first: an uncertainty-only search must not consume the
    # search budget before a later reliable full prompt can be evaluated.
    for complete in (True, False):
        for start, text in enumerate(texts):
            for prompt in PROMPTS:
                # A misread/missing 請 must not prove disappearance. Matching
                # only the remaining body can yield UNKNOWN, never PRESENT.
                expected = prompt if complete else prompt[1:]
                for offset, char in enumerate(text):
                    if char != expected[0]:
                        continue
                    pending = [(start, text[offset:], reliable[start], frozenset({start}))]
                    visited = 0
                    while pending:
                        index, candidate, confident, path = pending.pop()
                        visited += 1
                        if visited > 256:
                            return 'unknown'
                        if candidate.startswith(expected):
                            if confident and complete:
                                return 'present'
                            uncertain = True
                            continue
                        if not expected.startswith(candidate):
                            continue
                        for nxt, part in enumerate(texts):
                            if nxt not in path and part and _adjacent(usable[index], usable[nxt]):
                                pending.append((nxt, candidate+part, confident and reliable[nxt], path | {nxt}))
    if uncertain or not any(ok and text for ok, text in zip(reliable, texts)):
        return 'unknown'
    return 'absent'
