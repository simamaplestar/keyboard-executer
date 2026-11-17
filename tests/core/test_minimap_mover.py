"""MinimapMover 以模擬遊戲物理驗證（數值取自 2026-10-11 實機量測）。"""
import math

import pytest

from keyboard_executor.core.minimap import MinimapMover

_DT = .005


class World:
    """走路最高 27 px/s，起步/停止加減速 180 px/s²（50ms 點按約 1px）、
    小地圖顯示延遲 0.15 秒、座標取整格。"""

    def __init__(self, x=137.5, y=171.5, *, speed=27., blocked=False, rope_x=None,
                 rope_top=100., rope_bottom=None, floors=(171.5,), visible=True,
                 attack_lock=0., ignored_jumps=0, escalator=None):
        self.t, self.x, self.y = 0., x, y
        self.escalator = escalator               # (每秒上升格數, 終點高度)：站在手扶梯上被帶上去
        self.speed, self.blocked = speed, blocked
        self.rope_x, self.rope_top, self.rope_bottom = rope_x, rope_top, rope_bottom
        self.grabbed = rope_bottom is None
        self.attack_lock, self.locked_until = attack_lock, 0.
        self.ignored_jumps = ignored_jumps       # 被怪物撞到硬直時下跳沒反應
        self.floors = sorted(floors)
        self.visible = visible
        self.keys, self.log, self.history = set(), [], [(0., x, y)]
        self.v = 0.
        self.fall_at = None
        self.idle_calls = 0
        self.interrupt_at = None

    # --- injected callables ---
    def read(self):
        if not self.visible:
            return None
        seen = self.t - .15
        x, y = next(((hx, hy) for ht, hx, hy in reversed(self.history) if ht <= seen),
                     self.history[0][1:])
        return math.floor(x) + .5, math.floor(y) + .5

    def press(self, key):
        self.log.append(('down', key, round(self.t, 3)))
        if key == 'x' and self.attack_lock:
            self.locked_until = self.t + self.attack_lock
        if (key == 'space' and 'up' in self.keys and self.rope_x is not None
                and abs(self.x - self.rope_x) <= 1.5):
            self.grabbed, self.y = True, min(self.y, self.rope_bottom or self.y)
        if key == 'space' and 'down' in self.keys and self.ignored_jumps:
            self.ignored_jumps -= 1
        elif key == 'space' and 'down' in self.keys:
            lower = [f for f in self.floors if f > self.y + .5]
            if lower:
                self.fall_at = (self.t + .4, lower[0])
                self.escalator = None            # 從手扶梯跳下來
        self.keys.add(key)

    def release(self, key):
        self.log.append(('up', key, round(self.t, 3)))
        self.keys.discard(key)

    def sleep(self, seconds):
        end = self.t + seconds
        while self.t < end - 1e-12:
            step = min(_DT, end - self.t)
            self.t += step
            self._advance(step)
            self.history.append((self.t, self.x, self.y))

    def clock(self):
        return self.t

    def interrupted(self):
        if self.interrupt_at is not None and self.t >= self.interrupt_at:
            self.interrupt_at = None
            return True
        return False

    def idle(self):
        self.idle_calls += 1

    # --- physics ---
    def _advance(self, dt):
        if not self.blocked:
            want = (0. if self.t < self.locked_until
                    else self.speed if 'right' in self.keys and 'left' not in self.keys
                    else -self.speed if 'left' in self.keys and 'right' not in self.keys
                    else 0.)
            step = 180 * dt
            self.v = min(want, self.v + step) if want > self.v else max(want, self.v - step)
            self.x += self.v * dt
        on_rope = (self.rope_x is not None and abs(self.x - self.rope_x) <= 1.5
                   and self.grabbed)
        if on_rope and 'up' in self.keys:
            self.y = max(self.rope_top, self.y - 20 * dt)
        if on_rope and 'down' in self.keys and 'space' not in self.keys:
            self.y = min(self.floors[-1], self.y + 20 * dt) if self.fall_at is None else self.y
        if self.fall_at and self.t >= self.fall_at[0]:
            self.y, self.fall_at = self.fall_at[1], None
        if self.escalator is not None and self.fall_at is None:
            speed, top = self.escalator
            self.y = max(top, self.y - speed * dt)


