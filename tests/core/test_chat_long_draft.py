"""Dense Chinese drafts still need Enter; white-field guards must not reject them."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from keyboard_executor.core.chat_channel import chat_input_has_text, same_chat_input_text
from keyboard_executor.core.chat_observer import ChatMessage
from tests.core.test_chat_reply_channel import channel_session


def dense_draft():
    # Synthetic 900x30 field, Microsoft JhengHei Bold 22px. No game capture or
    # dependency on an installed font at test time. Only 71.7% is white despite
    # intact margins and distinct, normally sized Chinese glyphs.
    path = Path(__file__).parents[1] / 'fixtures/chat/long_chinese_draft.png'
    return cv2.imread(str(path))


def test_real_game_long_draft_is_visible_despite_reduced_white_background():
    path = Path(__file__).parents[1] / 'fixtures/chat/long_chinese_game_draft.png'
    image = cv2.imread(str(path))
    assert image.shape == (33, 730, 3)
    assert chat_input_has_text(image) is True
    assert same_chat_input_text(image, image.copy())


@pytest.mark.parametrize('scale', [.75, 1, 1.5, 2])
def test_dense_chinese_draft_is_visible_with_or_without_blinking_caret(scale):
    image = dense_draft()
    caret = image.copy()
    caret[:, -4:-3] = 0
    image, caret = [cv2.resize(frame, None, fx=scale, fy=scale) for frame in (image, caret)]
    original = image.copy()
    assert chat_input_has_text(image) is True
    assert chat_input_has_text(caret) is True
    assert same_chat_input_text(image, caret)
    assert same_chat_input_text(caret, image)
    assert np.array_equal(image, original)


@pytest.mark.parametrize('color', [(0, 0, 0), (80, 80, 80), (215, 215, 215), (20, 120, 220)])
def test_dense_draft_with_overlay_cannot_be_confirmed_or_resubmitted(color):
    image = dense_draft()
    covered = image.copy()
    covered[5:-5, 200:500] = color
    assert chat_input_has_text(covered) is None
    assert not same_chat_input_text(image, covered)


@pytest.mark.parametrize('width,height', [(45, 15), (60, 18), (45, 8), (60, 6), (89, 4)])
def test_solid_block_is_not_mistaken_for_joined_chinese_glyphs(width, height):
    image = np.full((30, 900, 3), 255, dtype=np.uint8)
    image[5:5+height, 10:10+width] = 80
    assert chat_input_has_text(image) is None


@pytest.mark.parametrize('covered', [False, True])
def test_dense_reply_reaches_enter_only_when_its_field_is_clear(channel_session, covered):
    session, win, _, _, _, scene = channel_session
    capture = scene.capture
    draft = dense_draft()[:, :182].copy()
    if covered:
        draft[5:-5, 20:160] = 80

    def capture_draft(rect):
        image = capture(rect)
        if scene.draft:
            # Paint at the same editable field as ChannelScene, at native scale.
            left, top = win.x + 148, win.y + 465
            x1, y1 = max(left, rect.x), max(top, rect.y)
            x2, y2 = min(left+182, rect.x+rect.width), min(top+30, rect.y+rect.height)
            if x2 > x1 and y2 > y1:
                image[y1-rect.y:y2-rect.y, x1-rect.x:x2-rect.x] = draft[
                    y1-top:y2-top, x1-left:x2-left]
        return image

    scene.capture = capture_draft
    message = ChatMessage(1, 'whisper', '朋友', '在嗎')
    reply = '這是一段比較長的中文回覆, 要確認文字出現之後才送出, 回完再接著執行腳本'
    if covered:
        with pytest.raises(RuntimeError, match='未確認回覆文字出現在輸入框'):
            session._send_replies([(message, reply)], win)
        assert scene.draft == reply and not scene.sent
    else:
        session._send_replies([(message, reply)], win)
        assert scene.sent == [(reply, 'whisper')]
        assert not scene.draft and not scene.input_focused
        assert scene.channel == 'public'
