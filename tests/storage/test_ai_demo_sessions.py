from keyboard_executor.storage.ai_demo_sessions import AiDemoSessionStore


def test_create_makes_unique_dirs(tmp_path):
    store = AiDemoSessionStore(tmp_path)
    a, b = store.create(), store.create()
    assert a != b
    assert a.is_dir() and b.is_dir()
    assert a.parent == tmp_path / "ai_demos"


def test_store_keeps_latest_10(tmp_path):
    store = AiDemoSessionStore(tmp_path, keep=10)
    made = [store.create() for _ in range(12)]
    left = sorted(p.name for p in (tmp_path / "ai_demos").iterdir())
    assert len(left) == 10
    assert made[0].name not in left and made[1].name not in left
    assert made[-1].name in left


def test_version_roundtrip(tmp_path):
    store = AiDemoSessionStore(tmp_path)
    session = store.create()
    data = {"main": {"name": "練功"}, "return": None, "changes": "改了跳躍", "verdict": None}
    store.save_version(session, 2, data)
    assert store.load_version(session, 2) == data
    assert store.versions(session) == [2]


def test_timeline_saved(tmp_path):
    store = AiDemoSessionStore(tmp_path)
    session = store.create()
    store.save_timeline(session, {"start_dot": [1, 2]})
    assert (session / "timeline.json").read_text(encoding="utf-8").startswith("{")