def mover(world):
    return MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                        interrupted=world.interrupted, idle=world.idle)


@pytest.mark.parametrize('target', [200., 160., 140., 139., 100., 60., 137.])
def test_walk_reaches_target_within_one_pixel(target):
    world = World()
    assert mover(world).walk(target, 1, deadline=20)
    assert abs(world.read()[0] - target) <= 1
    assert not world.keys
    assert world.t < 12


def test_walk_far_uses_one_long_hold_then_short_taps():
    world = World()
    assert mover(world).walk(250., 1, deadline=20)
    holds = [e for e in world.log if e[0] == 'down']
    assert len(holds) <= 6
    assert world.t < 8


def test_walk_blocked_by_wall_gives_up_and_releases():
    world = World(blocked=True)
    assert not mover(world).walk(200., 1, deadline=20)
    assert not world.keys
    assert world.t < 3


def test_missing_dot_fails_without_input():
    world = World(visible=False)
    assert not mover(world).walk(200., 1, deadline=20)
    assert world.log == []


def test_deadline_stops_and_releases():
    world = World(speed=5.)
    assert not mover(world).walk(400., 1, deadline=2)
    assert not world.keys
    assert world.t < 3.5


def test_interruption_releases_then_continues_after_idle():
    world = World()
    world.interrupt_at = .5
    assert mover(world).walk(220., 1, deadline=20)
    ups = [e for e in world.log if e[0] == 'up']
    assert ups[0][2] == pytest.approx(.5, abs=.05)
    assert world.idle_calls >= 2


def test_rope_climbs_to_target_height():
    world = World(rope_x=137.5)
    assert mover(world).rope(137.5, 120., 1, 2, 'space', deadline=20)
    assert abs(world.read()[1] - 120) <= 2
    assert not world.keys


def test_rope_aligns_to_rope_x_before_climbing():
    world = World(x=150.5, rope_x=137.5)
    assert mover(world).rope(137., 120., 1, 2, 'space', deadline=20)
    assert abs(world.read()[1] - 120) <= 2


def test_rope_end_above_head_is_grabbed_with_jump():
    world = World(rope_x=137.5, rope_bottom=167.)
    assert mover(world).rope(137., 120., 1, 2, 'space', deadline=20)
    assert ('down', 'space') in [e[:2] for e in world.log]
    assert abs(world.read()[1] - 120) <= 2


def test_rope_away_from_rope_fails():
    world = World(rope_x=50.)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     log=(reasons := []).append)
    assert not m.rope(137.5, 120., 1, 2, 'space', deadline=20)
    assert not world.keys
    assert '抓不到繩子' in reasons[-1]


def test_rope_end_reports_end_instead_of_alignment():
    world = World(rope_x=137.5, rope_top=150.)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     log=(reasons := []).append)
    assert not m.rope(137.5, 120., 1, 2, 'space', deadline=20)
    assert '繩子盡頭' in reasons[-1]


def test_down_jump_repeats_until_target_floor():
    world = World(y=100.5, floors=(100.5, 130.5, 160.5))
    assert mover(world).down_jump(160., 2, 'space', deadline=20)
    assert abs(world.read()[1] - 160) <= 2
    jumps = [e for e in world.log if e[:2] == ('down', 'space')]
    assert len(jumps) == 2
    # 方向鍵先按、晚放
    first_down = next(e for e in world.log if e[:2] == ('down', 'down'))
    first_jump = jumps[0]
    assert first_jump[2] - first_down[2] >= .1 - 1e-9


def test_down_jump_on_bottom_floor_fails():
    world = World(y=160.5, floors=(160.5,))
    assert not mover(world).down_jump(190., 2, 'space', deadline=20)
    assert not world.keys


def test_down_jump_below_target_fails_without_input():
    world = World(y=160.5, floors=(100.5, 160.5))
    assert not mover(world).down_jump(100., 2, 'space', deadline=20)
    assert world.log == []


def test_rope_ignores_loose_tolerance_for_rope_alignment():
    world = World(x=139.5, rope_x=137.5)
    assert mover(world).rope(137., 120., 3, 3, 'space', deadline=20)


