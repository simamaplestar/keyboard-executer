"""組裝送給 AI 的示範／修正訊息（內部多模態格式，見 core/ai/messages.py）。

每個函式回傳 (user message, frame_id→sent_scale, frame_id→送出尺寸)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from keyboard_executor.core.ai_demo.frames import (
    MAX_SENT_EDGE, Frame, frame_attachment, select_keyframes,
)
from keyboard_executor.core.ai_demo.outcome import RunOutcome
from keyboard_executor.core.ai_demo.timeline import KeyHold, MouseAct, format_timeline

MAX_EVENT_LOG_CHARS = 4000
_ATTACHMENT_KEYS = ("name", "media_type", "data", "path")


@dataclass
class DemoRecording:
    frames: list[Frame]
    holds: list[KeyHold]
    mouse: list[MouseAct]
    event_times_ms: list[int]
    duration_ms: int
    start_dot: tuple[float, float]
    minimap_region: tuple[int, int, int, int]
    window_title: str
    goal_text: str
    capture_scale: float = 1.0       # 截圖實體像素 / 視窗座標


Images = tuple[list[dict], list[str], dict[str, float], dict[str, tuple[int, int]]]


def _xy(dot) -> str:
    return "(?)" if dot is None else f"({dot[0]:.0f}, {dot[1]:.0f})"


def _attach(picked: list[Frame], capture_scale: float, out_dir: Path,
            max_edge: int = MAX_SENT_EDGE) -> Images:
    images, lines, scales, sizes = [], [], {}, {}
    for frame in picked:
        att = frame_attachment(frame, out_dir, max_edge)
        images.append({k: att[k] for k in _ATTACHMENT_KEYS})
        scales[frame.id] = att["sent_scale"]
        sizes[frame.id] = att["sent_size"]
        w, h = att["sent_size"]
        ratio = att["sent_scale"] / (capture_scale or 1.0)
        lines.append(f"[{frame.id}] t={frame.t_ms / 1000:.1f}s 送出尺寸 {w}×{h}，"
                     f"圖上 1px = {ratio:.2f} 視窗座標，黃點 {_xy(frame.dot)}")
    return images, lines, scales, sizes


def _header(rec: DemoRecording) -> list[str]:
    lines = [f"目標視窗標題：{rec.window_title}",
             f"示範長度：{rec.duration_ms / 1000:.1f} 秒",
             f"小地圖範圍（視窗座標 x, y, w, h）：{list(rec.minimap_region)}",
             f"起點黃點：{_xy(rec.start_dot)}"]
    if rec.goal_text.strip():
        lines.append(f"使用者說明的目的：{rec.goal_text.strip()}")
    return lines


def _timeline(rec: DemoRecording) -> str:
    return format_timeline(rec.holds, rec.mouse,
                           [(f.t_ms, f.dot) for f in rec.frames],
                           [(f.t_ms, f.id) for f in rec.frames]) or "（沒有按鍵或滑鼠事件）"


def initial_message(rec: DemoRecording, limit: int, out_dir: Path,
                    max_edge: int = MAX_SENT_EDGE):
    picked = select_keyframes(rec.frames, rec.event_times_ms, limit)
    images, frame_lines, scales, sizes = _attach(picked, rec.capture_scale, out_dir, max_edge)
    text = "\n".join([
        "這是我的練功示範，請產生練功腳本與回起點腳本。",
        *_header(rec), "", "# 時間軸", _timeline(rec), "", "# 截圖", *frame_lines])
    return {"role": "user", "content": text, "images": images}, scales, sizes


def _event_log(events: list[dict]) -> str:
    parts = []
    steps: list[str] = []
    for e in events:
        kind = e.get("kind")
        if kind == "step":
            steps.append(str(e.get("index")))
            continue
        if steps:
            parts.append("步驟 " + " ".join(steps))
            steps = []
        if kind == "wait_result":
            state = (f"命中 {e.get('elapsed_ms')}ms" if e.get("matched")
                     else f"逾時（{e.get('on_timeout')}）")
            parts.append(f"等待 #{e.get('index')} {e.get('type')} {state}")
        elif kind == "branch":
            parts.append(f"判斷 #{e.get('index')} {e.get('type')} 走 {e.get('taken')}")
        elif kind == "timed_key":
            parts.append(f"定時技能 {e.get('key')}")
    if steps:
        parts.append("步驟 " + " ".join(steps))
    text = "\n".join(parts) or "（沒有執行紀錄）"
    if len(text) > MAX_EVENT_LOG_CHARS:
        half = MAX_EVENT_LOG_CHARS // 2
        text = text[:half] + "\n…（中略）…\n" + text[-half:]
    return text


def fix_message(rec: DemoRecording, run: RunOutcome, previous_script: dict,
                limit: int, out_dir: Path, max_edge: int = MAX_SENT_EDGE):
    demo_quota = max(2, limit // 2)
    run_quota = max(2, limit - demo_quota)
    demo = select_keyframes(rec.frames, rec.event_times_ms, demo_quota)
    tried = select_keyframes(run.frames, [], run_quota)
    images, frame_lines, scales, sizes = _attach(demo + tried, rec.capture_scale, out_dir,
                                                 max_edge)
    ended = run.ended + (f"：{run.reason}" if run.reason else "")
    text = "\n".join([
        "這是上一版腳本的試跑結果，請和示範比對後判定 success 或 needs_fix。",
        *_header(rec), f"本輪結束方式：{ended}", "", "# 示範時間軸", _timeline(rec), "",
        "# 本輪執行紀錄（步驟為該層動作序號）", _event_log(run.events), "",
        "# 上一版主腳本", "```json",
        json.dumps(previous_script, ensure_ascii=False, indent=2), "```", "",
        "# 截圖（D 開頭是示範，R 開頭是本輪試跑）", *frame_lines])
    return {"role": "user", "content": text, "images": images}, scales, sizes


def return_fix_message(rec: DemoRecording, return_script: dict, end_dot,
                       dot_trace: list, out_dir: Path, max_edge: int = MAX_SENT_EDGE):
    picked = rec.frames[:1]
    images, frame_lines, scales, sizes = _attach(picked, rec.capture_scale, out_dir, max_edge)
    trace = " → ".join(_xy(dot) for _, dot in dot_trace[-30:]) or "（沒有讀到黃點）"
    text = "\n".join([
        "回起點腳本跑完後，角色沒有回到起點附近，請修正 return_script。",
        *_header(rec), f"實際停下的黃點：{_xy(end_dot)}", f"黃點軌跡：{trace}", "",
        "# 目前的回起點腳本", "```json",
        json.dumps(return_script, ensure_ascii=False, indent=2), "```", "",
        "# 起點截圖", *frame_lines])
    return {"role": "user", "content": text, "images": images}, scales, sizes
