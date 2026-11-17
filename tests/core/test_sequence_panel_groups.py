"""輪播圖 ahash 群組 + AI 編號後援：本地 OCR 讀不出編號時的解析規則。"""
import threading
from types import SimpleNamespace

import numpy as np

from keyboard_executor.core.sequence_panel_vision import PanelVision
from keyboard_executor.core.sequence_panel_watcher import PanelWatcher, _ImageGroup
from tests.core.test_sequence_panel import reading
from tests.core.test_sequence_panel_helpers import make_panel_watcher, step, settle, PROMPT


def _pattern(seed):
    """產生指定 seed 的 32x32 非均勻圖（ahash 可區分）；首像素內嵌 seed 供測試還原。"""
    rng = np.random.default_rng(seed)
    crop = rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)
    crop[0, 0] = (10 + seed * 200, 0, 0)
    return crop


def _make(index_by_seed, digit_by_seed, char_by_seed):
    """vision：依影像內嵌 seed 決定輪播圖；recognizer：字元與 AI 編號後援。"""
    def vision(image, _recognize):
        stamp = int(image[0, 0, 0]) if image.size else 0
        seed = stamp % 2  # 兩張圖輪替：偶數 stamp → 圖 A、奇數 → 圖 B
        crop = _pattern(seed)
        return PanelVision(index=index_by_seed(seed, stamp), input_box=(100, 600, 600, 750),
                           confirm_box=(650, 600, 900, 750), crop=crop)

    def recognize(samples, **kwargs):
        return [reading(s.sample_id, 1, char_by_seed(1 if s.image[0, 0, 0] > 128 else 0))
                for s in samples]

    def recognize_digits(samples, **kwargs):
        from keyboard_executor.core.ai.sequence_char_recognizer import DigitReading
        return [DigitReading(s.sample_id, digit_by_seed(1 if s.image[0, 0, 0] > 128 else 0))
                for s in samples]

    return vision, SimpleNamespace(recognize=recognize, recognize_digits=recognize_digits)


def _drive(watcher, platform, now, count):
    settle(watcher, lambda: bool(platform.ocr_engine.calls) and not watcher._ocr_busy)
    platform.ocr_engine._boxes = PROMPT
    for t in range(1, count + 1):
        step(watcher, platform, now, t)
        settle(watcher, lambda: not watcher._ai_running and not watcher._ai_pending)


def test_ai_digit_fallback_resolves_after_two_agreeing_votes():
    # 本地讀不出編號；AI 編號後援圖 A→1、圖 B→2；字元 A→N、B→G
    vision, recognizer = _make(lambda seed, stamp: None,
                               lambda seed: seed + 1,
                               lambda seed: 'NG'[seed])
    watcher, platform, win, now, stop, calls = make_panel_watcher(recognizer=recognizer)
    watcher._vision = vision
    try:
        watcher.start(win)
        _drive(watcher, platform, now, 8)
        locked = watcher._round._locked
        assert locked == {1: 'N', 2: 'G'}
    finally:
        stop.set()
        watcher.close()


def test_single_ai_digit_vote_does_not_resolve():
    # 只出現一次的圖（一票）不得解析
    vision, recognizer = _make(lambda seed, stamp: None,
                               lambda seed: seed + 1,
                               lambda seed: 'NG'[seed])
    watcher, platform, win, now, stop, calls = make_panel_watcher(recognizer=recognizer)
    watcher._vision = vision
    try:
        watcher.start(win)
        _drive(watcher, platform, now, 2)  # 圖A一票、圖B一票
        assert watcher._round._locked == {}
        assert all(g.index is None for g in watcher._groups)
    finally:
        stop.set()
        watcher.close()


def test_local_index_sibling_resolves_group():
    # 圖 A 首次（stamp=2）本地讀到 1，之後同圖本地讀不出 → 沿用群組編號投票
    def index_by_seed(seed, stamp):
        if seed == 1:
            return 2
        return 1 if stamp == 2 else None

    vision, recognizer = _make(index_by_seed, lambda seed: None, lambda seed: 'NG'[seed])
    watcher, platform, win, now, stop, calls = make_panel_watcher(recognizer=recognizer)
    watcher._vision = vision
    try:
        watcher.start(win)
        _drive(watcher, platform, now, 6)
        assert watcher._round._locked.get(1) == 'N'
    finally:
        stop.set()
        watcher.close()


def test_conflicting_digit_with_other_group_never_resolves():
    # 圖 B 的 AI 編號後援也回 1（與圖 A 衝突）→ 圖 B 群組封鎖，不猜
    vision, recognizer = _make(lambda seed, stamp: None,
                               lambda seed: 1,  # 兩張圖都回 1
                               lambda seed: 'NG'[seed])
    watcher, platform, win, now, stop, calls = make_panel_watcher(recognizer=recognizer)
    watcher._vision = vision
    try:
        watcher.start(win)
        _drive(watcher, platform, now, 8)
        locked = watcher._round._locked
        # 先解析的群組取得 1；另一群組衝突封鎖，不得產生第二個 1 的投票來源
        groups = [g for g in watcher._groups if g.index == 1]
        assert len(groups) == 1
        assert any(g.blocked for g in watcher._groups if g.index is None)
        assert set(locked) <= {1}
    finally:
        stop.set()
        watcher.close()


def test_group_index_unit_rules():
    watcher, platform, win, now, stop, calls = make_panel_watcher()
    try:
        crop_a, crop_b = _pattern(0), _pattern(1)
        va = PanelVision(None, None, None, crop_a)
        vb = PanelVision(None, None, None, crop_b)
        # 一票不解析
        assert watcher._group_index(va, 1) is None
        # 同圖第二票且多數 → 解析
        assert watcher._group_index(va, 1) == 1
        # 另一張圖同編號 → 衝突封鎖
        assert watcher._group_index(vb, 1) is None
        assert watcher._group_index(vb, 1) is None
        # 本地編號直接定，且與群組既有編號一致
        va_local = PanelVision(1, None, None, crop_a)
        assert watcher._group_index(va_local, None) == 1
        # 本地編號永遠優先（指紋碰撞或 OCR 異常不封鎖本地結果）
        va_bad = PanelVision(3, None, None, crop_a)
        assert watcher._group_index(va_bad, None) == 3
    finally:
        stop.set()
        watcher.close()