def test_path_key_is_tapped_along_the_walk_not_held():
    world = World(x=60.5)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, path_key='x')
    assert m.walk(220., 1, deadline=30)
    taps = [e for e in world.log if e[:2] == ('down', 'x')]
    assert len(taps) >= 5
    for down in taps:                       # 每次都只按一下就放開
        up = next(e for e in world.log if e[:2] == ('up', 'x') and e[2] >= down[2])
        assert up[2] - down[2] <= .15
    assert abs(world.read()[0] - 220) <= 1
    assert not world.keys


def test_path_key_that_freezes_movement_still_reaches_target():
    world = World(x=60.5, attack_lock=.4)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     path_key='x')
    assert m.walk(220., 1, deadline=40)
    assert abs(world.read()[0] - 220) <= 1


def test_taps_that_never_move_fail_fast_and_mention_path_key():
    world = World(blocked=True)
    reasons = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     log=reasons.append, path_key='x')
    assert not m.walk(140., 1, deadline=20)
    assert world.t < 5          # 6 次逐漸加長的點按，不必等滿 20 秒逾時
    assert 'x' in reasons[-1]
    assert not world.keys


def test_path_key_stiffness_longer_than_stuck_limit_is_not_a_wall():
    world = World(x=60.5, attack_lock=1.2)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     path_key='x', log=(reasons := []).append)
    assert m.walk(160., 1, deadline=60), reasons
    assert abs(world.read()[0] - 160) <= 1


def test_fine_adjustment_never_taps_path_key():
    world = World(x=137.5)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     path_key='x')
    assert m.walk(140., 1, deadline=20)
    assert not [e for e in world.log if e[1] == 'x']


@pytest.mark.parametrize('start, target', [(60.5, 160.), (60.5, 71.), (200.5, 92.)])
def test_no_path_key_after_coarse_phase(start, target):
    world = World(x=start, attack_lock=.8)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     path_key='x')
    assert m.walk(target, 1, deadline=60)
    moves = [e for e in world.log if e[1] in ('left', 'right')]
    holds = [(d[2], u[2]) for d, u in zip(moves[::2], moves[1::2]) if u[2] - d[2] > .2]
    last_hold_end = holds[-1][1] if holds else 0
    assert not [e for e in world.log if e[1] == 'x' and e[2] > last_hold_end]


@pytest.mark.parametrize('present', [False, True])
def test_path_key_only_when_gate_sees_monster(present):
    world = World(x=60.5)
    checks = []

    def gate():
        checks.append(world.t)
        return present

    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     path_key='x', path_gate=gate)
    assert m.walk(220., 1, deadline=30)
    taps = [e for e in world.log if e[:2] == ('down', 'x')]
    assert checks
    assert (len(taps) >= 5) if present else not taps


def test_down_jump_retries_when_a_jump_is_swallowed():
    world = World(y=100.5, floors=(100.5, 130.5), ignored_jumps=2)
    assert mover(world).down_jump(130., 2, 'space', deadline=30)
    assert abs(world.read()[1] - 130) <= 2


def test_down_jump_gives_up_after_three_unchanged_attempts():
    world = World(y=160.5, floors=(160.5,))
    reasons = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     log=reasons.append)
    assert not m.down_jump(190., 2, 'space', deadline=60)
    assert len([e for e in world.log if e[:2] == ('down', 'space')]) == 3
    assert '最底層' in reasons[-1]


def test_longer_path_step_taps_less_often():
    counts = {}
    for step in (5, 10):
        world = World(x=60.5)
        m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                         path_key='x', path_step=step)
        assert m.walk(220., 1, deadline=30)
        counts[step] = len([e for e in world.log if e[:2] == ('down', 'x')])
    assert counts[10] <= counts[5] * .6


def test_loose_tolerance_finishes_right_after_release_without_waiting():
    world = World()
    m = mover(world)
    assert m.walk(200., 10, deadline=20)
    release = max(e[2] for e in world.log if e[0] == 'up')
    assert world.t - release < .05          # 不等 0.25 秒反應＋停穩
    world.sleep(1.)                         # 滑行結束後仍在誤差內
    assert abs(world.read()[0] - 200) <= 10


def test_tight_tolerance_still_waits_until_settled():
    world = World()
    assert mover(world).walk(200., 1, deadline=20)
    release = max(e[2] for e in world.log if e[0] == 'up')
    assert world.t - release >= .25


