import cv2
import numpy as np
import pytest

from keyboard_executor.core.chat_channel import (
    chat_input_has_text,
    find_public_menu_item,
    is_public_channel,
    locate_chat_input,
    locate_channel_button,
    same_chat_input_text,
)
from keyboard_executor.platforms.base import TextBox


def _chat_image(*, recipient="All", typed=False, menu=False):
    image = np.full((430, 440, 3), (20, 35, 55), dtype=np.uint8)
    image[379:417, 10:142] = 125
    image[385:417, 142:430] = 255
    cv2.putText(image, recipient, (24, 404), cv2.FONT_HERSHEY_SIMPLEX,
                .6, (255, 255, 255), 1, cv2.LINE_AA)
    if typed:
        cv2.putText(image, "hello", (148, 409), cv2.FONT_HERSHEY_SIMPLEX,
                    .8, (0, 0, 0), 2, cv2.LINE_AA)
    if menu:
        image[76:370, 10:142] = 85
        for y in range(102, 370, 33):
            cv2.putText(image, "Choice", (20, y), cv2.FONT_HERSHEY_SIMPLEX,
                        .5, (255, 255, 255), 1, cv2.LINE_AA)
    return image


def _box(text, *, y=290, x=20, confidence=.99):
    return TextBox(text, x, y, 90, 22, confidence)


@pytest.mark.parametrize('scale', [.75, 1, 1.5, 2])
def test_locates_whisper_dialog_field_above_chat_at_various_scales(scale):
    from keyboard_executor.core.chat_channel import locate_recipient_input
    image = np.zeros((600, 800, 3), dtype=np.uint8)
    image[90:235, 380:760] = (210, 150, 25)
    image[159:225, 392:748] = 238
    image[160:182, 400:730] = 255
    image[200:220, 610:665] = (20, 200, 150)
    image[200:220, 680:735] = (20, 200, 150)
    cv2.putText(image, 'Friend', (404, 176), cv2.FONT_HERSHEY_SIMPLEX,
                .5, (20, 20, 20), 1)
    image = cv2.resize(image, None, fx=scale, fy=scale)
    area = locate_recipient_input(image)
    assert area is not None
    x, y, w, h = area
    assert abs(x - 400*scale) <= 2 and abs(y - 160*scale) <= 2
    assert abs(w - 330*scale) <= 2 and abs(h - 22*scale) <= 2


def test_normal_chat_bar_does_not_count_as_recipient_dialog():
    from keyboard_executor.core.chat_channel import locate_recipient_input
    assert locate_recipient_input(_chat_image()) is None


@pytest.mark.parametrize('scale', [.75, 1, 1.5, 2])
def test_selected_recipient_does_not_cut_off_the_start_of_the_real_input(scale):
    from pathlib import Path
    from keyboard_executor.core.chat_channel import locate_recipient_input
    path = Path(__file__).parents[1] / 'fixtures/chat/whisper_recipient.png'
    image = cv2.imread(str(path))
    image = cv2.resize(image, None, fx=scale, fy=scale)
    area = locate_recipient_input(image)
    assert area is not None
    x, y, w, h = area
    assert abs(x - 39*scale) <= 2
    assert abs(y - 109*scale) <= 2
    assert abs(w - 445*scale) <= 2
    assert abs(h - 30*scale) <= 2


@pytest.mark.parametrize("recipient", ["All", "Somebody"])
@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
def test_locates_the_channel_button_regardless_of_recipient_and_dpi(recipient, scale):
    image = cv2.resize(_chat_image(recipient=recipient), None, fx=scale, fy=scale)

    result = locate_channel_button(image)

    assert result is not None
    x, y, width, height = result
    assert 20 * scale <= x + width / 2 <= 130 * scale
    assert 385 * scale <= y + height / 2 <= 415 * scale
    assert width >= 100 * scale
    assert height >= 20 * scale


@pytest.mark.parametrize("menu", [False, True])
def test_locates_button_with_short_text_already_in_the_white_input(menu):
    result = locate_channel_button(_chat_image(typed=True, menu=menu))

    assert result is not None
    x, y, width, height = result
    assert 20 <= x + width / 2 <= 130
    assert 385 <= y + height / 2 <= 415


def test_open_channel_menu_does_not_replace_the_button_location():
    result = locate_channel_button(_chat_image(menu=True))

    assert result is not None
    assert result[1] >= 379


def test_does_not_guess_a_button_from_chat_text_without_a_white_input():
    image = _chat_image()
    image[370:] = (20, 35, 55)
    cv2.putText(image, "All", (15, 410), cv2.FONT_HERSHEY_SIMPLEX,
                .8, (255, 255, 255), 1)

    assert locate_channel_button(image) is None


def test_white_input_without_an_adjacent_gray_button_is_not_enough():
    image = _chat_image()
    image[:, :142] = (20, 35, 55)

    assert locate_channel_button(image) is None


def test_rejects_two_plausible_input_bars_instead_of_picking_one():
    image = _chat_image()
    image[279:317, 10:142] = 125
    image[285:317, 142:430] = 255

    assert locate_channel_button(image) is None


