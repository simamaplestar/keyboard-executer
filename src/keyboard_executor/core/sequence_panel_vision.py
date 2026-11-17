"""完整面板的本地 CV 定位：輸入框、確認按鈕、輪播小圖與編號。

全部純函式、無 I/O、無執行緒；任何一步不可信就回 None，由呼叫方保守處理，
絕不猜位置。數字編號用本地 OCR（放大的小圖右上角），AI 只需要辨識字元。
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PanelVision:
    index: int | None               # 本地 OCR 讀到的輪播編號 1/2/3
    input_box: tuple[int, int, int, int] | None    # 正規化 0-1000
    confirm_box: tuple[int, int, int, int] | None  # 正規化 0-1000
    crop: np.ndarray | None         # 放大後的輪播小圖（送 AI 辨識字元用）


def _norm(box, width, height):
    l, t, r, b = box
    return (round(l * 1000 / width), round(t * 1000 / height),
            round(r * 1000 / width), round(b * 1000 / height))


def find_input_box(image: np.ndarray):
    """白色輸入框：面板下半部最寬的扁近白實心區塊。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = (gray > 245).astype(np.uint8) * 255
    h, w = mask.shape
    mask[:int(h * .55), :] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if bw > w * .35 and .03 * h < bh < .2 * h and area > bw * bh * .8:
            if best is None or bw > best[2] - best[0]:
                best = (int(x), int(y), int(x + bw), int(y + bh))
    return best


def find_confirm(image: np.ndarray, inbox):
    """綠色確認按鈕：只接受輸入框右側同列的最大綠色連通塊。"""
    if inbox is None:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 80, 80), (95, 255, 255))
    h, w = mask.shape
    keep = np.zeros_like(mask)
    y0, y1 = max(0, inbox[1] - 12), min(h, inbox[3] + 12)
    keep[y0:y1, inbox[2] + 2:] = 255
    mask = cv2.bitwise_and(mask, keep)
    # 侵蝕去除按鈕上緣的稀疏雜訊條，避免 bbox 頂端跨帧抖動導致定位不穩
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    blobs = [(stats[i, 4], stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3])
             for i in range(1, count)
             if stats[i, 4] > 80 and .03 * w < stats[i, 2] < .3 * w
             and .03 * h < stats[i, 3] < .25 * h]
    if not blobs:
        return None
    # 垂直範圍固定為搜尋窗（按鈕與輸入框同列）：游標遮住按鈕時
    # 綠色像素垂直範圍會抖動，固定範圍才能跨帧保持 IoU 穩定。
    area, x, y, bw, bh = max(blobs)
    return (int(x), int(y0), int(min(x + bw, w)), int(y1))


def find_carousel(image: np.ndarray, inbox):
    """輪播小圖：提示文字與輸入框之間最「忙」的矩形（深色線條或飽和色）。"""
    h, w = image.shape[:2]
    top = int(h * .38)
    bottom = (inbox[1] - 6) if inbox else int(h * .8)
    if bottom - top < h * .15:
        return None
    band = image[top:bottom, :]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    busy = ((gray < 190) | (hsv[:, :, 1] > 45)).astype(np.uint8) * 255
    busy = cv2.morphologyEx(busy, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(busy)
    best = None
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if (.1 * w < bw < .6 * w and .25 * (bottom - top) < bh < .95 * (bottom - top)
                and area > bw * bh * .25):
            if best is None or area > best[4]:
                best = (int(x), int(y + top), int(bw), int(bh), int(area))
    return best[:4] if best else None


def carousel_index(image: np.ndarray, carousel, recognize) -> int | None:
    """小圖四角放大 OCR 編號；單一字元 1/2/3、信心 ≥ .85、只信靠角落的讀數。

    編號可能出現在任一角落（反 OCR 隨機化），扭曲字元主體在小圖中央，
    因此排除中央讀數、取離最近角落最近者。
    """
    x, y, w, h = carousel
    sub = image[y:y + h, x:x + w]
    if sub.size == 0:
        return None
    big = cv2.resize(sub, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
    sh, sw = big.shape[:2]
    best = None
    for box in recognize(big):
        text = box.text.strip()
        if len(text) != 1 or text not in "123" or box.confidence < .85:
            continue
        cx, cy = box.x + box.width / 2, box.y + box.height / 2
        if not (cx < sw * .35 or cx > sw * .65):  # 水平中央：可能是字元筆畫，不信
            continue
        if not (cy < sh * .4 or cy > sh * .6):    # 垂直中央：同上
            continue
        dist = min(cx ** 2 + cy ** 2, (sw - cx) ** 2 + cy ** 2,
                   cx ** 2 + (sh - cy) ** 2, (sw - cx) ** 2 + (sh - cy) ** 2) ** .5
        if best is None or dist < best[0]:
            best = (dist, int(text))
    return best[1] if best else None


def crop_fingerprint(crop: np.ndarray) -> int:
    """輪播小圖的 16x16 平均雜湊；同一張圖跨帧距離小（≲30），不同圖距離大（≳100）。"""
    gray = cv2.cvtColor(cv2.resize(crop, (16, 16)), cv2.COLOR_BGR2GRAY)
    bits = (gray > gray.mean()).flatten()
    return int(sum(int(bit) << i for i, bit in enumerate(bits)))


def carousel_image(image: np.ndarray, carousel, *, scale=3) -> np.ndarray:
    x, y, w, h = carousel
    crop = image[y:y + h, x:x + w]
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def analyze_panel(image: np.ndarray, recognize) -> PanelVision:
    """單帧完整分析；AI 只需要處理回傳的 crop（可能為 None）。"""
    h, w = image.shape[:2]
    inbox = find_input_box(image)
    confirm = find_confirm(image, inbox)
    carousel = find_carousel(image, inbox)
    index = crop = None
    if carousel is not None:
        index = carousel_index(image, carousel, recognize)
        crop = carousel_image(image, carousel)
    return PanelVision(
        index=index,
        input_box=_norm(inbox, w, h) if inbox else None,
        confirm_box=_norm(confirm, w, h) if confirm else None,
        crop=crop,
    )
