"""小地圖分析：平台、打怪順序、換層方式，整理成每層左右掃的走法。"""
import pytest

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.route_map import analyze, describe, patrol_actions
from tests.core.test_route_learn import REGION, Rec


def two_laps():
    rec = Rec(150, 200)
    for _ in range(2):
        rec.walk("right", 200, hold=("c",))     # 平台 1（上層）
        rec.walk("left", 100, hold=("c",))
        rec.walk("right", 150)
        rec.down_jump(260)                      # 換到平台 2
        rec.walk("right", 220, hold=("c",))
        rec.walk("left", 80, hold=("c",))
        rec.walk("right", 210)
        rec.portal((150, 200))                  # 傳回平台 1
    rec.idle(.5)
    return rec


def model_of(rec):
    steps = rec.learn()
    return analyze(rec.events, rec.samples, steps, REGION)


def test_finds_platforms_cycle_attack_and_links():
    model = model_of(two_laps())
    farms = [p for p in model.platforms if p.farm]
    assert [(round(p.y), round(p.x0), round(p.x1)) for p in farms] == [
        (200, 100, 200), (260, 80, 220)]
    assert model.cycle == [1, 2]
    assert model.attack_key == "c" and model.attack_hold
    kinds = {k: [s.kind for s in v] for k, v in model.links.items()}
    assert "down_jump" in kinds[(1, 2)]
    assert "portal" in kinds[(2, 1)]
    text = describe(model)
    assert "平台 1" in text and "打怪順序" in text and "下跳" in text and "傳點" in text


def test_patrol_script_sweeps_each_farm_platform_once_per_lap():
    model = model_of(two_laps())
    actions, missing = patrol_actions(model, loop_count=20)
    assert missing == []
    script = script_from_dict({"name": "巡邏", "target_window": {"app_name": "msw.exe"},
                               "actions": actions})
    body = [a.params | {"type": str(a.type)} for a in script.actions[0].params["actions"]]
    sweeps = [a for a in body if a.get("name", "").startswith("平台")]
    assert len(sweeps) == 4                     # 兩個平台各左右一趟（不是錄到的兩圈）
    assert all(a["hold_keys"] == ["c"] for a in sweeps)
    targets = [tuple(a["target"]) for a in sweeps]
    assert (197, 200) in targets and (103, 200) in targets
    assert (217, 260) in targets and (83, 260) in targets
    assert sum(a.get("method") == "down_jump" for a in body) == 1
    assert sum(a.get("name") == "走到傳點" for a in body) == 1
    first = body[0]
    assert first["type"] == "minimap_goto"
    assert [b["goto_index"] for b in first["branches"][:2]] == [6, body.index(next(
        a for a in body if a.get("name") == "平台 2 往右打" or a.get("name") == "平台 2 往左打"))]


def test_sweep_ends_near_the_exit():
    model = model_of(two_laps())
    actions, _ = patrol_actions(model)
    body = actions[0]["actions"]
    names = [a.get("name") for a in body]
    # 平台 1 的出口（下跳點 x=150）在中間偏左 → 先往右，最後往左打完再回中間下跳。
    i = names.index("平台 1 往右打")
    assert names[i + 1] == "平台 1 往左打"


def test_missing_link_back_is_reported():
    rec = Rec(150, 200)
    rec.walk("right", 200, hold=("c",))
    rec.walk("left", 100, hold=("c",))
    rec.walk("right", 150)
    rec.down_jump(260)
    rec.walk("right", 220, hold=("c",))
    rec.walk("left", 80, hold=("c",))
    model = model_of(rec)
    actions, missing = patrol_actions(model)
    assert missing == [(2, 1)]


def test_no_attack_means_no_patrol():
    rec = Rec(100, 200)
    rec.walk("right", 180)
    model = model_of(rec)
    with pytest.raises(ValueError, match="打怪"):
        patrol_actions(model)