@pytest.mark.parametrize("image", [
    np.zeros((0, 0, 3), dtype=np.uint8),
    np.zeros((430, 440), dtype=np.uint8),
    np.full((430, 440, 3), 255, dtype=np.uint8),
])
def test_missing_or_unusable_ui_returns_none(image):
    assert locate_channel_button(image) is None


@pytest.mark.parametrize("label", ["對所有人", " 對 所有人 ", "對所有人7", "對所有人 ▼"])
def test_public_channel_requires_the_exact_label_but_allows_the_ocr_arrow(label):
    assert is_public_channel([_box(label, confidence=.7)])


@pytest.mark.parametrize("label", [
    "朋友：對所有人", "對所有人說你好", "對所有人77", "對所有人V", "所有人", "對好友",
])
def test_chat_mentions_or_other_labels_do_not_confirm_public_channel(label):
    assert not is_public_channel([_box(label)])


def test_low_confidence_public_label_does_not_confirm_the_channel():
    assert not is_public_channel([_box("對所有人", confidence=.69)])
    assert not is_public_channel([])


def test_finds_public_menu_item_only_among_recognizable_sibling_rows():
    public = _box("對所有人")
    boxes = [public, _box("對好友", y=26), _box("對隊伍", y=92),
             _box("無關聊天", x=180, y=90)]

    assert find_public_menu_item(boxes) is public


@pytest.mark.parametrize("siblings", [
    [],
    [_box("對好友", y=257)],
    [_box("對好友", y=224), _box("對好友", y=257)],
    [_box("對好友", y=224), _box("對隊伍", y=257, confidence=.69)],
    [_box("對好友", y=224, x=180), _box("對隊伍", y=257, x=180)],
    [_box("路人：對好友", y=224), _box("路人：對隊伍", y=257)],
])
def test_chat_mentions_or_insufficient_menu_evidence_are_not_click_targets(siblings):
    assert find_public_menu_item([_box("對所有人"), *siblings]) is None


def test_duplicate_public_labels_make_the_menu_ambiguous():
    boxes = [_box("對所有人"), _box("對所有人", y=330),
             _box("對好友", y=224), _box("對隊伍", y=257)]

    assert find_public_menu_item(boxes) is None


def test_overlapping_ocr_fragments_are_not_two_sibling_menu_rows():
    boxes = [_box("對所有人"), _box("對好友", y=250), _box("對隊伍", y=250)]

    assert find_public_menu_item(boxes) is None


def test_low_confidence_public_menu_item_is_not_a_click_target():
    boxes = [_box("對所有人", confidence=.69),
             _box("對好友", y=224), _box("對隊伍", y=257)]

    assert find_public_menu_item(boxes) is None


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
def test_locates_inner_input_without_recipient_button_or_right_hand_icon(scale):
    image = _chat_image()
    image[389:415, 390:426] = (220, 170, 20)
    image = cv2.resize(image, None, fx=scale, fy=scale)

    result = locate_chat_input(image)

    assert result is not None
    x, y, width, height = result
    assert 141 * scale <= x <= 145 * scale
    assert 385 * scale <= y <= 387 * scale
    assert x + width <= 391 * scale
    assert width >= 200 * scale
    assert height >= 20 * scale
    assert chat_input_has_text(image[y:y + height, x:x + width]) is False


def test_does_not_locate_an_input_from_a_white_rectangle_without_the_channel_ui():
    image = np.full((430, 440, 3), 255, dtype=np.uint8)

    assert locate_chat_input(image) is None


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
def test_blinking_caret_does_not_prevent_locating_the_known_white_input(scale):
    image = _chat_image()
    image[390:412, 145:146] = 0
    image = cv2.resize(image, None, fx=scale, fy=scale)

    result = locate_chat_input(image)

    assert result is not None
    x, y, width, height = result
    assert chat_input_has_text(image[y:y + height, x:x + width]) is None


def _input_crop():
    return np.full((33, 300, 3), 255, dtype=np.uint8)


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
@pytest.mark.parametrize("caret", [False, True])
def test_empty_input_ignores_border_but_treats_a_lone_caret_as_unknown(scale, caret):
    image = _input_crop()
    image[0] = image[-1] = 120
    image[:, 0] = image[:, -1] = 120
    if caret:
        image[5:28, 2:3] = 0
    image = cv2.resize(image, None, fx=scale, fy=scale)

    assert chat_input_has_text(image) is (None if caret else False)


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
@pytest.mark.parametrize("text", ["hello", ".", "!", "?", "-", "_", "'", ":"])
def test_detects_remaining_ascii_text_and_single_punctuation(scale, text):
    image = _input_crop()
    cv2.putText(image, text, (6, 25), cv2.FONT_HERSHEY_SIMPLEX,
                .7, (0, 0, 0), 1, cv2.LINE_AA)
    image = cv2.resize(image, None, fx=scale, fy=scale)

    assert chat_input_has_text(image) is True


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
def test_detects_chinese_like_glyphs_and_preserves_image(scale):
    image = _input_crop()
    for left in [6, 31]:
        cv2.rectangle(image, (left, 6), (left + 18, 24), (0, 0, 0), 1)
        cv2.line(image, (left + 9, 3), (left + 9, 27), (0, 0, 0), 1)
        cv2.line(image, (left, 15), (left + 18, 15), (0, 0, 0), 1)
    image = cv2.resize(image, None, fx=scale, fy=scale)
    before = image.copy()

    assert chat_input_has_text(image) is True
    assert np.array_equal(image, before)


