import cv2
import numpy as np
import pytest

from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import ScreenCapture
from keyboard_executor.platforms.factory import Platform
from tests.core.test_minimap_mover import World
from tests.core.test_player_basic import make_script
from tests.fakes import FakeInputBackend, FakeWindowManager
from tests.core.test_player_basic import make_window

REGION = [20, 30, 300, 260]


class WorldCapture(ScreenCapture):
    """依模擬世界的黃點位置（視窗相對、含 0.15s 顯示延遲）畫出小地圖。"""

    def __init__(self, world, win, scale=1.):
        self.world, self.win, self.scale = world, win, scale
        self.monster = None          # 畫面上出現的怪物圖（偵測範圍擷取時貼上）
        self.monster_rects = []

    def capture(self, rect):
        if rect.height == 200:       # 沿路按鍵的偵測範圍
            self.monster_rects.append(rect)
            scene = np.full((rect.height, rect.width, 3), 90, dtype=np.uint8)
            if self.monster is not None:
                h, w = self.monster.shape[:2]
                scene[50:50+h, 300:300+w] = self.monster
            return scene
        image = np.zeros((rect.height, rect.width, 3), dtype=np.uint8)
        pos = self.world.read()
        if pos is not None:
            cx = round((self.win.x + pos[0]) * self.scale) - rect.x
            cy = round((self.win.y + pos[1]) * self.scale) - rect.y
            cv2.circle(image, (cx, cy), round(5 * self.scale), (0, 230, 255), -1)
        cv2.circle(image, (10, 10), 2, (0, 230, 255), -1)          # 小圖示干擾
        return image

    def scale_factor(self):
        return self.scale


def setup(world, scale=1.):
    win = make_window()
    backend = FakeInputBackend()
    backend.key_down = lambda key: (backend.calls.append(('key_down', key)), world.press(key))
    backend.key_up = lambda key: (backend.calls.append(('key_up', key)), world.release(key))
    platform = Platform(input_backend=backend, window_manager=FakeWindowManager([win]),
                        screen_capture=WorldCapture(world, win, scale))
    player = Player(platform, sleep=world.sleep, clock=world.clock)
    return player, backend


@pytest.mark.parametrize('scale', [1., 2.])
def test_walk_action_reaches_target(scale):
    world = World(x=137.5, y=171.5)
    player, backend = setup(world, scale)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [210, 171]},
        {"type": "key_press", "key": "b"}]))
    assert result.ok, result.error
    assert abs(world.read()[0] - 210) <= 1
    assert not world.keys
    assert ('key_press', 'b', 100) in backend.calls


def test_failed_move_aborts_with_position_and_releases_keys():
    world = World(x=137.5, blocked=True)
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [210, 171]},
        {"type": "key_press", "key": "b"}]))
    assert not result.ok
    assert '小地圖移動失敗' in result.error and '目前 138, 172' in result.error
    assert not world.keys
    assert not any(c[0] == 'key_press' for c in backend.calls)


def test_failed_move_can_continue():
    world = World(visible=False)
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [210, 171],
         "on_timeout": "continue"},
        {"type": "key_press", "key": "b"}]))
    assert result.ok
    assert ('key_press', 'b', 100) in backend.calls


def test_down_jump_action_uses_jump_key():
    world = World(x=137.5, y=100.5, floors=(100.5, 130.5, 160.5))
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [137, 160],
         "method": "down_jump", "jump_key": "space"}]))
    assert result.ok, result.error
    assert abs(world.read()[1] - 160) <= 2


def test_stop_while_holding_releases_keys():
    import threading
    world = World(x=137.5)
    stop = threading.Event()
    win = make_window()
    backend = FakeInputBackend()
    backend.key_down = lambda key: (world.press(key), stop.set() if key == 'right' else None)
    backend.key_up = world.release
    platform = Platform(input_backend=backend, window_manager=FakeWindowManager([win]),
                        screen_capture=WorldCapture(world, win))
    result = Player(platform, stop_event=stop, sleep=world.sleep, clock=world.clock).play(
        make_script([{"type": "minimap_move", "region": REGION, "target": [250, 171]}]))
    assert not result.ok
    assert not world.keys


def test_walk_that_ends_on_another_floor_fails():
    world = World(x=137.5, y=171.5)
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [210, 120]}]))
    assert not result.ok
    assert '高度' in result.error


def test_learned_slide_carries_to_next_walk_in_same_run():
    world = World(x=60.5, y=171.5, speed=45.)          # 騎乘：更快、滑更遠
    player, backend = setup(world)
    import keyboard_executor.core.minimap as minimap
    seen = []
    original = minimap.MinimapMover.walk

    def walk(self, *args, **kwargs):
        seen.append(self.slide)
        return original(self, *args, **kwargs)

    minimap.MinimapMover.walk = walk
    try:
        result = player.play(make_script([
            {"type": "minimap_move", "region": REGION, "target": [200, 171]},
            {"type": "minimap_move", "region": REGION, "target": [80, 171]}]))
    finally:
        minimap.MinimapMover.walk = original
    assert result.ok, result.error
    assert seen[0] == 6. and seen[1] != 6.


@pytest.mark.parametrize('present', [False, True])
def test_path_key_follows_monster_template_in_region(present):
    tpl = np.zeros((20, 24, 3), dtype=np.uint8)
    tpl[:, :12] = (0, 160, 0)
    tpl[5:12, 15:20] = (0, 220, 255)
    world = World(x=60.5)
    player, backend = setup(world)
    player._templates = lambda name: tpl
    capture = player._platform.screen_capture
    capture.monster = cv2.flip(tpl, 1) if present else None
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [220, 171], "path_key": "x",
         "path_template": "綠帽怪", "path_region": [0, 500, 900, 200]}]))
    assert result.ok, result.error
    taps = [c for c in backend.calls if c == ('key_down', 'x')]
    assert capture.monster_rects
    assert bool(taps) is present


