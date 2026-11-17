"""本地 CV 定位的合成影像測試：任何一步不可信都必須回 None，不猜位置。"""
import numpy as np
import cv2

from keyboard_executor.core.sequence_panel_vision import (
    find_input_box, find_confirm, find_carousel, carousel_index, carousel_image,
    analyze_panel,
)
from keyboard_executor.platforms.base import TextBox


def dialog(*, with_input=True, with_button=True, with_carousel=True):
    """520x400 仿測謊面板：淺灰底、白色輸入框、綠色按鈕、雜訊輪播圖。"""
    rng = np.random.default_rng(7)
    image = np.full((400, 520, 3), 238, np.uint8)
    if with_input:
        cv2.rectangle(image, (97, 325), (391, 358), (255, 255, 255), -1)
    if with_button:
        cv2.rectangle(image, (400, 320), (445, 355), (80, 200, 60), -1)  # BGR 綠
    carousel = None
    if with_carousel:
        noise = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
        image[170:270, 190:290] = noise
        carousel = (190, 170, 100, 100)
    return image, carousel


def test_input_box_found_and_stable():
    image, _ = dialog()
    assert find_input_box(image) == (97, 325, 392, 359)


def test_input_box_absent_returns_none():
    image, _ = dialog(with_input=False)
    assert find_input_box(image) is None


def test_confirm_only_right_of_input():
    image, _ = dialog()
    box = find_confirm(image, find_input_box(image))
    # 水平來自綠色 blob；垂直固定為輸入框同列搜尋窗（325-12, 359+12）
    assert box is not None and box[0] >= 392 and box[1] == 313 and box[3] == 371


def test_confirm_requires_input_and_button():
    image, _ = dialog(with_button=False)
    assert find_confirm(image, find_input_box(image)) is None
    image, _ = dialog(with_input=False)
    assert find_confirm(image, None) is None


def test_carousel_found_between_prompt_and_input():
    image, expected = dialog()
    found = find_carousel(image, find_input_box(image))
    assert found is not None
    x, y, w, h = found
    assert abs(x - expected[0]) <= 8 and abs(y - expected[1]) <= 8
    assert 60 <= w <= 140 and 60 <= h <= 140


def test_carousel_absent_returns_none():
    image, _ = dialog(with_carousel=False)
    assert find_carousel(image, find_input_box(image)) is None


def test_index_accepts_any_corner():
    image, carousel = dialog()
    # 子圖 500x500（100*5）：四角編號皆可
    calls = []
    assert carousel_index(image, carousel,
                          lambda img: calls.append(img.shape) or [TextBox('2', 40, 2, 10, 14, .99)]) == 2
    assert calls and calls[0][0] > 100  # 子圖有放大
    assert carousel_index(image, carousel,
                          lambda img: [TextBox('3', 445, 2, 10, 14, .99)]) == 3
    assert carousel_index(image, carousel,
                          lambda img: [TextBox('1', 445, 440, 10, 14, .99)]) == 1  # 右下角
    # 水平或垂直中央讀數（可能是字元筆畫）不信
    assert carousel_index(image, carousel,
                          lambda img: [TextBox('2', 240, 2, 10, 14, .99)]) is None
    assert carousel_index(image, carousel,
                          lambda img: [TextBox('2', 40, 240, 10, 14, .99)]) is None
    # 中央誤讀 + 角落正確：取角落
    boxes = [TextBox('1', 230, 10, 10, 14, .99), TextBox('2', 448, 4, 10, 14, .99)]
    assert carousel_index(image, carousel, lambda img: boxes) == 2


def test_index_rejects_low_confidence_and_non_digit():
    image, carousel = dialog()
    assert carousel_index(image, carousel, lambda img: [TextBox('2', 0, 0, 10, 10, .7)]) is None
    assert carousel_index(image, carousel, lambda img: [TextBox('X2', 0, 0, 20, 10, .99)]) is None
    assert carousel_index(image, carousel, lambda img: [TextBox('7', 0, 0, 10, 10, .99)]) is None


def test_carousel_image_upscaled():
    image, carousel = dialog()
    crop = carousel_image(image, carousel)
    assert crop.shape[0] == carousel[3] * 3 and crop.shape[1] == carousel[2] * 3


def test_analyze_panel_normalizes_boxes():
    image, _ = dialog()
    vision = analyze_panel(image, lambda img: [])
    h, w = image.shape[:2]
    assert vision.index is None  # 合成雜訊不應冒出數字
    assert vision.input_box == (round(97*1000/w), round(325*1000/h),
                                round(392*1000/w), round(359*1000/h))
    assert vision.confirm_box is not None and vision.crop is not None