def _real_recording():
    import json
    from pathlib import Path

    from keyboard_executor.core.route_learn import DotSample, KeyEvent, learn_route
    path = Path(__file__).resolve().parents[1] / "data" / "route_dash_recording.json"
    rec = json.loads(path.read_text(encoding="utf-8"))["recording"]
    events = [KeyEvent(t, k, d) for t, k, d in rec["events"]]
    samples = [DotSample(t, x, y) for t, x, y in rec["samples"]]
    steps = learn_route(events, samples, jump_key=rec["jump_key"])
    return analyze(events, samples, steps, rec["region"], jump_key=rec["jump_key"])


def test_real_dash_recording_two_floors_with_stairs():
    """使用者實錄：下層是階梯（左高右低），上層靠傳點上去、下跳回來；C 是衝刺技能。"""
    model = _real_recording()
    assert len(model.platforms) == 2
    top, bottom = model.platforms
    assert round(top.y) == 270 and 170 <= top.x0 <= 180 and 305 <= top.x1 <= 312
    assert bottom.x0 <= 42 and bottom.x1 >= 316
    assert abs(bottom.y_at(60) - 314) <= 1 and abs(bottom.y_at(250) - 322) <= 1
    assert bottom.contains((190, 322)) and not top.contains((190, 322))
    assert model.cycle == [2, 1]
    assert model.dash and model.face_reverse and 40 <= model.dash_step <= 48
    up = model.links[(2, 1)]
    assert [s.kind for s in up] == ["press", "portal", "press"]
    assert up[0].keys == ("u",)
    assert [s.kind for s in model.links[(1, 2)]] == ["down_jump"]
    text = describe(model)
    assert "衝刺" in text and "反方向" in text and "314（左）" in text


def test_real_dash_recording_patrol_follows_one_recorded_lap():
    """使用者回報：錄製時不是只在下層跑；腳本要照錄到的一整圈走，不要自己左右掃。"""
    model = _real_recording()
    raw, missing = patrol_actions(model, loop_count=3)
    assert missing == []
    script = script_from_dict({"name": "x", "target_window": {"app_name": "msw.exe"},
                               "actions": raw})
    body = raw[0]["actions"][6:]
    moves = [(a["method"], a["target"]) for a in body if a["type"] == "minimap_move"]
    # 衝完要下跳：提早放開 C（避免衝出平台），再走到下跳位置。
    assert moves == [("hold", [46, 314]), ("hold", [178, 322]), ("walk", [178, 322]),
                     ("hold", [308, 270]), ("walk", [308, 270]), ("down_jump", [308, 322])]
    assert body[[a.get("name") for a in body].index("按住 C 往右衝到 (308, 270)")]["tolerance"] > 6
    dashes = [a for a in body if a.get("method") == "hold"]
    assert all(a["hold_keys"] == ["c"] and a["face_reverse"] for a in dashes)
    keys = [a.get("key") for a in body if a["type"] == "key_press"]
    assert keys == ["u", "up", "u"]
    # 實機：衝過頭時就按 U 遊戲沒收到。U 要在走到傳點、停穩之後按，傳送失敗重來也重按。
    acts = raw[0]["actions"]
    walk_i = next(i for i, a in enumerate(acts) if a.get("name") == "走到傳點")
    u_i = next(i for i, a in enumerate(acts) if a.get("key") == "u")
    up_i = next(i for i, a in enumerate(acts) if a.get("key") == "up")
    assert walk_i < u_i < up_i
    confirm = next(a for a in acts if a.get("name") == "確認已傳送")
    assert confirm["otherwise_index"] == walk_i
    assert not any("打" in (a.get("name") or "") for a in body)
    assert script.actions


def test_real_dash_recording_position_check_covers_dash_overshoot():
    """實機日誌：衝到 x=352（超過錄到的 320）時不在任何區域，一直原地下跳。"""
    model = _real_recording()
    raw, _ = patrol_actions(model, loop_count=3)
    branches = raw[0]["actions"][0]["branches"]
    bottom = branches[0]["area"]
    x, y, w, h = bottom
    assert x <= 352 <= x + w and y <= 322 <= y + h
    rx, ry, rw, rh = model.region
    assert x >= rx and x + w <= rx + rw
