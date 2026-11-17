import base64
from pathlib import Path

import cv2
import numpy as np

from keyboard_executor.core.ai_demo.frames import (
    Frame, frame_attachment, make_thumb, select_keyframes,
)


def solid(value, w=64, h=36):
    return np.full((h, w, 3), value, dtype=np.uint8)


def make_frames(values, step_ms=500):
    return [Frame(id=f"D{i + 1}", t_ms=i * step_ms, path=Path(f"D{i + 1}.png"),
                  size=(64, 36), dot=None, thumb=make_thumb(solid(v)))
            for i, v in enumerate(values)]


def ids(frames):
    return [f.id for f in frames]


def test_make_thumb_shape():
    thumb = make_thumb(solid(10, 1280, 720))
    assert thumb.shape == (36, 64)
    assert thumb.ndim == 2


def test_always_keeps_first_and_last():
    frames = make_frames([0] * 10)
    picked = select_keyframes(frames, [], limit=30)
    assert ids(picked) == ["D1", "D10"]


def test_static_screen_without_events_only_first_last():
    frames = make_frames([50] * 40)
    assert ids(select_keyframes(frames, [], limit=30)) == ["D1", "D40"]


def test_event_neighbours_selected():
    frames = make_frames([0] * 10)
    picked = select_keyframes(frames, [1200], limit=30)   # D3(1000) 前、D4(1500) 後
    assert ids(picked) == ["D1", "D3", "D4", "D10"]


def test_changed_frames_selected():
    frames = make_frames([0, 0, 0, 200, 200, 200])
    assert "D4" in ids(select_keyframes(frames, [], limit=30))


def test_respects_limit_and_time_order():
    values = [(i * 37) % 256 for i in range(100)]
    frames = make_frames(values)
    picked = select_keyframes(frames, list(range(0, 50_000, 700)), limit=30)
    assert len(picked) == 30
    assert picked[0].id == "D1" and picked[-1].id == "D100"
    assert [f.t_ms for f in picked] == sorted(f.t_ms for f in picked)


def test_single_frame():
    frames = make_frames([0])
    assert ids(select_keyframes(frames, [0, 10], limit=30)) == ["D1"]


def test_empty_frames():
    assert select_keyframes([], [100], limit=30) == []


def test_limit_below_two_treated_as_two():
    frames = make_frames([0, 100, 200, 0])
    assert ids(select_keyframes(frames, [], limit=1)) == ["D1", "D4"]


def test_attachment_downscales_to_1280(tmp_path):
    src = tmp_path / "D1.png"
    cv2.imwrite(str(src), solid(80, 2560, 1440))
    frame = Frame(id="D1", t_ms=0, path=src, size=(2560, 1440), dot=None,
                  thumb=make_thumb(solid(80)))
    att = frame_attachment(frame, tmp_path / "sent")
    assert att["media_type"] == "image/jpeg"
    assert att["sent_scale"] == 2.0
    assert att["sent_size"] == (1280, 720)
    assert Path(att["path"]).is_file()
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(att["data"]), np.uint8),
                           cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (720, 1280)


def test_attachment_small_image_not_upscaled(tmp_path):
    src = tmp_path / "D1.png"
    cv2.imwrite(str(src), solid(80, 800, 600))
    frame = Frame(id="D1", t_ms=0, path=src, size=(800, 600), dot=None,
                  thumb=make_thumb(solid(80)))
    att = frame_attachment(frame, tmp_path / "sent")
    assert att["sent_scale"] == 1.0
    assert att["sent_size"] == (800, 600)
