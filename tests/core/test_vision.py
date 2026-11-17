import cv2
import numpy as np

from keyboard_executor.core.vision import count_color_pixels, sample_dominant_hsv, encode_png


def test_count_color_pixels_counts_red_block():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)                      # BGR 純紅
    assert count_color_pixels(img, 0, 255, 255) == 100


def test_count_color_pixels_ignores_grey():
    img = np.full((10, 10, 3), 128, dtype=np.uint8)   # 灰：飽和度 0
    assert count_color_pixels(img, 0, 255, 255) == 0


def test_count_color_pixels_matches_red_near_upper_hue():
    hsv = np.zeros((4, 4, 3), dtype=np.uint8)
    hsv[:, :] = (178, 255, 255)                  # 接近 179 的紅
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert count_color_pixels(bgr, 0, 255, 255, hue_tol=10) == 16


def test_sample_dominant_hsv_picks_saturated_pixel():
    patch = np.full((5, 5, 3), 128, dtype=np.uint8)   # 灰底
    patch[2, 2] = (0, 0, 255)                          # 一顆紅
    h, s, v = sample_dominant_hsv(patch)
    assert h == 0 and s == 255


def test_count_color_pixels_low_sat_target_still_excludes_grey():
    # 取樣到低飽和色時，飽和地板仍應排除灰色像素（避免廣泛誤命中）
    grey = np.full((10, 10, 3), 128, dtype=np.uint8)   # S=0
    assert count_color_pixels(grey, 0, 50, 200) == 0


def test_encode_png_returns_png_magic_bytes():
    from keyboard_executor.core.vision import encode_png
    data = encode_png(np.zeros((4, 4, 3), dtype=np.uint8))
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data[:8]) == b"\x89PNG\r\n\x1a\n"   # PNG 檔頭 magic
