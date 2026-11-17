from pathlib import Path

import cv2
import numpy as np
import pytest

from keyboard_executor.core.minimap import find_player_dot

FIXTURES = Path(__file__).parents[1] / 'fixtures/minimap'


@pytest.mark.parametrize('name, expected', [
    ('tower-1.png', (144, 85)), ('tower-2.png', (139, 275)), ('tower-3.png', (208, 362)),
])
def test_finds_player_dot_on_real_minimaps(name, expected):
    dot = find_player_dot(cv2.imread(str(FIXTURES / name)))
    assert dot is not None
    assert abs(dot[0] - expected[0]) <= 1 and abs(dot[1] - expected[1]) <= 1


def test_finds_dot_in_live_window_crop():
    assert find_player_dot(cv2.imread(str(FIXTURES / 'toy-live.png'))) is not None


def test_small_yellow_icons_and_empty_maps_are_not_the_player():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(image, (20, 20), 3, (0, 230, 255), -1)        # ~30 px icon
    assert find_player_dot(image) is None


def test_two_similar_dots_are_ambiguous():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(image, (20, 20), 6, (0, 230, 255), -1)
    cv2.circle(image, (70, 70), 6, (0, 230, 255), -1)
    assert find_player_dot(image) is None


def test_scaled_capture_uses_scaled_area():
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(image, (100, 50), 11, (0, 230, 255), -1)
    assert find_player_dot(image, scale=2) == pytest.approx((100, 50), abs=.5)
    small = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(small, (100, 50), 5, (0, 230, 255), -1)
    assert find_player_dot(small, scale=2) is None
