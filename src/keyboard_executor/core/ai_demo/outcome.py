"""一次試跑（主腳本或回起點腳本）的結果。"""
from __future__ import annotations

from dataclasses import dataclass, field

from keyboard_executor.core.ai_demo.frames import Frame


@dataclass
class RunOutcome:
    ended: str   # "time_up" | "finished" | "aborted" | "stopped" | "interrupted"
    reason: str = ""
    frames: list[Frame] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    dot_trace: list = field(default_factory=list)   # [(t_ms, (x, y) | None), ...]
