"""小地圖路線學習：模擬錄製（按鍵＋黃點軌跡）→ 步驟 → 可載入的腳本。"""
import pytest

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.route_learn import (
    DotSample, KeyEvent, learn_route, route_actions, summarize,
)

REGION = [20, 160, 300, 260]
DT = .04


class Rec:
    """模擬玩家操作：產生按鍵事件與每 40ms 一次的黃點讀數。"""

    def __init__(self, x=100.0, y=200.0):
        self.t, self.x, self.y = 0.0, x, y
        self.events, self.samples = [], []
        self.idle(.5)

    def _tick(self, n=1):
        for _ in range(n):
            self.samples.append(DotSample(self.t, self.x, self.y))
            self.t += DT

    def down(self, key):
        self.events.append(KeyEvent(self.t, key, True))

    def up(self, key):
        self.events.append(KeyEvent(self.t, key, False))

    def idle(self, sec):
        self._tick(int(round(sec / DT)))

    def walk(self, key, to_x, hold=(), tap=None, speed=27.0):
        for k in hold:
            self.down(k)
        self.down(key)
        self._tick(4)                       # 反應延遲
        sign = 1 if to_x > self.x else -1
        tapped = 0
        while (to_x - self.x) * sign > 4:
            self.x += sign * speed * DT
            if tap and tapped % 6 == 0:
                self.down(tap)
                self._tick()
                self.up(tap)
                tapped += 1
                continue
            tapped += 1
            self._tick()
        self.up(key)
        for k in hold:
            self.up(k)
        while (to_x - self.x) * sign > 0:   # 放開後滑行
            self.x += sign * min(1.0, abs(to_x - self.x))
            self._tick()
        self.idle(.4)

    def climb(self, to_y, key="up"):
        self.down(key)
        self._tick(4)
        sign = 1 if to_y > self.y else -1
        while (to_y - self.y) * sign > 0:
            self.y += sign * min(1.5, abs(to_y - self.y))
            self._tick()
        self.up(key)
        self.idle(.4)

    def down_jump(self, to_y, jump="space"):
        self.down("down")
        self._tick(2)
        self.down(jump)
        self._tick(2)
        self.up(jump)
        self._tick(2)
        self.up("down")
        while self.y < to_y:
            self.y = min(to_y, self.y + 4)
            self._tick()
        self.idle(.4)

    def jump(self, key, dx, dy=0.0, jump="space"):
        self.down(key)
        self._tick(3)
        self.down(jump)
        self._tick()
        self.up(jump)
        steps = 15
        for i in range(steps):
            self.x += dx / steps
            arc = -6 * (1 - abs(2 * (i + 1) / steps - 1))
            self.y += dy / steps
            self.samples.append(DotSample(self.t, self.x, self.y + arc))
            self.t += DT
        self.up(key)
        self.idle(.4)

    def portal(self, to):
        self.down("up")
        self._tick(5)
        self.up("up")
        self._tick(3)
        self.x, self.y = to
        self.idle(.6)

    def press(self, key, sec=.1):
        self.down(key)
        self.idle(sec)
        self.up(key)
        self.idle(.3)

    def learn(self, **kw):
        return learn_route(self.events, self.samples, **kw)


def kinds(steps):
    return [s.kind for s in steps]


def test_walk_with_held_attack_key():
    rec = Rec(100, 200)
    rec.walk("right", 180, hold=("c",))
    rec.walk("left", 120, hold=("c",))
    steps = rec.learn()
    assert kinds(steps) == ["walk", "walk"]
    assert steps[0].hold_keys == ("c",) and abs(steps[0].end[0] - 180) <= 1
    assert steps[1].hold_keys == ("c",) and abs(steps[1].end[0] - 120) <= 1


def test_tapped_attack_becomes_path_key_not_presses():
    rec = Rec(60, 200)
    rec.walk("right", 200, tap="x")
    steps = rec.learn()
    assert kinds(steps) == ["walk"]
    assert steps[0].path_key == "x" and steps[0].hold_keys == ()
    assert 1 <= steps[0].path_step <= 10


def test_rope_down_jump_jump_portal_and_presses():
    rec = Rec(100, 300)
    rec.walk("right", 150)
    rec.climb(250)                       # 爬繩上去
    rec.press("t")                       # 原地按 T
    rec.down_jump(300)                   # 下跳回來
    rec.jump("right", 30)                # 往右跳過坑
    rec.walk("right", 220)
    rec.portal((80, 200))                # 傳點
    rec.press("right", .12)              # 往右按一下
    steps = rec.learn()
    assert kinds(steps) == ["walk", "rope", "press", "down_jump", "jump", "walk",
                            "portal", "press"]
    rope = steps[1]
    assert abs(rope.start[0] - 150) <= 1 and abs(rope.end[1] - 250) <= 1
    assert steps[2].keys == ("t",)
    assert steps[3].end[1] == pytest.approx(300, abs=1)
    assert steps[4].keys == ("right", "space") and 200 <= steps[4].hold_ms <= 2000
    assert steps[6].end == (80, 200)
    assert steps[7].keys == ("right",) and steps[7].hold_ms == pytest.approx(120, abs=40)
    assert "傳點 1" in summarize(steps)


def test_repeated_taps_in_place_merge_into_one_hold():
    rec = Rec()
    for _ in range(4):
        rec.down("c")
        rec.idle(.08)
        rec.up("c")
        rec.idle(.12)
    rec.walk("right", 160)
    steps = rec.learn()
    assert kinds(steps) == ["press", "walk"]
    assert steps[0].keys == ("c",) and steps[0].hold_ms >= 600


