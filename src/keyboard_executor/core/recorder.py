"""錄製引擎：把 InputHook 的事件流轉為 Action 序列（純邏輯，不碰平台 API）。

演算法（spec §6）：
- 修飾鍵（ctrl/shift/alt/cmd）按住時按下的一般鍵 → key_combo；否則 key_press
- 相鄰輸出動作的觸發事件時間差 >= 50ms → 先插入 delay
- 滑鼠 down/up 位移（Chebyshev）<= 5px → mouse_click，否則 mouse_drag
- 滑鼠 move 在 simplified 模式丟棄、full 模式以 100ms 取樣（第一個保留）
- 座標一律轉為視窗相對座標（origin = 錄製當下的視窗左上角）
- 控制熱鍵（F9/F10）由呼叫端以 SessionGuard.is_control_event 過濾，不會進到 feed
- 產出的 Action params 形狀與 action_from_dict 正規化結果一致，存檔後可原樣載回
"""
from __future__ import annotations

from keyboard_executor.core.geometry import Point, to_relative
from keyboard_executor.core.models import Action, ActionType
from keyboard_executor.platforms.base import EventKind, InputEvent

# 修飾鍵 canonical 名稱與 combo 內的固定順序（key_to_name 已把左右變體/別名正規化）
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "cmd")
_MODIFIERS = frozenset(_MODIFIER_ORDER)

_MIN_DELAY_MS = 50  # 相鄰輸出動作間隔 >= 此值才插入 delay
_CLICK_TOLERANCE_PX = 5  # down/up Chebyshev 位移 <= 此值視為點擊
_MOVE_SAMPLE_MS = 100    # full 模式 mouse_move 取樣間隔


class Recorder:
    """mode: "simplified"（預設，丟棄滑鼠移動軌跡）或 "full"（取樣保留 mouse_move）。

    非執行緒安全，呼叫端需序列化 feed()。
    """

    def __init__(self, origin: Point, mode: str = "simplified"):
        if mode not in ("simplified", "full"):
            raise ValueError(f"未知的錄製模式: {mode!r}")
        self._origin = origin
        self._mode = mode
        self._actions: list[Action] = []
        self._held: set[str] = set()
        self._last_output_ts: int | None = None
        self._pending_down: tuple | None = None  # (button, x, y, ts)，拖曳/點擊配對用
        self._last_move_ts: int | None = None    # full 模式最後保留的 move 時間

    def feed(self, event: InputEvent) -> None:
        if event.kind is EventKind.KEY_DOWN:
            self._on_key_down(event)
        elif event.kind is EventKind.KEY_UP:
            self._held.discard(event.key)
        elif event.kind is EventKind.MOUSE_DOWN:
            self._on_mouse_down(event)
        elif event.kind is EventKind.MOUSE_UP:
            self._on_mouse_up(event)
        elif event.kind is EventKind.MOUSE_MOVE:
            self._on_mouse_move(event)
        elif event.kind is EventKind.SCROLL:
            self._on_scroll(event)

    def finish(self) -> list[Action]:
        return list(self._actions)

    # -- 鍵盤 --

    def _on_key_down(self, event: InputEvent) -> None:
        key = event.key
        if key in _MODIFIERS:
            self._held.add(key)
            return
        if self._held:
            keys = [m for m in _MODIFIER_ORDER if m in self._held] + [key]
            self._output(Action(type=ActionType.KEY_COMBO, params={"keys": keys, "hold_ms": 0}),
                         event.timestamp_ms)
        else:
            self._output(Action(type=ActionType.KEY_PRESS,
                                params={"key": key, "hold_ms": 0}),
                         event.timestamp_ms)

    # -- 滑鼠 --

    def _on_mouse_down(self, event: InputEvent) -> None:
        if self._pending_down is not None:
            return  # 已有按鍵按住（拖曳中）：忽略其他按鍵的 down（不支援多鍵拖曳）
        self._pending_down = (event.button, event.x, event.y, event.timestamp_ms)

    def _on_mouse_up(self, event: InputEvent) -> None:
        if self._pending_down is None or event.button != self._pending_down[0]:
            return
        button, down_x, down_y, _down_ts = self._pending_down
        self._pending_down = None
        rel_down = to_relative(self._origin, Point(down_x, down_y))
        moved = max(abs(event.x - down_x), abs(event.y - down_y))  # Chebyshev 位移
        if moved <= _CLICK_TOLERANCE_PX:
            self._output(Action(type=ActionType.MOUSE_CLICK,
                                params={"x": rel_down.x, "y": rel_down.y,
                                        "button": str(button), "count": 1}),
                         event.timestamp_ms)
        else:
            rel_up = to_relative(self._origin, Point(event.x, event.y))
            self._output(Action(type=ActionType.MOUSE_DRAG,
                                params={"from": [rel_down.x, rel_down.y],
                                        "to": [rel_up.x, rel_up.y],
                                        "button": str(button)}),
                         event.timestamp_ms)

    def _on_mouse_move(self, event: InputEvent) -> None:
        if self._pending_down is not None:
            return  # 拖曳進行中：drag 已含起迄，不記錄中途移動
        if self._mode != "full":
            return  # simplified：丟棄移動軌跡
        if (self._last_move_ts is not None
                and event.timestamp_ms - self._last_move_ts < _MOVE_SAMPLE_MS):
            return
        rel = to_relative(self._origin, Point(event.x, event.y))
        self._output(Action(type=ActionType.MOUSE_MOVE, params={"x": rel.x, "y": rel.y}),
                     event.timestamp_ms)
        self._last_move_ts = event.timestamp_ms

    def _on_scroll(self, event: InputEvent) -> None:
        rel = to_relative(self._origin, Point(event.x, event.y))
        self._output(Action(type=ActionType.SCROLL,
                            params={"x": rel.x, "y": rel.y,
                                    "dx": event.dx, "dy": event.dy}),
                     event.timestamp_ms)

    # -- 共用輸出（含 delay 插入） --

    def _output(self, action: Action, timestamp_ms: int) -> None:
        if self._last_output_ts is not None:
            dt = timestamp_ms - self._last_output_ts
            if dt >= _MIN_DELAY_MS:
                self._actions.append(Action(type=ActionType.DELAY, params={"ms": dt}))
        self._actions.append(action)
        self._last_output_ts = timestamp_ms