@pytest.mark.parametrize("color", [(40, 150, 200), (80, 80, 80), (215, 215, 215)])
def test_obscured_or_colored_input_cannot_be_reported_as_empty(color):
    image = _input_crop()
    image[5:28, 20:110] = color

    assert chat_input_has_text(image) is None


def test_isolated_vertical_stroke_away_from_the_start_is_ambiguous():
    image = _input_crop()
    image[5:28, 30:31] = 0

    assert chat_input_has_text(image) is None


def test_single_pixel_punctuation_at_left_edge_is_not_removed_as_a_frame():
    image = _input_crop()
    image[24:26, 1:2] = 0

    assert chat_input_has_text(image) is True


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
def test_a_single_pipe_is_never_mistaken_for_empty_input(scale):
    image = _input_crop()
    cv2.putText(image, "|", (6, 25), cv2.FONT_HERSHEY_SIMPLEX,
                .7, (0, 0, 0), 1, cv2.LINE_AA)
    image = cv2.resize(image, None, fx=scale, fy=scale)

    assert chat_input_has_text(image) is not False


@pytest.mark.parametrize("image", [
    np.zeros((0, 0, 3), dtype=np.uint8),
    np.full((33, 300), 255, dtype=np.uint8),
    np.full((33, 300, 3), 225, dtype=np.uint8),
    np.full((4, 300, 3), 255, dtype=np.uint8),
])
def test_unusable_or_nonwhite_input_is_unknown(image):
    assert chat_input_has_text(image) is None


def _draft(text, *, caret=False, scale=1.0):
    image = _input_crop()
    cv2.putText(image, text, (6, 25), cv2.FONT_HERSHEY_SIMPLEX,
                .7, (0, 0, 0), 1, cv2.LINE_AA)
    if caret:
        caret_x = 10 + cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .7, 1)[0][0]
        image[5:28, caret_x:caret_x + 1] = 0
    return cv2.resize(image, None, fx=scale, fy=scale)


@pytest.mark.parametrize("scale", [.75, 1.0, 1.5, 2.0])
@pytest.mark.parametrize("text", [".", "hello", "!"])
def test_same_draft_ignores_a_tail_caret_appearing_or_disappearing(scale, text):
    before = _draft(text, scale=scale)
    after = _draft(text, caret=True, scale=scale)
    original = after.copy()

    assert same_chat_input_text(before, after)
    assert same_chat_input_text(after, before)
    assert np.array_equal(after, original)


@pytest.mark.parametrize("before,after", [(".", "!"), ("hello", "hell!"), ("hi", "hil")])
def test_different_drafts_are_not_safe_to_resubmit(before, after):
    assert not same_chat_input_text(_draft(before), _draft(after, caret=True))


def test_tall_exclamation_stem_is_not_removed_as_a_caret():
    period = _input_crop()
    period[25:27, 10:12] = 0
    exclamation = period.copy()
    exclamation[3:23, 10:11] = 0

    assert not same_chat_input_text(period, exclamation)


def test_identical_visible_text_is_the_same_draft():
    image = _draft("hello")

    assert same_chat_input_text(image, image.copy())


@pytest.mark.parametrize('scale', [.75, 1, 1.5, 2])
def test_real_recipient_name_remains_readable_when_full_height_caret_blinks(scale):
    from pathlib import Path
    root = Path(__file__).parents[1] / 'fixtures/chat'
    before = cv2.imread(str(root / 'recipient_name.png'))
    after = cv2.imread(str(root / 'recipient_name_caret.png'))
    before = cv2.resize(before, None, fx=scale, fy=scale)
    after = cv2.resize(after, None, fx=scale, fy=scale)
    assert chat_input_has_text(before) is True
    assert chat_input_has_text(after) is True
    assert same_chat_input_text(before, after)
    assert same_chat_input_text(after, before)


@pytest.mark.parametrize("kind", ["empty", "caret", "colored", "obscured", "resized"])
def test_untrusted_or_missing_text_is_not_the_same_draft(kind):
    image = _draft(".")
    other = image.copy()
    if kind == "empty":
        other[:] = 255
    elif kind == "caret":
        other[:] = 255
        other[5:28, 2:3] = 0
    elif kind == "colored":
        other[5:25, 30:70] = (20, 80, 160)
    elif kind == "obscured":
        other[5:28, 30:120] = 80
    else:
        other = other[:-1]

    assert not same_chat_input_text(image, other)
    assert not same_chat_input_text(other, image)
