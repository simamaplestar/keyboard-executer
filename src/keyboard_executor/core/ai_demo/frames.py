"""示範／試跑截圖：關鍵幀挑選與 AI 圖片附件。

挑選規則（spec §7.1）：必選首尾；每個事件取前後最近的一張；再加入與上一張候選
差異明顯的畫面。超過上限時保留首尾，其餘依「與前一張的差異量」取前幾名。
"""
from __future__ import annotations

import base64
import bisect
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DIFF_THRESHOLD = 12.0
THUMB_SIZE = (64, 36)      # (w, h)
MAX_SENT_EDGE = 1280
_JPEG_QUALITY = 85


@dataclass
class Frame:
    id: str                              # "D1".. 示範；"R{輪}-{n}" 試跑
    t_ms: int
    path: Path                           # 原尺寸 PNG
    size: tuple[int, int]                # 原尺寸 (w, h)，實體像素
    dot: tuple[float, float] | None
    thumb: np.ndarray                    # 64×36 灰階，只存在記憶體


def make_thumb(image: np.ndarray) -> np.ndarray:
    gray = image if image.ndim == 2 else cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, THUMB_SIZE, interpolation=cv2.INTER_AREA)


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(cv2.absdiff(a, b)))


def select_keyframes(frames: list[Frame], event_times_ms: list[int], limit: int) -> list[Frame]:
    if not frames:
        return []
    limit = max(2, limit)
    n = len(frames)
    times = [f.t_ms for f in frames]
    mandatory = {0, n - 1}
    candidates: set[int] = set()
    for t in event_times_ms:
        before = bisect.bisect_right(times, t) - 1
        if before >= 0:
            candidates.add(before)
        if before + 1 < n:
            candidates.add(before + 1)
    ref = frames[0].thumb
    for i in range(1, n):
        if _diff(frames[i].thumb, ref) > DIFF_THRESHOLD:
            candidates.add(i)
            ref = frames[i].thumb
    candidates -= mandatory
    room = limit - len(mandatory)
    if len(candidates) > room:
        score = {i: _diff(frames[i].thumb, frames[i - 1].thumb) for i in candidates}
        candidates = set(sorted(candidates, key=lambda i: (-score[i], i))[:max(0, room)])
    return [frames[i] for i in sorted(mandatory | candidates)]


def read_image(path: Path) -> np.ndarray | None:
    """支援非 ASCII 路徑（cv2.imread 在 Windows 讀不到中文路徑）。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def write_png(path: Path, image: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"無法編碼截圖：{path.name}")
    buf.tofile(str(path))


def frame_attachment(frame: Frame, out_dir: Path, max_edge: int = MAX_SENT_EDGE) -> dict:
    """縮到長邊 max_edge 內的 JPEG 附件（messages.py 內部格式），另附
    sent_scale（原寬/送出寬）與 sent_size，供模板裁切換算回原圖座標。"""
    image = read_image(frame.path)
    if image is None:
        raise OSError(f"讀不到截圖：{frame.path.name}")
    h, w = image.shape[:2]
    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        image = cv2.resize(image, (round(w * ratio), round(h * ratio)),
                           interpolation=cv2.INTER_AREA)
    sh, sw = image.shape[:2]
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    if not ok:
        raise OSError(f"無法編碼截圖：{frame.id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{frame.id}.jpg"
    buf.tofile(str(path))
    return {"name": f"{frame.id}.jpg", "media_type": "image/jpeg",
            "data": base64.b64encode(buf.tobytes()).decode("ascii"),
            "path": str(path), "sent_scale": w / sw, "sent_size": (sw, sh)}
