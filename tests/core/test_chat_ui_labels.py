"""Fixed UI labels accept script variants without rewriting chat/name text."""
from dataclasses import replace
from pathlib import Path

import cv2
import pytest

from keyboard_executor.core.chat_channel import (
    find_public_menu_item, is_public_channel, is_recipient_prompt,
)
from keyboard_executor.platforms.base import TextBox
from tests.core.test_chat_reply import close_sessions, make_session


def test_real_recipient_modal_accepts_the_recorded_tiny_output():
    # Tiny 3.9.2 + v6 emitted simplified 请 at .97084 on this real modal.
    # Exercise both pre-typing validation and the subsequent glyph freshness check.
    image = cv2.imread(str(Path(__file__).parents[1] / 'fixtures/chat/whisper_recipient.png'))
    session, _, win, backend, _, _, _ = make_session(visual_delivery=True)
    win = replace(win, x=0, y=0, width=image.shape[1], height=image.shape[0])
    session._platform.window_manager.windows = [win]
    session._platform.screen_capture.capture = lambda r: image[r.y:r.y+r.height, r.x:r.x+r.width].copy()
    session._platform.ocr_engine.recognize = lambda _: [
        TextBox('请輸入密語對象。', 141, 22, 156, 24, .97084),
        TextBox('MMDxD', 228, 49, 85, 23, .92955),
    ]

    assert session._prepare_recipient_input(win) == (39, 109, 445, 30)
    assert backend.calls == []


@pytest.mark.parametrize('text', [
    '請輸入密語對象。', '请輸入密語對象。', '请输入密语对象:',
    '請 输 入 密语 對象',
    '讀输入密語對象。',  # 視窗縮小到 0.55 倍時實測讀錯第一字
    '讀輸入密語封象。',  # 另一台電腦 1296x759 實測
    '请輸入密語對像', '请蛛入密語對象·',
])
def test_fixed_recipient_caption_accepts_traditional_simplified_and_mixed(text):
    box = TextBox(text, 10, 10, 160, 24, .97)
    assert is_recipient_prompt([box])
    assert box.text == text


@pytest.mark.parametrize('text,confidence', [
    ('请输入交易金额', .99), ('請輸入密語對象嗎', .99),
    ('朋友:请輸入密語對象', .99), ('请輸入密語對象。', .69),
    ('', .99), ('讀讀入密語對像', .99), ('請輸入密語對', .99),
    ('請輸入秘密對象', .99), ('请輸入密語對象。', .69),
])
def test_other_lookalike_or_low_confidence_captions_still_fail(text, confidence):
    assert not is_recipient_prompt([TextBox(text, 10, 10, 160, 24, confidence)])


def test_public_channel_and_menu_accept_script_variants_with_existing_geometry_checks():
    target = TextBox('对所有人', 20, 290, 90, 22, .99)
    group = TextBox('对群组', 20, 224, 90, 22, .99)
    team = TextBox('對队伍', 20, 257, 90, 22, .99)
    assert is_public_channel([target])
    assert find_public_menu_item([target, group, team]) is target
    assert find_public_menu_item([target]) is None
    assert find_public_menu_item([target, group, replace(team, x=190)]) is None
    assert not is_public_channel([replace(target, text='朋友:对所有人')])
    assert not is_public_channel([replace(target, confidence=.69)])
    assert target.text == '对所有人'


def test_unreadable_recipient_title_is_reread_before_giving_up():
    # 另一台電腦：第一次 OCR 沒讀到標題就直接停掉腳本；應在時限內重讀。
    image = cv2.imread(str(Path(__file__).parents[1] / 'fixtures/chat/whisper_recipient.png'))
    session, _, win, backend, _, _, _ = make_session(visual_delivery=True)
    win = replace(win, x=0, y=0, width=image.shape[1], height=image.shape[0])
    session._platform.window_manager.windows = [win]
    session._platform.screen_capture.capture = lambda r: image[r.y:r.y+r.height, r.x:r.x+r.width].copy()
    shots = iter(range(1000))

    def capture(r):
        crop = image[r.y:r.y+r.height, r.x:r.x+r.width].copy()
        crop[0, 0] = next(shots) % 250   # 淡入動畫：每次擷取像素都不同，不重用 OCR 快取
        return crop

    session._platform.screen_capture.capture = capture
    reads = iter([[TextBox('讀输入密語', 141, 22, 120, 24, .60)],
                  [TextBox('请輸入密語對象。', 141, 22, 156, 24, .97)]])
    session._platform.ocr_engine.recognize = lambda _: next(reads)
    assert session._prepare_recipient_input(win) == (39, 109, 445, 30)
    assert backend.calls == []


def test_recipient_title_never_read_reports_what_ocr_saw():
    image = cv2.imread(str(Path(__file__).parents[1] / 'fixtures/chat/whisper_recipient.png'))
    session, _, win, backend, _, _, _ = make_session(visual_delivery=True)
    win = replace(win, x=0, y=0, width=image.shape[1], height=image.shape[0])
    session._platform.window_manager.windows = [win]
    session._platform.screen_capture.capture = lambda r: image[r.y:r.y+r.height, r.x:r.x+r.width].copy()
    session._platform.ocr_engine.recognize = lambda _: [TextBox('交易', 141, 22, 60, 24, .99)]
    with pytest.raises(RuntimeError, match='標題讀到: 交易'):
        session._prepare_recipient_input(win)
    assert backend.calls == []
