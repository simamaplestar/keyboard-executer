import numpy as np

from keyboard_executor.core.vision import TemplateMatch, match_template


def make_scene(patch, at):
    """640x480x3 灰底大圖，把 patch 貼到 (x, y)=at 位置。"""
    scene = np.full((480, 640, 3), 128, dtype=np.uint8)
    x, y = at
    h, w = patch.shape[:2]
    scene[y:y + h, x:x + w] = patch
    return scene


def make_patch():
    patch = np.zeros((40, 60, 3), dtype=np.uint8)
    patch[:, :, 2] = 255  # 紅色圖塊（BGR）
    patch[10:30, 20:40] = (0, 255, 0)  # 內含綠色方塊，具辨識特徵
    return patch


def test_found_returns_center_within_tolerance():
    patch = make_patch()
    scene = make_scene(patch, at=(300, 200))
    m = match_template(scene, patch, threshold=0.85)
    assert m.found is True
    # 中心 = (300 + 60/2, 200 + 40/2) = (330, 220)
    assert abs(m.x - 330) <= 1 and abs(m.y - 220) <= 1
    assert m.confidence >= 0.85


def test_not_found_below_threshold():
    scene = np.full((480, 640, 3), 128, dtype=np.uint8)
    other = np.zeros((40, 60, 3), dtype=np.uint8)
    other[:, :, 0] = 255  # 場景裡沒有的藍塊
    m = match_template(scene, other, threshold=0.95)
    assert m.found is False
    assert m.confidence < 0.95


def test_grayscale_default_still_matches_color_patch():
    patch = make_patch()
    scene = make_scene(patch, at=(100, 50))
    m = match_template(scene, patch)  # grayscale=True 預設
    assert m.found is True
    assert abs(m.x - 130) <= 1 and abs(m.y - 70) <= 1


def test_color_mode_matches_too():
    patch = make_patch()
    scene = make_scene(patch, at=(10, 10))
    m = match_template(scene, patch, grayscale=False)
    assert m.found is True
    assert abs(m.x - 40) <= 1 and abs(m.y - 30) <= 1


def test_confidence_high_for_exact_patch():
    patch = make_patch()
    scene = make_scene(patch, at=(0, 0))
    m = match_template(scene, patch)
    assert m.confidence > 0.99
    assert isinstance(m, TemplateMatch)


def asymmetric_patch():
    patch = np.zeros((40, 60, 3), dtype=np.uint8)
    patch[:, :20] = (0, 0, 255)
    patch[:, 20:40] = (0, 255, 0)
    patch[5:15, 45:55] = (255, 255, 255)
    return patch


def test_mirror_finds_horizontally_flipped_sprite():
    import cv2
    patch = asymmetric_patch()
    scene = make_scene(cv2.flip(patch, 1), at=(300, 200))
    assert match_template(scene, patch, threshold=0.9).found is False
    m = match_template(scene, patch, threshold=0.9, mirror=True)
    assert m.found and abs(m.x - 330) <= 1 and abs(m.y - 220) <= 1


def test_mirror_still_finds_original_orientation():
    patch = asymmetric_patch()
    scene = make_scene(patch, at=(100, 50))
    assert match_template(scene, patch, threshold=0.9, mirror=True).found
