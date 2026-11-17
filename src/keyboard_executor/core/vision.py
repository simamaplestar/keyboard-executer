"""跨平台視覺演算法（純 numpy/OpenCV，無平台差異，可完整單元測試）。

- 模板比對：cv2.matchTemplate + TM_CCOEFF_NORMED，回傳命中中心座標與信心值
- 文字搜尋（Task 4）：對 OCR 產出的 TextBox 清單做 contains/regex 比對
- 顏色偵測：count_color_pixels 數區域內落在 HSV 範圍的像素；sample_dominant_hsv 取樣代表色
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from keyboard_executor.core.color_math import hue_ranges


@dataclass(frozen=True)
class TemplateMatch:
    found: bool
    x: int          # 命中區域中心（搜尋影像座標系，實體像素）
    y: int
    confidence: float


def match_template(image: np.ndarray, template: np.ndarray,
                   threshold: float = 0.85, grayscale: bool = True,
                   mirror: bool = False) -> TemplateMatch:
    """在 image 中找 template。grayscale 預設 True（對亮度變化較穩健，spec §8.2）。
    回傳命中中心座標；confidence >= threshold 時 found=True。
    mirror=True 時也比對左右翻轉的模板（遊戲角色/怪物會面向兩邊），取較佳者。"""
    if mirror:
        normal = match_template(image, template, threshold, grayscale)
        flipped = match_template(image, cv2.flip(template, 1), threshold, grayscale)
        return flipped if flipped.confidence > normal.confidence else normal
    img = image
    tpl = template
    if grayscale:
        img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    th, tw = template.shape[:2]

    # 均勻（零變異）模板會讓 TM_CCOEFF_NORMED 對所有位置回傳 1.0（0/0 相關比），
    # 屬無意義比對：信心值歸 0、found=False，中心座標仍比照未命中路徑指向最佳位置。
    if tpl.std() == 0:
        return TemplateMatch(found=False, x=tw // 2, y=th // 2, confidence=0.0)

    result = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(result)
    center_x = int(max_loc[0] + tw / 2)
    center_y = int(max_loc[1] + th / 2)
    return TemplateMatch(found=bool(max_v >= threshold),
                         x=center_x, y=center_y, confidence=float(max_v))


def find_text(boxes: "list", pattern: str, mode: str = "contains"):
    """在 OCR TextBox 清單中找符合 pattern 的第一個框；皆不中回傳 None。
    mode="contains"：子字串；mode="regex"：re.search。"""
    for b in boxes:
        if mode == "regex":
            if re.search(pattern, b.text):
                return b
        elif pattern in b.text:
            return b
    return None


_SAT_FLOOR = 40   # 飽和度地板：低於此值視為灰/白，一律不算命中——避免取到低飽和色
                  # 時 (sat - sat_tol) 掉到 0，把整片灰色都算進來造成廣泛誤命中。


def count_color_pixels(image_bgr: np.ndarray, hue: int, sat: int, val: int,
                       hue_tol: int = 10, sat_tol: int = 80,
                       val_tol: int = 80) -> int:
    """區域 BGR → HSV，回符合目標顏色的像素數。
    H 落在 hue_ranges(hue, hue_tol)（環繞用多段 OR）、
    S >= max(_SAT_FLOOR, sat - sat_tol)、V >= clamp(val - val_tol)。"""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    sv_ok = (s >= max(_SAT_FLOOR, sat - sat_tol)) & (v >= max(0, val - val_tol))
    hue_ok = np.zeros(h.shape, dtype=bool)
    for lo, hi in hue_ranges(hue, hue_tol):
        hue_ok |= (h >= lo) & (h <= hi)
    return int(np.count_nonzero(hue_ok & sv_ok))


def sample_dominant_hsv(image_bgr: np.ndarray) -> tuple[int, int, int]:
    """一小塊 BGR patch → 代表 HSV：取飽和度最高的像素（避開反鋸齒淡邊）。"""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    flat = hsv.reshape(-1, 3)
    idx = int(flat[:, 1].argmax())
    return int(flat[idx, 0]), int(flat[idx, 1]), int(flat[idx, 2])


def encode_png(image_bgr: np.ndarray) -> bytes:
    """BGR 影像編碼成 PNG bytes（沿用 OpenCV BGR 慣例，顏色正確）。編碼失敗拋 ValueError。"""
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ValueError("PNG 編碼失敗")
    return buf.tobytes()