def test_walk_from_standstill_starts_without_response_wait():
    world = World()
    mover(world).walk(200., 10, deadline=20)
    first = next(e for e in world.log if e[0] == 'down')
    assert first[2] < .25


def test_down_jump_right_after_walk_does_not_wait_for_slide_to_stop():
    world = World(y=100.5, floors=(100.5, 130.5))
    world.keys.add('right')
    world.sleep(1.)
    world.release('right')                  # 還在滑行
    start = world.t
    assert mover(world).down_jump(130., 2, 'space', deadline=20)
    first_down = next(e for e in world.log if e[:2] == ('down', 'down'))
    assert first_down[2] - start < .25


def test_hold_keys_stay_down_during_the_long_walk_and_are_released():
    world = World(x=60.5)
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, hold_keys=('c',))
    assert m.walk(200., 3, deadline=30)
    downs = [e for e in world.log if e[:2] == ('down', 'c')]
    ups = [e for e in world.log if e[:2] == ('up', 'c')]
    assert downs and len(downs) == len(ups)
    right = next(e for e in world.log if e[:2] == ('down', 'right'))
    assert downs[0][2] <= right[2]              # 先按住 C 再走
    assert ups[0][2] - downs[0][2] >= 3         # 長距離全程按住
    world.sleep(1)                              # 容許誤差寬：放開後不等停穩
    assert abs(world.read()[0] - 200) <= 3
    assert not world.keys


def test_hold_keys_blocked_walk_waits_longer_and_releases_everything():
    world = World(blocked=True)
    logs = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, hold_keys=('c',),
                     log=logs.append)
    assert not m.walk(200., 1, deadline=20)
    assert not world.keys
    assert 3 <= world.t < 5
    assert 'c' in logs[-1]


class DashWorld(World):
    """衝刺技能（依實錄）：按住 C 每 0.25 秒往面向衝 44 格；按 C 當下有按住方向鍵就轉向
    （reverse 時轉成相反方向）；剛衝完 0.4 秒內單獨點方向鍵轉不了身。沒按 C 時照常走路。"""

    def __init__(self, x=46.5, *, reverse=True, lo=38., hi=320., dash=True, coast=False,
                 **kw):
        super().__init__(x=x, **kw)
        self.reverse, self.lo, self.hi, self.dash = reverse, lo, hi, dash
        self.facing, self.next_dash, self.busy_until = 1, None, 0.
        self.coast, self.coast_at = coast, None     # 放開 C 後動作還會再衝一次

    def _turn(self, key):
        self.facing = (1 if key == 'right' else -1) * (-1 if self.reverse else 1)

    def press(self, key):
        if key in ('left', 'right') and self.t >= self.busy_until:
            self._turn(key)
        if key == 'c':
            held = [k for k in ('left', 'right') if k in self.keys]
            if held:
                self._turn(held[-1])
        super().press(key)

    def release(self, key):
        if key == 'c' and self.coast and self.next_dash is not None:
            self.coast_at = (self.t + .2, self.facing)
        super().release(key)

    def _advance(self, dt):
        if self.coast_at and self.t >= self.coast_at[0]:
            self.x = min(self.hi, max(self.lo, self.x + 44 * self.coast_at[1]))
            self.coast_at, self.busy_until = None, self.t + .4
        if 'c' not in self.keys or not self.dash:
            self.next_dash = None
            super()._advance(dt)
            self.x = min(self.hi, max(self.lo, self.x))
            return
        if self.next_dash is None:
            self.next_dash = self.t + .05
        if self.t >= self.next_dash:
            self.x = min(self.hi, max(self.lo, self.x + 44 * self.facing))
            self.next_dash = self.t + .25
            self.busy_until = self.t + .4


def dash_mover(world, reverse):
    return MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                        interrupted=world.interrupted, idle=world.idle, hold_keys=('c',),
                        face_reverse=reverse)


def test_hold_move_dashes_with_reversed_facing_and_releases():
    world = DashWorld(x=46.5)
    m = dash_mover(world, True)
    assert m.hold_move(178., 22, deadline=20)
    assert 156 <= world.x <= 222
    first_dir = next(e for e in world.log if e[0] == 'down' and e[1] in ('left', 'right'))
    assert first_dir[1] == 'left'           # 往右衝要點左
    assert not world.keys


