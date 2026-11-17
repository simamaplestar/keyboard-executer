from pathlib import Path

import cv2
import numpy as np

from keyboard_executor.core.ai.manual import DEMO_GUIDE, build_demo_system_prompt
from keyboard_executor.core.ai_demo.frames import Frame, make_thumb
from keyboard_executor.core.ai_demo.outcome import RunOutcome
from keyboard_executor.core.ai_demo.prompt import (
    DemoRecording, fix_message, initial_message, return_fix_message,
)
from keyboard_executor.core.ai_demo.timeline import KeyHold


def frames(tmp_path, prefix, count, w=2560, h=1440):
    out = []
    for i in range(count):
        img = np.full((h, w, 3), (i * 53) % 256, dtype=np.uint8)
        path = tmp_path / f"{prefix}{i + 1}.png"
        cv2.imwrite(str(path), img)
        out.append(Frame(id=f"{prefix}{i + 1}", t_ms=i * 500, path=path, size=(w, h),
                         dot=(100.0 + i, 40.0), thumb=make_thumb(img)))
    return out


def recording(tmp_path, count=40):
    return DemoRecording(frames=frames(tmp_path, "D", count),
                         holds=[KeyHold("right", 1200, 3850)], mouse=[],
                         event_times_ms=[1200], duration_ms=count * 500,
                         start_dot=(100.0, 40.0), minimap_region=(10, 20, 200, 100),
                         window_title="MapleStory Worlds", goal_text="左右打怪",
                         capture_scale=1.25)


def test_initial_message_has_images_and_timeline(tmp_path):
    rec = recording(tmp_path)
    message, scales, sizes = initial_message(rec, 30, tmp_path / "sent")
    assert message["role"] == "user"
    assert 2 <= len(message["images"]) <= 30
    text = message["content"]
    assert "左右打怪" in text
    assert "D1" in text
    assert "按住 right" in text
    assert "(10, 20, 200, 100)" in text or "[10, 20, 200, 100]" in text
    assert scales["D1"] == 2.0
    assert sizes["D1"] == (1280, 720)
    # 圖片附件只留 messages.py 認得的欄位
    assert set(message["images"][0]) == {"name", "media_type", "data", "path"}
    # 1px 換算到視窗座標：sent_scale / capture_scale
    assert "1.6" in text


def test_fix_message_splits_quota(tmp_path):
    rec = recording(tmp_path)
    run = RunOutcome(ended="time_up", frames=frames(tmp_path, "R1-", 40),
                     events=[{"kind": "step", "index": 0, "total": 2, "type": "loop",
                              "label": "迴圈"}])
    message, scales, _ = fix_message(rec, run, {"name": "練功", "actions": []}, 30,
                                     tmp_path / "sent")
    names = [img["name"] for img in message["images"]]
    assert len([n for n in names if n.startswith("D")]) <= 15
    assert len([n for n in names if n.startswith("R1-")]) <= 15
    assert "time_up" in message["content"]
    assert "\"name\": \"練功\"" in message["content"]
    assert set(scales) == {n[:-4] for n in names}


def test_fix_message_truncates_long_event_log(tmp_path):
    rec = recording(tmp_path, count=3)
    events = [{"kind": "wait_result", "index": i % 7, "type": "wait_image",
               "matched": False, "elapsed_ms": 5000, "on_timeout": "continue"}
              for i in range(2000)]
    run = RunOutcome(ended="aborted", reason="等待逾時", frames=frames(tmp_path, "R1-", 3),
                     events=events)
    message, _, _ = fix_message(rec, run, {"name": "練功"}, 30, tmp_path / "sent")
    assert "（中略）" in message["content"]
    assert len(message["content"]) < 4000 + 3000
    assert "等待逾時" in message["content"]


def test_return_fix_message_mentions_dots(tmp_path):
    rec = recording(tmp_path, count=3)
    message, scales, sizes = return_fix_message(
        rec, {"name": "回起點"}, (150.0, 60.0), [(0, (150.0, 60.0))], tmp_path / "sent")
    text = message["content"]
    assert "(100, 40)" in text
    assert "(150, 60)" in text
    assert "\"name\": \"回起點\"" in text
    assert message["images"]
    assert "D1" in scales and "D1" in sizes


def test_system_prompt_has_demo_guide_without_no_selection_line():
    prompt = build_demo_system_prompt()
    assert DEMO_GUIDE in prompt
    assert "目前沒有選中的腳本" not in prompt
    assert "propose_demo_scripts" in DEMO_GUIDE
    assert "minimap_move" in DEMO_GUIDE
    assert "loop" in DEMO_GUIDE
