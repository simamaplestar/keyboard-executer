import numpy as np

from keyboard_executor.core.vision import find_text
from keyboard_executor.platforms.base import TextBox
from tests.fakes import FakeOcrEngine


def box(text, x=0, y=0, w=10, h=10, conf=0.9):
    return TextBox(text=text, x=x, y=y, width=w, height=h, confidence=conf)


def test_find_text_contains_substring():
    boxes = [box("開始遊戲"), box("連線中斷，請重試")]
    hit = find_text(boxes, "連線中斷", mode="contains")
    assert hit is not None and hit.text == "連線中斷，請重試"


def test_find_text_contains_no_match_returns_none():
    boxes = [box("開始遊戲"), box("設定")]
    assert find_text(boxes, "連線中斷") is None


def test_find_text_regex_mode():
    boxes = [box("HP 100/100"), box("等級 42")]
    hit = find_text(boxes, r"等級 \d+", mode="regex")
    assert hit is not None and hit.text == "等級 42"


def test_find_text_returns_first_match():
    boxes = [box("重試 A"), box("重試 B")]
    hit = find_text(boxes, "重試")
    assert hit.text == "重試 A"


def test_fake_ocr_engine_recognize_returns_queued_boxes():
    eng = FakeOcrEngine(boxes=[[box("第一輪")], [box("第二輪")]])
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    assert [b.text for b in eng.recognize(img)] == ["第一輪"]
    assert [b.text for b in eng.recognize(img)] == ["第二輪"]
    assert len(eng.calls) == 2
