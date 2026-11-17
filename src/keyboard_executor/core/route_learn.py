"""小地圖路線學習（純計算，不碰輸入與畫面）。

錄製時同時記下「按了哪些鍵」與「小地圖黃點位置」，錄完整理成步驟：
- 走路：按住左/右且黃點水平移動 → 走到終點；期間一直按住的鍵（如攻擊 C）
  成為 hold_keys，反覆點按的鍵成為 path_key。
- 爬繩：按住上/下、黃點垂直移動 → 對齊繩子 X 再爬到終點高度。
- 下跳：按住下再按跳躍、高度變低 → 下跳到落地高度。
- 跳躍：按住左/右時按跳躍 → 在起跳點用同方向＋跳躍，按住到落地。
- 傳點：按上後黃點瞬間跳到別處 → 走到傳點、按上、確認已傳送。
- 原地按鍵：其餘按鍵（T、buff、喝水…）記下位置與按住時間照按。

回放看位置不看時間：每一步都先回到錄製時的位置再按鍵。
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace

DIRECTIONS = ("left", "right", "up", "down")

_LAG = .2               # 輸入到黃點開始反應的延遲（秒）
_MOVE_MIN = 3.0         # 水平移動少於這麼多格視為原地點按
_CLIMB_MIN = 4.0        # 垂直移動至少這麼多格才算爬繩/下跳
_TELEPORT = 10.0        # 相鄰兩次讀數距離這麼大視為傳送
_TELEPORT_DT = .35
_SETTLE = .2            # 連續這麼久不動才算停穩
_STILL = 1.0            # 黃點會在相鄰兩格之間閃動，差 1 格內都算沒動
_HOLD_RATIO = .6        # 走路期間按住比例超過這個值視為全程按住
_MERGE_GAP = .4         # 同位置連續點按同一鍵、間隔小於此值合併成按住
_IDLE_DELAY = .8        # 兩步之間空閒超過這麼久才補延遲
_JUMP_MAX = 1.0         # 方向跳最多按住多久（秒）
_ABSORB = .3            # 按鍵有這個比例的時間是在走路中按住 → 算走路的一部分
_DASH_MIN = 10.0        # 沒按方向鍵、只按住某鍵時水平移動這麼多＝衝刺型攻擊
_DASH_TOL = 6


@dataclass(frozen=True)
class KeyEvent:
    t: float            # 秒（與 DotSample 同一個時鐘）
    key: str
    down: bool


@dataclass(frozen=True)
class DotSample:
    t: float
    x: float
    y: float


@dataclass
class RouteStep:
    kind: str                       # walk / rope / down_jump / jump / portal / press / dash
    t0: float
    t1: float
    start: tuple[float, float]
    end: tuple[float, float]
    keys: tuple[str, ...] = ()      # press/jump：要按的鍵
    hold_ms: int = 0
    hold_keys: tuple[str, ...] = ()
    path_key: str | None = None
    path_step: int = 5
    idle_before: float = 0.0        # 與上一步之間的空閒秒數（等怪重生等）
    before: tuple = ()              # portal：站上傳點後、按上之前要按的鍵 ((keys, hold_ms)…)


@dataclass
class _Interval:
    key: str
    t0: float
    t1: float
    used: bool = False
    absorbed: bool = False

    @property
    def length(self):
        return max(0.0, self.t1 - self.t0)


@dataclass
class _Track:
    samples: list[DotSample]
    times: list[float] = field(init=False)

    def __post_init__(self):
        self.samples = sorted(self.samples, key=lambda s: s.t)
        self.times = [s.t for s in self.samples]

    def at(self, t: float) -> tuple[float, float]:
        """t 當下（或之前最後一次）的位置。"""
        i = bisect.bisect_right(self.times, t) - 1
        s = self.samples[max(0, i)]
        return (s.x, s.y)

    def window(self, t0: float, t1: float) -> list[DotSample]:
        a = bisect.bisect_left(self.times, t0)
        b = bisect.bisect_right(self.times, t1)
        return self.samples[a:b]

    def settled(self, t: float, limit: float = 2.0, *, y_only=False) -> tuple[float, tuple]:
        """t 之後第一次停穩的時間與位置；limit 內都沒停穩就回 t+limit 的位置。"""
        window = self.window(t, t + limit)
        anchor, prev = None, None
        for s in window:
            if (prev is not None and s.t - prev.t <= _TELEPORT_DT
                    and max(abs(s.x - prev.x), abs(s.y - prev.y)) >= _TELEPORT):
                # 之後被傳送走了：停在傳送前最後的位置，不算到傳送後的地方。
                return prev.t, (prev.x, prev.y)
            prev = s
            if anchor is not None and abs(s.y - anchor.y) <= _STILL and (
                    y_only or abs(s.x - anchor.x) <= _STILL):
                if s.t - anchor.t >= _SETTLE:
                    return anchor.t, (anchor.x, anchor.y)
            else:
                anchor = s
        end = t + limit
        return end, self.at(end)

    def teleport(self, t0: float, t1: float):
        """t0~t1 內黃點瞬間跳動的位置：回傳 (跳之前讀數, 跳之後讀數) 或 None。"""
        window = self.window(t0, t1)
        for a, b in zip(window, window[1:]):
            if (b.t - a.t <= _TELEPORT_DT
                    and max(abs(b.x - a.x), abs(b.y - a.y)) >= _TELEPORT):
                return a, b
        return None


def _intervals(events: list[KeyEvent], end_time: float) -> list[_Interval]:
    """down/up 配對成按住區間；按住重複觸發的 down 不另算；沒放開的收在結尾。"""
    open_at: dict[str, tuple[float, int]] = {}
    result = []
    for order, e in enumerate(sorted(events, key=lambda e: e.t)):
        if e.down:
            open_at.setdefault(e.key, (e.t, order))
        elif e.key in open_at:
            t0, seq = open_at.pop(e.key)
            result.append((seq, _Interval(e.key, t0, e.t)))
    for key, (t0, seq) in open_at.items():
        result.append((seq, _Interval(key, t0, end_time)))
    # 依按下的先後排序（同一時間按下的組合鍵保留原本順序，如 ctrl+1）。
    return [iv for _, iv in sorted(result, key=lambda r: (r[1].t0, r[0]))]


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _subtract(t0, t1, ranges):
    """[t0, t1] 扣掉 ranges 之後剩下的區段。"""
    pieces = [(t0, t1)]
    for r0, r1 in sorted(ranges):
        nxt = []
        for p0, p1 in pieces:
            if r1 <= p0 or r0 >= p1:
                nxt.append((p0, p1))
                continue
            if r0 > p0:
                nxt.append((p0, r0))
            if r1 < p1:
                nxt.append((r1, p1))
        pieces = nxt
    return [(a, b) for a, b in pieces if b - a > .05]


def learn_route(events: list[KeyEvent], samples: list[DotSample], *,
                jump_key: str = "space") -> list[RouteStep]:
    """錄到的按鍵＋黃點軌跡 → 依時間排序的步驟。"""
    if not samples:
        raise ValueError("錄製期間沒有讀到小地圖黃點，請確認小地圖範圍")
    track = _Track(list(samples))
    end_time = max([track.times[-1]] + [e.t for e in events])
    intervals = _intervals(events, end_time)
    by_key: dict[str, list[_Interval]] = {}
    for iv in intervals:
        by_key.setdefault(iv.key, []).append(iv)
    steps: list[RouteStep] = []
    busy: list[tuple[float, float]] = []     # 已被爬繩/跳躍/傳點佔用的時間

    def add(step):
        steps.append(step)
        busy.append((step.t0, step.t1))

    # 1) 跳躍鍵：下跳、方向跳、原地跳。按住同一個方向連跳兩次以上＝邊走邊跳，
    #    交給走路（沿路按跳躍），不拆成一次次「走到起跳點再跳」。
    chain: list[_Interval] = []
    for side in [iv for d in ("left", "right") for iv in by_key.get(d, [])]:
        inside = [j for j in by_key.get(jump_key, [])
                  if side.t0 <= j.t0 <= side.t1
                  and not any(d.t0 <= j.t0 <= d.t1 + .05 for d in by_key.get("down", []))
                  and not any(u.t0 <= j.t0 <= u.t1 for u in by_key.get("up", []))]
        if len(inside) >= 2:
            for j in inside:
                j.used = True
            chain.extend(inside)
    for jump in by_key.get(jump_key, []):
        if jump.used:
            continue
        before = track.at(jump.t0)
        downs = [iv for iv in by_key.get("down", []) if iv.t0 <= jump.t0 <= iv.t1 + .05]
        if downs:
            t_land, landed = track.settled(jump.t0 + _LAG, 3.0, y_only=True)
            jump.used = True
            for d in downs:
                d.used = True
            if landed[1] - before[1] >= _CLIMB_MIN:
                add(RouteStep("down_jump", jump.t0, t_land, before, landed))
            continue
        if any(iv.t0 <= jump.t0 <= iv.t1 for iv in by_key.get("up", [])):
            continue        # 按住上時跳一下＝抓繩，交給爬繩處理
        sides = [iv for d in ("left", "right") for iv in by_key.get(d, [])
                 if iv.t0 <= jump.t0 <= iv.t1]
        t_land, landed = track.settled(jump.t0 + _LAG + .1, _JUMP_MAX, y_only=True)
        jump.used = True
        if sides:
            side = max(sides, key=lambda iv: iv.t0)
            # 按住方向到落地；斜坡上一直沒停穩時最多按 _JUMP_MAX 秒。
            hold = int(round(min(_JUMP_MAX, max(.3, t_land - jump.t0)) * 1000, -1))
            add(RouteStep("jump", jump.t0, t_land, before, landed,
                          keys=(side.key, jump_key), hold_ms=hold))
        else:
            add(RouteStep("press", jump.t0, jump.t1, before, before, keys=(jump_key,),
                          hold_ms=_hold_ms(jump.length)))

    # 2) 上：傳點或爬繩；下（沒有跳）：往下爬。
    for key in ("up", "down"):
        for iv in by_key.get(key, []):
            if iv.used:
                continue
            start = track.at(iv.t0)
            # 小地圖顯示比按鍵早一點變也有可能：往前多看 0.3 秒，取第一次瞬移。
            hop = track.teleport(iv.t0 - .3, iv.t1 + 1.0) if key == "up" else None
            if hop is not None:
                t_end, end = track.settled(hop[1].t, 2.0)
                iv.used = True
                add(RouteStep("portal", iv.t0, t_end, (hop[0].x, hop[0].y), end,
                              hold_ms=_hold_ms(iv.length)))
                continue
            t_end, end = track.settled(iv.t1 + _LAG, 2.0, y_only=True)
            moved = end[1] - start[1]
            if (key == "up" and moved <= -_CLIMB_MIN) or (key == "down" and moved >= _CLIMB_MIN):
                iv.used = True
                rope_x = _rope_x(track, iv.t0, t_end, start)
                add(RouteStep("rope", iv.t0, t_end, (rope_x, start[1]), (rope_x, end[1])))

    # 3) 左右：扣掉上面已佔用的時間後，剩下的是走路或原地點按。
    pieces = []
    for key in ("left", "right"):
        for iv in by_key.get(key, []):
            for p0, p1 in _subtract(iv.t0, iv.t1, busy):
                pieces.append((p0, p1, key, p1 >= iv.t1 - 1e-6, p0 <= iv.t0 + 1e-6))
            iv.used = True
    pieces.sort()

    others = [iv for iv in intervals if iv.key not in DIRECTIONS and iv.key != jump_key]
    walk_info = []
    # 走路時一直按著的鍵（例如邊走邊按住 C）：大部分時間是在走路中按住就算走路的一部分，
    # 不再另外變成「回到某處原地按 C 幾秒」。
    for iv in others:
        moving = sum(_overlap(p[0], p[1], iv.t0, iv.t1) for p in pieces)
        if iv.length >= .3 and moving >= iv.length * _ABSORB:
            iv.absorbed = True
    for p0, p1, key, released, fresh in pieces:
        hold, taps = [], {}
        duration = p1 - p0
        for k in sorted({iv.key for iv in others}):
            ivs = [iv for iv in by_key[k] if not iv.used or iv.absorbed]
            covered = sum(_overlap(p0, p1, iv.t0, iv.t1) for iv in ivs)
            inside = [iv for iv in ivs if iv.t0 >= p0 - .05 and iv.t1 <= p1 + .05]
            if duration >= .2 and covered >= duration * _HOLD_RATIO:
                hold.append(k)
            elif len(inside) >= 2:
                taps[k] = inside
        path_key, path_taps = None, []
        jumps = [j for j in chain if p0 - .05 <= j.t0 <= p1 + .05]
        if jumps:
            path_key, path_taps = jump_key, jumps
            for ivs in taps.values():
                for iv in ivs:
                    iv.used = True
        elif taps:
            path_key, path_taps = max(taps.items(), key=lambda kv: len(kv[1]))
            for iv in path_taps:
                iv.used = True
        walk_info.append((p0, p1, key, released, fresh, tuple(hold), path_key, path_taps))
    for iv in others:
        if iv.absorbed:
            iv.used = True

    # 4) 其餘按鍵：原地按（同位置連按同一鍵合併成按住）。
    presses = _presses([iv for iv in others if not iv.used], track)
    press_times = [p.t0 for p in presses]

    long_holds = [iv for iv in others if not iv.used and iv.length >= 1.0]
    for p0, p1, key, released, fresh, hold, path_key, path_taps in walk_info:
        moved = track.at(p1 + _LAG)[0] - track.at(p0)[0]
        facing = (p1 - p0 < .6 and not hold and released and fresh and (
            (key == "left" and moved > 0) or (key == "right" and moved < 0)
            or any(p0 - .1 <= iv.t0 <= p1 + .15 and iv.t1 > p1 + .5 for iv in long_holds)))
        if facing:
            # 衝刺技能前點一下方向鍵轉身：只是按鍵，移動算在後面的衝刺。
            pos = track.at(p0)
            steps.append(RouteStep("press", p0, p1, pos, pos, keys=(key,),
                                   hold_ms=_hold_ms(p1 - p0)))
            continue
        cuts = [p0] + [t for t in press_times if p0 < t < p1] + [p1]
        for i, (c0, c1) in enumerate(zip(cuts, cuts[1:])):
            last = i == len(cuts) - 2
            start = track.at(c0)
            if last and released:
                t_end, end = track.settled(c1 + _LAG, 2.0)
            else:
                t_end, end = c1, track.at(c1)
            hop = track.teleport(c0, t_end)
            if hop is not None:                 # 走一走被傳送：終點算傳送前
                t_end, end = hop[0].t, (hop[0].x, hop[0].y)
            dx = end[0] - start[0]
            if abs(dx) < _MOVE_MIN:
                # 只有真的按下又放開的點按才算；跳躍/爬繩後剩下的一小段方向鍵不算。
                if released and fresh and len(cuts) == 2:
                    # 原地按方向（例如「往右按一下」，或按住右＋C 原地打怪）。
                    steps.append(RouteStep("press", c0, c1, start, end, keys=(key,) + hold,
                                           hold_ms=_hold_ms(c1 - c0)))
                continue
            path_step = 5
            if path_key is not None:
                count = max(1, sum(1 for iv in path_taps if c0 <= iv.t0 <= c1))
                path_step = int(min(100, max(1, round(abs(dx) / count))))
            steps.append(RouteStep("walk", c0, t_end, start, end, hold_keys=hold,
                                   path_key=path_key, path_step=path_step))
    steps.extend(presses)
    steps.sort(key=lambda s: (s.t0, s.t1))
    steps = _merge_walks(steps)
    _fill_idle(steps)
    return steps


def _hold_ms(seconds: float) -> int:
    return int(max(50, round(seconds * 1000, -1)))


def _rope_x(track, t0, t1, start):
    """繩子 X：高度開始改變前最後一次讀到的 X。"""
    prev = None
    for s in track.window(t0, t1):
        if abs(s.y - start[1]) >= 1:
            return prev.x if prev is not None else s.x
        prev = s
    return start[0]


def _presses(ivs, track) -> list[RouteStep]:
    groups: list[list[_Interval]] = []
    for iv in sorted(ivs, key=lambda i: i.t0):
        if groups and iv.t0 < max(g.t1 for g in groups[-1]) and iv.key not in {
                g.key for g in groups[-1]}:
            groups[-1].append(iv)          # 同時按住的不同鍵 → 組合鍵
            continue
        groups.append([iv])
    merged: list[list[_Interval]] = []
    for g in groups:
        prev = merged[-1] if merged else None
        if (prev is not None and len(g) == 1 and len(prev) >= 1
                and {i.key for i in prev} == {g[0].key}
                and g[0].t0 - max(i.t1 for i in prev) <= _MERGE_GAP
                and _near(track.at(prev[0].t0), track.at(g[0].t0), 2)):
            prev.append(g[0])              # 同位置連按同一鍵 → 按住整段
            continue
        merged.append(g)
    steps = []
    for g in merged:
        t0, t1 = min(i.t0 for i in g), max(i.t1 for i in g)
        keys = tuple(dict.fromkeys(i.key for i in sorted(g, key=lambda i: i.t0)))
        pos = track.at(t0)
        if len(keys) == 1:
            # 只按住一個鍵、人物卻水平移動了 → 衝刺型攻擊（按住 C 一路往前衝）。
            # 終點取放開後一下下的位置：衝刺是一格一格跳，放開時已經停在最後一格；
            # 等停穩的話常會等到下一次轉身衝刺。
            t_end = t1 + .12
            end = track.at(t_end)
            dx, dy = abs(end[0] - pos[0]), abs(end[1] - pos[1])
            if dx >= _DASH_MIN and dy <= max(_CLIMB_MIN + 4, dx * .15):
                steps.append(RouteStep("dash", t0, t_end, pos, end, keys=keys,
                                       hold_ms=_hold_ms(t1 - t0)))
                continue
        steps.append(RouteStep("press", t0, t1, pos, pos, keys=keys, hold_ms=_hold_ms(t1 - t0)))
    return steps


def _near(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _merge_walks(steps):
    result = []
    for s in steps:
        prev = result[-1] if result else None
        if (prev is not None and prev.kind == s.kind == "walk"
                and prev.hold_keys == s.hold_keys and prev.path_key == s.path_key
                and (prev.end[0] - prev.start[0]) * (s.end[0] - s.start[0]) > 0
                and abs(prev.end[1] - s.end[1]) < 2):
            prev.end, prev.t1 = s.end, s.t1
            continue
        result.append(s)
    return result


def _fill_idle(steps):
    last_end = None
    for s in steps:
        if last_end is not None and s.t0 - last_end >= _IDLE_DELAY:
            s.idle_before = s.t0 - last_end
        last_end = s.t1 if last_end is None else max(last_end, s.t1)


# ---------- 步驟 → 腳本動作 ----------

_KEY_LABEL = {"left": "左", "right": "右", "up": "上", "down": "下", "space": "空白鍵"}


def _label(key):
    return _KEY_LABEL.get(key, key.upper() if len(key) == 1 else key)


def _area(points, margin_x=4, margin_y=4):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = int(min(xs) - margin_x), int(min(ys) - margin_y)
    return [x0, y0, int(max(xs) + margin_x) - x0 + 1, int(max(ys) + margin_y) - y0 + 1]


def attach_portal_keys(steps: list[RouteStep]) -> list[RouteStep]:
    """傳點前在同一位置按的鍵（例如下坐騎的 U）併進傳點：要先走到傳點、停穩才按，
    傳送失敗重試時一起重按。"""
    result: list[RouteStep] = []
    for s in steps:
        if s.kind == "portal":
            before = []
            while (result and result[-1].kind == "press"
                   and result[-1].keys[0] not in ("left", "right", "up", "down")
                   and abs(result[-1].start[0] - s.start[0]) <= 8
                   and abs(result[-1].start[1] - s.start[1]) <= 4
                   and s.t0 - result[-1].t1 <= 1.5):
                p = result.pop()
                before.insert(0, (p.keys, max(100, p.hold_ms)))
            if before:
                s = replace(s, before=tuple(before) + tuple(s.before))
        result.append(s)
    return result


class step_actions:
    """把步驟轉成腳本動作（走路、爬繩、下跳、跳、傳點、按鍵），記住每段的位置供走丟時接回。"""

    def __init__(self, region, jump_key="space", *, header=6):
        self.region = list(region)
        self.jump_key = jump_key
        self.base = header
        self.body: list[dict] = []
        self.anchors: list[tuple[list[int], int]] = []
        self.here = None
        self._group = None
        self.face_reverse = None        # 衝刺技能轉身方向（地圖分析學到的）
        self.dash_step = None           # 一次衝刺幾格（地圖分析學到的）
        self._loose = False             # 上一步是提早放開的衝刺：下一步要先走到精確位置

    def index(self) -> int:
        return len(self.body) + self.base

    def _clamp(self, p):
        rx, ry, rw, rh = self.region
        return [int(min(rx + rw - 1, max(rx, round(p[0])))),
                int(min(ry + rh - 1, max(ry, round(p[1]))))]

    def move(self, name, target, method="walk", tolerance=3, **extra) -> dict:
        action = {"type": "minimap_move", "name": name, "region": list(self.region),
                  "target": self._clamp(target), "method": method, "tolerance": tolerance,
                  "jump_key": self.jump_key, "timeout_ms": 15000, "on_timeout": "goto",
                  "goto_index": 0}
        action.update(extra)
        return action

    def walk(self, name, target, tolerance=3, method="walk", **extra) -> None:
        self.body.append(self.move(name, target, method=method, tolerance=tolerance, **extra))
        self.here = target

    def goto_start(self, name) -> None:
        self.body.append({"type": "goto", "name": name, "goto_index": 0})

    def _anchor(self, points):
        index = self._group if self._group is not None else self.index()
        self.anchors.append((_area(points), index))
        self._group = None

    def _align(self, pos, tolerance, name):
        here = self.here
        if (self._loose or here is None or abs(here[0] - pos[0]) > tolerance
                or abs(here[1] - pos[1]) > 4):
            self.walk(name, pos, tolerance=tolerance)
        self._loose = False

    def steps(self, steps: list[RouteStep]) -> None:
        steps = attach_portal_keys(steps)
        for s, nxt in zip(steps, steps[1:] + [None]):
            self.step(s, nxt)

    def step(self, s: RouteStep, nxt: RouteStep | None = None) -> None:
        body = self.body
        if self._group is None:
            self._group = self.index()
        if s.idle_before >= _IDLE_DELAY:
            body.append({"type": "delay", "name": "照錄製時停一下",
                         "ms": int(round(s.idle_before * 1000, -2))})
        if s.kind == "walk":
            extra = {}
            label = f"走到 ({s.end[0]:.0f}, {s.end[1]:.0f})"
            if s.hold_keys:
                extra["hold_keys"] = list(s.hold_keys)
                label += f"，按住 {'+'.join(map(_label, s.hold_keys))}"
            if s.path_key:
                extra.update(path_key=s.path_key, path_step=s.path_step)
                label += f"，沿路按 {_label(s.path_key)}"
            self._anchor([s.start, s.end])
            self.walk(label, s.end, **extra)
        elif s.kind == "dash":
            self._anchor([s.start, s.end])
            side = "右" if s.end[0] > s.start[0] else "左"
            tolerance = _DASH_TOL
            if nxt is not None and nxt.kind not in ("dash", "walk") and self.dash_step:
                # 衝完要在這裡下跳/進傳點/按鍵：小地圖慢半拍會多衝一格（可能衝出平台），
                # 提早放開，下一步再走到精確位置。
                tolerance = int(max(_DASH_TOL, min(40, self.dash_step * .8)))
            body.append(self.move(f"按住 {_label(s.keys[0])} 往{side}衝到 ({s.end[0]:.0f}, "
                                  f"{s.end[1]:.0f})", s.end, method="hold",
                                  tolerance=tolerance, hold_keys=list(s.keys),
                                  **({} if self.face_reverse is None
                                     else {"face_reverse": self.face_reverse})))
            self.here = s.end
            self._loose = tolerance > _DASH_TOL
            return
        elif s.kind == "rope":
            self._anchor([s.start, s.end])
            word = "爬上" if s.end[1] < s.start[1] else "爬下"
            body.append(self.move(f"{word}繩子到 ({s.end[0]:.0f}, {s.end[1]:.0f})", s.end,
                                  method="rope", tolerance=1))
            self.here = s.end
        elif s.kind == "down_jump":
            self._anchor([s.start])
            self._align(s.start, 3, "走到下跳位置")
            body.append(self.move(f"下跳到高度 {s.end[1]:.0f}", s.end, method="down_jump"))
            self.here = s.end
        elif s.kind == "jump":
            self._anchor([s.start])
            self._align(s.start, 2, "走到起跳位置")
            body.append({"type": "key_combo", "name": f"往{_label(s.keys[0])}跳",
                         "keys": list(s.keys), "hold_ms": s.hold_ms})
            self.here = s.end
        elif s.kind == "portal":
            self._anchor([s.start])
            portal_index = self.index()
            body.append(self.move("走到傳點", s.start, tolerance=1))
            # 剛衝刺/走完技能動作還沒結束時按上會被忽略（實機每圈第一次都失敗）。
            body.append({"type": "delay", "name": "停穩再進傳點", "ms": 800})
            for keys, hold_ms in s.before:
                # 錄製時站在傳點上先按的鍵（例如 U）；傳送失敗重來時也會再按一次。
                name = f"按 {'+'.join(map(_label, keys))}"
                if len(keys) == 1:
                    body.append({"type": "key_press", "name": name, "key": keys[0],
                                 "hold_ms": hold_ms})
                else:
                    body.append({"type": "key_combo", "name": name, "keys": list(keys),
                                 "hold_ms": hold_ms})
                body.append({"type": "delay", "name": "等按鍵生效", "ms": 250})
            body.append({"type": "key_press", "name": "進傳點", "key": "up",
                         "hold_ms": max(150, min(s.hold_ms, 400))})
            body.append({"type": "delay", "name": "等傳送", "ms": 600})
            confirm = self.index()
            body.append({"type": "minimap_goto", "name": "確認已傳送", "region": list(self.region),
                         "branches": [{"area": _area([s.end], 30, 6),
                                       "goto_index": confirm + 1}],
                         "otherwise": "goto", "otherwise_index": portal_index})
            self.here = s.end
        else:   # press
            if self.here is not None or self._loose:
                self._align(s.start, 4, "回到按鍵位置")
            keys = list(s.keys)
            name = f"按 {'+'.join(map(_label, keys))}"
            if s.hold_ms >= 300:
                name += f" {s.hold_ms / 1000:g} 秒"
            if len(keys) == 1:
                body.append({"type": "key_press", "name": name, "key": keys[0],
                             "hold_ms": s.hold_ms})
            else:
                body.append({"type": "key_combo", "name": name, "keys": keys,
                             "hold_ms": s.hold_ms})
            if s.keys[0] in ("left", "right") and self.here is not None:
                self.here = s.end
        self._loose = False     # 走路/傳點/下跳等都會停在精確位置

    def finish(self) -> list[dict]:
        self.body.append({"type": "delay", "name": "本圈結束", "ms": 0})
        return self.body

    def header(self, branches: list[dict]) -> list[dict]:
        region, jump_key = self.region, self.jump_key
        head = [
            {"type": "minimap_goto", "name": "看人物在路線哪裡", "region": list(region),
             "branches": branches, "otherwise": "goto", "otherwise_index": 1},
            {"type": "delay", "name": "可能還在空中，等落地", "ms": 400},
            {"type": "minimap_goto", "name": "再看一次", "region": list(region),
             "branches": branches, "otherwise": "continue"},
            {"type": "key_combo", "name": "不在路線上，原地下跳", "keys": ["down", jump_key],
             "hold_ms": 100},
            {"type": "delay", "ms": 500},
            {"type": "goto", "name": "重新判斷位置", "goto_index": 0},
        ]
        assert len(head) == self.base
        return head


def route_actions(steps: list[RouteStep], region: list[int], *, jump_key: str = "space",
                  loop_count: int = 100) -> list[dict]:
    """步驟 → 照錄製重播的腳本動作（一個 loop；走丟時依黃點位置接回最近的步驟）。"""
    if not any(s.kind != "press" for s in steps):
        raise ValueError("沒有學到任何移動，請確認錄製時人物有走動且小地圖範圍正確")
    gen = step_actions(region, jump_key, header=_HEADER)
    gen.steps(steps)
    body = gen.finish()
    branches = [{"area": area, "goto_index": index} for area, index in gen.anchors]
    return [{"type": "loop", "name": "小地圖路線", "count": loop_count,
             "actions": gen.header(branches) + body}]


_HEADER = 6


def summarize(steps: list[RouteStep]) -> str:
    names = {"walk": "走路", "rope": "爬繩", "down_jump": "下跳", "jump": "跳躍",
             "portal": "傳點", "press": "按鍵", "dash": "衝刺"}
    counts = {}
    for s in steps:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    return "、".join(f"{names[k]} {v}" for k, v in counts.items() if k in names)