def test_hold_move_learns_reversed_facing_when_guess_is_wrong():
    world = DashWorld(x=178.5)
    logs = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, hold_keys=('c',),
                     log=logs.append)
    assert m.hold_move(46., 22, deadline=20)        # 以為不用反向，衝錯邊後自己改
    assert world.x <= 68
    assert m.face_reverse
    assert any('轉身' in line for line in logs)
    assert not world.keys


def test_hold_move_already_there_presses_nothing():
    world = DashWorld(x=310.5)
    assert dash_mover(world, True).hold_move(320., 22, deadline=20)
    assert world.log == []


def test_hold_move_against_wall_gives_up():
    world = DashWorld(x=40.5, lo=38.)
    m = dash_mover(world, True)
    assert not m.hold_move(0., 6, deadline=20)
    assert not world.keys


def test_hold_move_turns_right_after_a_dash_by_holding_direction_with_c():
    """實機：衝到最右邊後馬上要往回衝，單獨點方向鍵被遊戲忽略，一直往牆衝。"""
    world = DashWorld(x=46.5, hi=352.)
    m = dash_mover(world, True)
    assert m.hold_move(320., 22, deadline=20)        # 衝過頭撞到右牆 352
    world.sleep(.3)
    assert m.hold_move(38., 22, deadline=40)         # 動作剛結束就往回
    assert world.x <= 60
    assert not world.keys


def test_hold_move_falls_back_to_walking_when_dash_does_nothing():
    world = DashWorld(x=200.5, dash=False)
    logs = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, hold_keys=('c',),
                     face_reverse=True, log=logs.append)
    assert m.hold_move(170., 6, deadline=40)
    assert abs(world.read()[0] - 170) <= 6
    assert any('改用走的' in line for line in logs)
    assert not world.keys


def test_hold_move_coasting_after_release_is_not_mistaken_for_wrong_facing():
    """實機：剛衝完小地圖還在往舊方向動，被當成轉身方向錯而換邊，結果真的轉錯。"""
    world = DashWorld(x=60.5, hi=352., coast=True)
    logs = []
    m = MinimapMover(world.read, world.press, world.release, world.sleep, world.clock,
                     interrupted=world.interrupted, idle=world.idle, hold_keys=('c',),
                     face_reverse=True, log=logs.append)
    for target in (300., 60., 300., 178.):
        assert m.hold_move(target, 22, deadline=world.t + 20), logs
        assert abs(world.x - target) <= 22 + 44
    assert m.face_reverse
    assert not any('轉身' in line for line in logs)
    assert not world.keys


def test_quick_down_jump_leaves_moving_escalator_without_waiting():
    """手扶梯一直往上帶，高度不會停：立即下跳不等停穩，還沒到上層就跳回第一層。"""
    world = World(y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    assert mover(world).down_jump(171., 3, 'space', deadline=20, quick=True)
    first_down = next(e for e in world.log if e[:2] == ('down', 'down'))
    assert first_down[2] - .3 < .1
    assert abs(world.read()[1] - 171) <= 2


def test_normal_down_jump_still_waits_for_height_to_settle():
    world = World(y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    mover(world).down_jump(171., 3, 'space', deadline=20)
    first_down = next(e for e in world.log if e[:2] == ('down', 'down'))
    assert first_down[2] - .3 >= 1.


def test_peek_reads_position_without_waiting_for_dot_to_stop():
    world = World(y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    pos = mover(world).peek()
    assert pos is not None and pos[1] > 155
    assert world.t - .3 < .05


def test_peek_retries_briefly_when_dot_is_hidden():
    world = World(visible=False)
    assert mover(world).peek(limit=.3) is None
    assert .3 <= world.t < .4


def test_down_jump_finishes_right_after_landing_without_second_settle():
    """落地站穩就判斷到了沒，不要再多等一次停穩（實機每層多卡約 0.4 秒）。"""
    world = World(y=100.5, floors=(100.5, 130.5))
    assert mover(world).down_jump(130., 2, 'space', deadline=20)
    jump_at = next(e for e in world.log if e[:2] == ('down', 'space'))[2]
    # 0.4 秒後落地、小地圖晚 0.15 秒顯示、再 0.15 秒確認不動
    assert world.t - jump_at < .85
