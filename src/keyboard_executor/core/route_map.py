"""小地圖分析：從錄製軌跡找出平台、換層方式與打怪習慣，整理成「每層左右掃」的走法。

- 平台：人物站著（高度穩定）的位置依高度、左右連續分群。
- 打怪平台：錄製時在上面按攻擊鍵的平台；其他平台只是路過。
- 一圈：依打怪平台的到達順序找出重複的循環，重複錄的圈只取一圈。
- 換層：兩個打怪平台之間照錄製的走（爬繩、連跳、傳點…）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from keyboard_executor.core.route_learn import (
    DIRECTIONS, DotSample, KeyEvent, RouteStep, _area, _HEADER, _label, attach_portal_keys,
    step_actions,
)

_STAND_DY = .6          # 前後讀數高度差小於這個值算站著
_FLOOR_GAP = 3.0        # 高度差超過這個值算不同層
_PLATFORM_GAP = 14.0    # 同一層左右斷開超過這個值算不同平台
_MIN_SAMPLES = 6
_BIN = 8.0              # 平台高度取樣間隔（階梯每段至少這麼寬）
_FARM_SEC = .8          # 在平台上按攻擊鍵累積超過這麼久算打怪平台
_SWEEP_MARGIN = 3


@dataclass
class Platform:
    id: int
    y: float
    x0: float
    x1: float
    dwell: float = 0.0
    attack: float = 0.0
    y0: float | None = None     # 左端高度（階梯/斜坡兩端高度不同）
    y1: float | None = None     # 右端高度
    profile: list = field(default_factory=list)    # [(x, y)…] 實測高度，階梯用

    def __post_init__(self):
        if self.y0 is None:
            self.y0 = self.y
        if self.y1 is None:
            self.y1 = self.y

    @property
    def farm(self) -> bool:
        return self.attack >= _FARM_SEC

    def y_at(self, x: float) -> float:
        pts = self.profile
        if len(pts) >= 2:
            if x <= pts[0][0]:
                return pts[0][1]
            for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                if x <= xb:
                    return ya + (yb - ya) * (x - xa) / max(xb - xa, 1e-6)
            return pts[-1][1]
        if self.x1 - self.x0 < 1:
            return self.y
        k = min(1.0, max(0.0, (x - self.x0) / (self.x1 - self.x0)))
        return self.y0 + (self.y1 - self.y0) * k

    def contains(self, pos, margin=4.0) -> bool:
        return (self.x0 - margin <= pos[0] <= self.x1 + margin
                and abs(pos[1] - self.y_at(pos[0])) <= 4)

    def to_dict(self) -> dict:
        return {"id": self.id, "y": round(self.y), "x0": round(self.x0), "x1": round(self.x1),
                "y_left": round(self.y0), "y_right": round(self.y1),
                "farm": self.farm, "dwell_sec": round(self.dwell, 1)}


@dataclass
class MapModel:
    region: list[int]
    platforms: list[Platform]
    cycle: list[int]                         # 打怪平台的循環順序（平台 id）
    links: dict[tuple[int, int], list[RouteStep]] = field(default_factory=dict)
    attack_key: str | None = None
    attack_hold: bool = True
    attack_step: int = 5
    jump_key: str = "space"
    dash: bool = False               # 攻擊鍵是衝刺技能（按住會一格一格往前衝）
    dash_step: float = 20.0          # 一次衝刺移動幾格
    face_reverse: bool = False       # 轉身要按反方向
    lap: list = field(default_factory=list)     # 衝刺型：錄製中最有代表性的一整圈步驟

    def platform(self, pid) -> Platform:
        return next(p for p in self.platforms if p.id == pid)

    def locate(self, pos):
        hits = [p for p in self.platforms if p.contains(pos)]
        return min(hits, key=lambda p: abs(p.y - pos[1])) if hits else None

    def to_dict(self) -> dict:
        return {
            "region": list(self.region),
            "platforms": [p.to_dict() for p in self.platforms],
            "cycle": list(self.cycle),
            "links": [{"from": a, "to": b, "how": describe_link(steps)}
                      for (a, b), steps in self.links.items()],
            "attack_key": self.attack_key, "attack_hold": self.attack_hold,
            "jump_key": self.jump_key, "dash": self.dash,
            "dash_step": round(self.dash_step), "face_reverse": self.face_reverse,
        }


_BUSY_KINDS = ("jump", "down_jump", "rope", "portal")


def _busy(steps):
    return [(s.t0 - .05, s.t1 + .05) for s in steps if s.kind in _BUSY_KINDS]


def _in(t, ranges):
    return any(r0 <= t <= r1 for r0, r1 in ranges)


def _same_surface(a: DotSample, b: DotSample) -> bool:
    """相鄰兩次讀數是否在同一個平台上：高度變化小（斜坡/階梯允許隨水平距離變大）；
    衝刺一次跳很多格也算。掉落、傳送、跳躍都不算。"""
    dy, dx = abs(b.y - a.y), abs(b.x - a.x)
    return b.t - a.t <= .3 and dy <= min(8.0, 1.0 + .15 * dx)


def _platforms(samples: list[DotSample], busy) -> list[Platform]:
    comps: list[list[DotSample]] = []
    cur: list[DotSample] = []
    for a, b in zip(samples, samples[1:]):
        if not _in(a.t, busy) and not _in(b.t, busy) and _same_surface(a, b):
            if not cur:
                cur = [a]
            cur.append(b)
        elif cur:
            comps.append(cur)
            cur = []
    if cur:
        comps.append(cur)
    plats = [_platform_of(c) for c in comps if len(c) >= _MIN_SAMPLES]
    merged = True
    while merged:                       # 同一個平台不同時間站過的片段合併
        merged = False
        for i, p in enumerate(plats):
            for q in plats[i + 1:]:
                lo, hi = max(p.x0, q.x0) - _PLATFORM_GAP, min(p.x1, q.x1) + _PLATFORM_GAP
                if lo > hi:
                    continue
                a, b = max(p.x0, q.x0), min(p.x1, q.x1)
                probes = [(a + b) / 2] if a > b else [a + (b - a) * k / 4 for k in range(5)]
                if all(abs(p.y_at(x) - q.y_at(x)) <= _FLOOR_GAP for x in probes):
                    plats.remove(q)
                    plats[i] = _union(p, q)
                    merged = True
                    break
            if merged:
                break
    plats.sort(key=lambda p: (p.y, p.x0))       # 由上到下、由左到右編號
    for i, p in enumerate(plats, 1):
        p.id = i
    return plats


def _platform_of(samples) -> Platform:
    xs = [s.x for s in samples]
    x0, x1 = min(xs), max(xs)
    ys = sorted(s.y for s in samples)
    left = sorted(s.y for s in samples if s.x <= x0 + 6)
    right = sorted(s.y for s in samples if s.x >= x1 - 6)
    bins: dict[int, list[float]] = {}
    for s in samples:                       # 每 8 格取高度中位數，階梯也能對上
        bins.setdefault(int(s.x // _BIN), []).append(s.y)
    profile = []
    for b in sorted(bins):
        col = sorted(bins[b])
        xs_b = [s.x for s in samples if int(s.x // _BIN) == b]
        profile.append((sum(xs_b) / len(xs_b), col[len(col) // 2]))
    p = Platform(0, ys[len(ys) // 2], x0, x1, y0=left[len(left) // 2],
                 y1=right[len(right) // 2], profile=profile)
    p._samples = list(samples)
    return p


def _union(p: Platform, q: Platform) -> Platform:
    return _platform_of(p._samples + q._samples)


def _attack_profile(events: list[KeyEvent], steps: list[RouteStep], jump_key: str):
    """最常用的攻擊鍵與用法（按住 or 點按）。"""
    held: dict[str, float] = {}
    open_at: dict[str, float] = {}
    taps: dict[str, int] = {}
    for e in sorted(events, key=lambda e: e.t):
        if e.key in DIRECTIONS or e.key == jump_key:
            continue
        if e.down:
            open_at.setdefault(e.key, e.t)
        elif e.key in open_at:
            length = e.t - open_at.pop(e.key)
            held[e.key] = held.get(e.key, 0) + length
            taps[e.key] = taps.get(e.key, 0) + 1
    if not held:
        return None, True, 5
    key = max(held, key=held.get)
    hold = held[key] / max(1, taps[key]) >= .35
    path_steps = [s.path_step for s in steps if s.kind == "walk" and s.path_key == key]
    return key, hold, (sorted(path_steps)[len(path_steps) // 2] if path_steps else 5)


def _attack_time(platform: Platform, key, events, samples) -> float:
    if key is None:
        return 0.0
    total, open_at = 0.0, None
    track = sorted(samples, key=lambda s: s.t)

    def on(t):
        near = min(track, key=lambda s: abs(s.t - t))
        return platform.contains((near.x, near.y))
    for e in sorted(events, key=lambda e: e.t):
        if e.key != key:
            continue
        if e.down and open_at is None:
            open_at = e.t
        elif not e.down and open_at is not None:
            t, dt = open_at, .1
            while t < e.t:
                if on(t):
                    total += min(dt, e.t - t)
                t += dt
            open_at = None
    return total


def _visits(samples, model_platforms, busy=()):
    """依時間列出 (平台 id, 第一次站上的時間, 最後一次站著的時間)，連續相同的合併。"""
    visits: list[list] = []
    for s in samples:
        if _in(s.t, busy):
            continue
        hits = [p for p in model_platforms if p.contains((s.x, s.y), margin=2)]
        if not hits:
            continue
        pid = hits[0].id
        if visits and visits[-1][0] == pid:
            visits[-1][2] = s.t
        else:
            visits.append([pid, s.t, s.t])
    return visits


def _find_cycle(seq: list[int]) -> list[int]:
    """找重複的循環：最短的 p 使 seq 大致以 p 為週期；沒有就整段。"""
    seq = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]
    if not seq:
        return []
    for p in range(1, len(seq)):
        if seq[p] != seq[0]:
            continue
        candidate = seq[:p]
        rest = seq[p:]
        if all(rest[i] == candidate[i % p] for i in range(min(len(rest), p))):
            return candidate
    if len(seq) > 1 and seq[-1] == seq[0]:
        return seq[:-1]
    return seq


def analyze(events: list[KeyEvent], samples: list[DotSample], steps: list[RouteStep],
            region: list[int], *, jump_key: str = "space") -> MapModel:
    samples = sorted(samples, key=lambda s: s.t)
    busy = _busy(steps)
    platforms = _platforms(samples, busy)
    if not platforms:
        raise ValueError("錄製期間人物沒有站穩在任何平台上，無法分析地圖")
    key, hold, step = _attack_profile(events, steps, jump_key)
    for p in platforms:
        p.attack = _attack_time(p, key, events, samples)
    visits = _visits(samples, platforms, busy)
    for pid, t0, t1 in visits:
        next(p for p in platforms if p.id == pid).dwell += t1 - t0
    farm_ids = {p.id for p in platforms if p.farm}
    farm_seq = [pid for pid, _, _ in visits if pid in farm_ids]
    cycle = _find_cycle(farm_seq)
    model = MapModel(list(region), platforms, cycle, attack_key=key, attack_hold=hold,
                     attack_step=step, jump_key=jump_key)
    _dash_profile(model, steps, samples)
    if len(cycle) > 1 or (cycle and farm_seq.count(cycle[0]) > 1):
        pairs = list(zip(cycle, cycle[1:] + cycle[:1])) if len(cycle) > 1 else []
        for a, b in pairs:
            found = _link_steps(visits, steps, a, b, farm_ids, model)
            if found is not None:
                model.links[(a, b)] = found
    if model.dash and len(cycle) > 1:
        model.lap = _typical_lap(visits, steps, cycle, farm_ids, model)
    return model


def _typical_lap(visits, steps, cycle, farm_ids, model):
    """衝刺型照錄製的一圈走：每次從最後一層回到第一層算一圈，取耗時居中的那一圈
    （不含轉身點方向鍵與攻擊鍵，轉身由衝刺動作自己處理）。"""
    farm = [v for v in visits if v[0] in farm_ids]
    arrivals = [cur[1] for prev, cur in zip(farm, farm[1:])
                if cur[0] == cycle[0] and prev[0] == cycle[-1]]
    laps = []
    for t0, t1 in zip(arrivals, arrivals[1:]):
        lap = [s for s in steps if t0 - .3 <= s.t0 < t1 - .3 and _lap_step(s, model)]
        if lap and any(s.kind == "dash" for s in lap):
            laps.append((t1 - t0, lap))
    if not laps:
        return []
    # 取最常出現的走法（同樣步驟順序最多圈），其中耗時居中的那圈；偶發失誤的圈不選。
    sig = lambda lap: tuple((s.kind, s.keys) for s in lap)
    counts: dict = {}
    for _, lap in laps:
        counts[sig(lap)] = counts.get(sig(lap), 0) + 1
    best = max(counts.values())
    common = sorted((item for item in laps if counts[sig(item[1])] == best),
                    key=lambda item: item[0])
    return common[len(common) // 2][1]


def _lap_step(s, model) -> bool:
    """一圈裡要保留的步驟：轉身點方向鍵、攻擊鍵、對準傳點的小碎步、掉下平台都不算。"""
    if s.kind == "press" and (model.attack_key in s.keys
                              or s.keys in (("left",), ("right",))):
        return False
    if s.kind == "walk" and (abs(s.end[1] - s.start[1]) > 6
                             or abs(s.end[0] - s.start[0]) < 10):
        return False
    return True


def _link_steps(visits, steps, a, b, farm_ids, model):
    """錄製中第一次從打怪平台 a 換到 b 的那段：a 上最後一次掃完之後、到 b 上開始掃之前
    的所有步驟（傳點、下跳、爬繩、連跳、中間按的鍵…），不含攻擊與轉身。"""
    src, dst = model.platform(a), model.platform(b)
    farm_visits = [v for v in visits if v[0] in farm_ids]
    moves = ("walk", "dash")
    for cur, nxt in zip(farm_visits, farm_visits[1:]):
        if cur[0] != a or nxt[0] != b:
            continue
        arrive = nxt[1]
        on_src = [s for s in steps if s.kind in moves and cur[1] - .2 <= s.t0 < arrive
                  and src.contains(s.start) and src.contains(s.end)]
        start_t = on_src[-1].t1 if on_src else cur[2] - .6
        on_dst = [s for s in steps if s.kind in moves and s.t0 >= arrive - .3
                  and dst.contains(s.start) and dst.contains(s.end)]
        end_t = on_dst[0].t0 if on_dst else arrive + .5
        result = []
        for s in steps:
            if not start_t - .05 <= s.t0 < end_t:
                continue
            if s.kind == "press" and (model.attack_key in s.keys
                                      or s.keys in (("left",), ("right",))):
                continue
            result.append(s)
        return result
    return None


def _dash_profile(model: MapModel, steps, samples) -> None:
    dashes = [s for s in steps if s.kind == "dash" and s.keys == (model.attack_key,)]
    if len(dashes) < 2:
        return
    model.dash = True
    jumps = []
    ordered = sorted(samples, key=lambda s: s.t)
    for d in dashes:
        window = [s for s in ordered if d.t0 <= s.t <= d.t1]
        jumps += [abs(b.x - a.x) for a, b in zip(window, window[1:]) if abs(b.x - a.x) >= 8]
    if jumps:
        model.dash_step = sorted(jumps)[len(jumps) // 2]
    votes = 0
    for d in dashes:
        taps = [s for s in steps if s.kind == "press" and s.keys in (("left",), ("right",))
                and d.t0 - 1.0 <= s.t0 <= d.t0]
        if not taps:
            continue
        forward = d.end[0] > d.start[0]
        votes += 1 if (taps[-1].keys[0] == "right") != forward else -1
    model.face_reverse = votes > 0


def describe_link(steps: list[RouteStep]) -> str:
    words = {"walk": "走", "rope": "爬繩", "down_jump": "下跳", "jump": "跳",
             "portal": "傳點", "press": "按鍵", "dash": "衝刺"}
    parts = []
    for s in steps:
        word = words.get(s.kind, s.kind)
        if s.kind == "press":
            word += "".join(_label(k) for k in s.keys)
        if s.kind in ("rope", "down_jump", "portal", "jump"):
            word += f"@({s.start[0]:.0f},{s.start[1]:.0f})"
        if s.kind == "walk" and s.path_key:
            word += f"(沿路按{_label(s.path_key)})"
        if not parts or parts[-1] != word:
            parts.append(word)
    return " → ".join(parts) or "（同一平台）"


def describe(model: MapModel) -> str:
    """給使用者與 AI 看的地圖分析文字。"""
    lines = [f"小地圖範圍 {model.region}（座標相對遊戲視窗）"]
    for p in model.platforms:
        tag = "打怪" if p.farm else "路過"
        height = (f"y={p.y:.0f}" if abs(p.y0 - p.y1) < 2
                  else f"y={p.y0:.0f}（左）～{p.y1:.0f}（右）")
        lines.append(f"- 平台 {p.id}：高度 {height}，左右 x={p.x0:.0f}～{p.x1:.0f}（{tag}，"
                     f"停留 {p.dwell:.0f} 秒）")
    if model.cycle:
        lines.append("打怪順序：" + " → ".join(f"平台 {i}" for i in model.cycle)
                     + (" → 回到開頭" if len(model.cycle) > 1 else ""))
    for (a, b), steps in model.links.items():
        lines.append(f"- 平台 {a} → 平台 {b}：{describe_link(steps)}")
    if model.attack_key:
        how = "按住" if model.attack_hold else "連點"
        if model.dash:
            how = (f"衝刺技能：按住會一次往前衝約 {model.dash_step:.0f} 格；"
                   + ("轉身要按反方向" if model.face_reverse else "先按方向鍵轉身"))
        lines.append(f"攻擊鍵：{_label(model.attack_key)}（{how}）；跳躍鍵：{_label(model.jump_key)}")
    return "\n".join(lines)


def _lap_actions(model: MapModel, loop_count: int) -> list[dict]:
    gen = step_actions(model.region, model.jump_key, header=_HEADER)
    gen.face_reverse = model.face_reverse
    gen.dash_step = model.dash_step
    sections: dict[int, int] = {}
    lap = attach_portal_keys(model.lap)
    for s, nxt in zip(lap, lap[1:] + [None]):
        if s.kind in ("dash", "walk"):
            plat = model.locate(s.start)
            if plat is not None and plat.id not in sections:
                sections[plat.id] = gen.index()
        gen.step(s, nxt)
    body = gen.finish()
    reach = max(4, model.dash_step)
    branches = [{"area": _clip(_area([(model.platform(pid).x0, model.platform(pid).y0),
                                      (model.platform(pid).x1, model.platform(pid).y1)],
                                     reach, 4), model.region),
                 "goto_index": index} for pid, index in sections.items()]
    branches += [{"area": area, "goto_index": index} for area, index in gen.anchors]
    return [{"type": "loop", "name": "小地圖巡邏", "count": loop_count,
             "actions": gen.header(branches) + body}]


def _clip(area, region):
    rx, ry, rw, rh = region
    x0, y0 = max(area[0], rx), max(area[1], ry)
    x1 = min(area[0] + area[2], rx + rw)
    y1 = min(area[1] + area[3], ry + rh)
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]


def patrol_actions(model: MapModel, *, loop_count: int = 100, sweeps: int = 1) -> list[dict]:
    """每個打怪平台按住攻擊鍵左右掃 sweeps 趟，換層照錄製的走，接回下一個平台。
    衝刺型（按住攻擊鍵一格一格衝）照錄製中的一整圈走，不另外掃到平台盡頭。"""
    if not model.cycle:
        raise ValueError("沒有找到打怪的平台（錄製時在平台上按攻擊鍵），無法整理走法")
    if model.dash and model.lap:
        return _lap_actions(model, loop_count), []
    region = model.region
    gen = step_actions(region, model.jump_key, header=_HEADER)
    attack, method, tolerance, margin = {}, "walk", 4, _SWEEP_MARGIN
    if model.attack_key:
        if model.dash:
            attack = {"hold_keys": [model.attack_key], "face_reverse": model.face_reverse}
            method, margin = "hold", 0
            tolerance = int(max(6, min(40, model.dash_step / 2)))
        elif model.attack_hold:
            attack = {"hold_keys": [model.attack_key]}
        else:
            attack = {"path_key": model.attack_key, "path_step": model.attack_step}
    sections: dict[int, int] = {}
    missing = []
    order = model.cycle
    for n, pid in enumerate(order):
        p = model.platform(pid)
        sections[pid] = gen.index()
        left, right = p.x0 + margin, p.x1 - margin
        if right - left < 6:
            left = right = (p.x0 + p.x1) / 2
        nxt = order[(n + 1) % len(order)] if len(order) > 1 else None
        link = model.links.get((pid, nxt)) if nxt is not None else None
        # 先掃離出口遠的那一端，最後停在出口附近。
        exit_x = link[0].start[0] if link else (left + right) / 2
        ends = [right, left] if abs(exit_x - left) <= abs(exit_x - right) else [left, right]
        for _ in range(sweeps):
            for x in ends:
                side = "右" if x == right else "左"
                gen.walk(f"平台 {pid} 往{side}打", (x, p.y_at(x)), tolerance=tolerance,
                         method=method, **attack)
        if nxt is None:
            continue
        if link is None:
            missing.append((pid, nxt))
            gen.goto_start(f"沒錄到平台 {pid} → {nxt} 的走法，重新判斷位置")
            continue
        exit_pos = link[0].start
        if model.dash and abs(exit_pos[0] - gen.here[0]) > tolerance:
            # 衝刺技能：先衝到出口附近，最後一小段再用走的對準。
            gen.walk(f"平台 {pid} 衝到出口附近", exit_pos, tolerance=tolerance,
                     method=method, **attack)
        gen.steps(link)
    body = gen.finish()
    # 衝刺一次可能衝過錄到的平台盡頭：判斷位置時左右多放寬一次衝刺的距離。
    reach = max(4, model.dash_step) if model.dash else 4
    branches = [{"area": _clip(_area([(model.platform(pid).x0, model.platform(pid).y0),
                                      (model.platform(pid).x1, model.platform(pid).y1)],
                                     reach, 4), model.region),
                 "goto_index": sections[pid]} for pid in dict.fromkeys(order)]
    branches += [{"area": area, "goto_index": index} for area, index in gen.anchors]
    actions = [{"type": "loop", "name": "小地圖巡邏", "count": loop_count,
                "actions": gen.header(branches) + body}]
    return actions, missing