def _goto_script(world_branch_actions, otherwise="abort", otherwise_index=None):
    goto = {"type": "minimap_goto", "region": REGION, "otherwise": otherwise,
            "branches": [{"area": [100, 160, 100, 20], "goto_index": 3},
                         {"area": [100, 120, 100, 20], "goto_index": 4}]}
    if otherwise_index is not None:
        goto["otherwise_index"] = otherwise_index
    return make_script([goto,
                        {"type": "key_press", "key": "a"},
                        {"type": "key_press", "key": "b"},
                        {"type": "key_press", "key": "c"},
                        {"type": "key_press", "key": "d"}])


@pytest.mark.parametrize('y, pressed', [(171.5, ['c', 'd']), (130.5, ['d'])])
def test_minimap_goto_jumps_to_area_branch(y, pressed):
    world = World(x=137.5, y=y)
    player, backend = setup(world)
    result = player.play(_goto_script(None))
    assert result.ok, result.error
    assert [c[1] for c in backend.calls if c[0] == 'key_press'] == pressed


def test_minimap_goto_otherwise_abort_and_continue():
    world = World(x=30.5, y=171.5)                      # 不在任何區域
    player, backend = setup(world)
    result = player.play(_goto_script(None))
    assert not result.ok and '小地圖位置' in result.error
    world = World(x=30.5, y=171.5)
    player, backend = setup(world)
    result = player.play(_goto_script(None, otherwise="goto", otherwise_index=2))
    assert result.ok
    assert [c[1] for c in backend.calls if c[0] == 'key_press'] == ['b', 'c', 'd']


def test_failed_move_recovers_through_minimap_goto():
    """被撞下平台：走路失敗 → 依位置跳到該層的步驟繼續，而不是停止腳本。"""
    world = World(x=137.5, y=171.5)
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [180, 120],   # 在別層 → 失敗
         "on_timeout": "goto", "goto_index": 2},
        {"type": "key_press", "key": "a"},
        {"type": "minimap_goto", "region": REGION,
         "branches": [{"area": [100, 160, 150, 20], "goto_index": 3}]},
        {"type": "key_press", "key": "z"}]))
    assert result.ok, result.error
    assert [c[1] for c in backend.calls if c[0] == 'key_press'] == ['z']


def test_hold_dash_action_runs_and_remembers_reversed_facing():
    """實機回報：執行 method=hold 時 'hold' KeyError 中止。衝刺動作要能整段跑完。"""
    from tests.core.test_minimap_mover import DashWorld
    world = DashWorld(x=46.5, y=171.5, lo=38., hi=300.)
    player, backend = setup(world)
    steps = []
    player._on_step = steps.append              # 逐步顯示動作名稱（原本在這裡 KeyError）
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [178, 171], "method": "hold",
         "hold_keys": ["c"], "tolerance": 22},
        {"type": "minimap_move", "region": REGION, "target": [46, 171], "method": "hold",
         "hold_keys": ["c"], "tolerance": 22},
        {"type": "key_press", "key": "b"}]))
    assert result.ok, result.error
    assert world.read()[0] <= 68
    assert not world.keys
    assert ('key_press', 'b', 100) in backend.calls
    assert any(s.get("kind") == "step" for s in steps)


def test_hold_method_label():
    from keyboard_executor.core.models import action_from_dict, action_label
    a = action_from_dict({"type": "minimap_move", "region": REGION, "target": [178, 171],
                          "method": "hold", "hold_keys": ["c"], "tolerance": 22})
    assert action_label(a) == "按住衝到小地圖 (178, 171)（按住 c）"


def _escalator_goto(quick):
    goto = {"type": "minimap_goto", "region": REGION,
            "branches": [{"area": [100, 100, 100, 68], "goto_index": 2}]}   # y < 168：已被帶上去
    if quick:
        goto["quick"] = True
    return make_script([goto, {"type": "key_press", "key": "a"},
                        {"type": "key_press", "key": "b"}])


def test_quick_minimap_goto_judges_moving_dot_immediately():
    """站在手扶梯上：立即判斷不等黃點停下，馬上跳到「下跳」分支。"""
    world = World(x=137.5, y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    player, backend = setup(world)
    result = player.play(_escalator_goto(True))
    assert result.ok, result.error
    assert [c[1] for c in backend.calls if c[0] == 'key_press'] == ['b']
    assert world.t - .3 < .5


def test_minimap_goto_without_quick_waits_for_moving_dot():
    world = World(x=137.5, y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    player, backend = setup(world)
    player.play(_escalator_goto(False))
    assert world.t - .3 >= 1.2


def test_quick_down_jump_action_leaves_escalator():
    world = World(x=137.5, y=165.5, floors=(130.5, 171.5), escalator=(20., 130.5))
    world.sleep(.3)                          # 已經在手扶梯上一段時間
    player, backend = setup(world)
    result = player.play(make_script([
        {"type": "minimap_move", "region": REGION, "target": [137, 171],
         "method": "down_jump", "tolerance": 3, "quick": True}]))
    assert result.ok, result.error
    assert abs(world.read()[1] - 171) <= 2
    first_down = next(i for i, c in enumerate(backend.calls) if c == ('key_down', 'down'))
    assert first_down is not None