def test_simultaneous_keys_become_combo():
    rec = Rec()
    rec.down("ctrl")
    rec.down("1")
    rec.idle(.1)
    rec.up("1")
    rec.up("ctrl")
    rec.idle(.3)
    rec.walk("right", 160)
    steps = rec.learn()
    assert steps[0].kind == "press" and steps[0].keys == ("ctrl", "1")


def test_idle_wait_is_kept_as_delay():
    rec = Rec()
    rec.walk("right", 160)
    rec.idle(3)
    rec.walk("left", 110)
    steps = rec.learn()
    assert steps[1].idle_before >= 2.5
    actions = route_actions(steps, REGION)[0]["actions"]
    assert any(a["type"] == "delay" and a["ms"] >= 2500 for a in actions)


def test_generated_script_validates_and_jumps_back_on_failure():
    rec = Rec(100, 300)
    rec.press("t")
    rec.walk("right", 150, hold=("c",))
    rec.climb(250)
    rec.down_jump(300)
    rec.walk("right", 220)
    rec.portal((80, 200))
    steps = rec.learn()
    actions = route_actions(steps, REGION, loop_count=40)
    script = script_from_dict({"name": "學到的路線", "target_window": {"app_name": "msw.exe"},
                               "actions": actions})
    loop = script.actions[0]
    assert loop.params["count"] == 40
    body = [a.params | {"type": str(a.type)} for a in loop.params["actions"]]
    first = body[0]
    assert first["type"] == "minimap_goto"
    # 第一個分支指回路線開頭（包含移動前的原地按 T）。
    assert first["branches"][0]["goto_index"] == 6
    assert body[6]["type"] == "key_press" and body[6]["key"] == "t"
    moves = [a for a in body if a["type"] == "minimap_move"]
    assert all(m["on_timeout"] == "goto" and m["goto_index"] == 0 for m in moves)
    assert any(m["hold_keys"] == ["c"] for m in moves)
    assert any(m["method"] == "rope" for m in moves)
    assert any(m["method"] == "down_jump" for m in moves)
    portal = next(i for i, a in enumerate(body) if a.get("name") == "走到傳點")
    confirm = next(a for a in body if a.get("name") == "確認已傳送")
    assert confirm["otherwise_index"] == portal
    assert body[-1]["name"] == "本圈結束"
    for branch in first["branches"]:
        assert 0 <= branch["goto_index"] < len(body)


def test_no_dot_or_no_movement_is_a_clear_error():
    with pytest.raises(ValueError, match="黃點"):
        learn_route([KeyEvent(0, "c", True)], [])
    rec = Rec()
    rec.press("t")
    with pytest.raises(ValueError, match="移動"):
        route_actions(rec.learn(), REGION)


def test_direction_and_attack_held_in_place_becomes_combo():
    rec = Rec()
    rec.down("c")
    rec.down("right")
    rec.idle(1.25)                       # 被怪擋住，原地按住右＋C
    rec.up("right")
    rec.up("c")
    rec.idle(.3)
    rec.walk("left", 60)
    steps = rec.learn()
    assert steps[0].kind == "press" and steps[0].keys == ("right", "c")
    assert steps[0].hold_ms == pytest.approx(1250, abs=50)
    actions = route_actions(steps, REGION)[0]["actions"]
    combo = next(a for a in actions if a["type"] == "key_combo" and "c" in a["keys"])
    assert combo["keys"] == ["right", "c"]


def test_walk_end_before_portal_is_not_the_portal_destination():
    rec = Rec(100, 322)
    rec.down("right")
    rec._tick(4)
    while rec.x < 290:
        rec.x += 1.1
        rec._tick()
    rec.up("right")
    rec.portal((150, 270))                # 放開右鍵馬上進傳點
    steps = rec.learn()
    walk = steps[0]
    assert walk.kind == "walk" and walk.end[1] == pytest.approx(322, abs=1)
    assert steps[-1].kind == "portal" and steps[-1].end == (150, 270)


def test_jumps_while_holding_direction_become_one_walk_with_jump_taps():
    rec = Rec(300, 270)
    rec.down("left")
    rec._tick(3)
    for _ in range(4):                    # 按住左一路連跳下坡
        rec.down("space")
        rec._tick()
        rec.up("space")
        for _ in range(12):
            rec.x -= 1.2
            rec.y += .8
            rec._tick()
    rec.up("left")
    rec.idle(.5)
    steps = rec.learn()
    assert kinds(steps) == ["walk"]
    assert steps[0].path_key == "space"
    assert steps[0].end[1] > 270 + 30


def test_attack_held_across_direction_changes_is_part_of_walking():
    rec = Rec(100, 200)
    rec.down("c")
    for key, x in (("right", 160), ("left", 110), ("right", 150)):
        rec.down(key)
        rec._tick(3)
        sign = 1 if x > rec.x else -1
        while (x - rec.x) * sign > 0:
            rec.x += sign * 1.1
            rec._tick()
        rec.up(key)
        rec.idle(.3)                      # 停下來繼續按著 C 打怪
    rec.up("c")
    rec.idle(.4)
    steps = rec.learn()
    assert kinds(steps) == ["walk", "walk", "walk"]
    assert all(s.hold_keys == ("c",) for s in steps)
