from keyboard_executor.app.script_hotkey_poller import ScriptHotkeyPoller


def test_start_false_when_no_bindings():
    p = ScriptHotkeyPoller(lambda name: None,
                           key_down_fn=lambda vk: False, sleep=lambda s: None)
    assert p.start([]) is False
    assert p._thread is None


def test_fires_name_once_per_rising_edge_not_while_held():
    fired = []
    states = iter([False, False, True, True, False, True])  # 上升緣在 index 2、5
    poller = None
    n = {"i": 0}

    def key_down_fn(vk):
        return next(states)

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 6:
            poller.stop()   # 從輪詢執行緒自身呼叫 → 不得自我 join

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    assert poller.start([("甲", [0x41])]) is True
    poller._thread.join(timeout=2)
    assert fired == ["甲", "甲"]     # 兩次上升緣各一次；按著不放不重複


def test_combo_fires_only_when_all_keys_down():
    fired = []
    rounds = [
        {0x11: True, 0x41: False},   # ctrl 下、a 未下 → 不觸發
        {0x11: True, 0x41: True},    # 兩鍵皆下 → 上升緣觸發一次
        {0x11: True, 0x41: True},    # 仍皆下 → 不重複
    ]
    idx = {"r": 0}
    poller = None

    def key_down_fn(vk):
        return rounds[idx["r"]].get(vk, False)

    def fake_sleep(_):
        idx["r"] += 1
        if idx["r"] >= len(rounds):
            poller.stop()
            idx["r"] = len(rounds) - 1     # 防越界

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    poller.start([("組", [0x11, 0x41])])
    poller._thread.join(timeout=2)
    assert fired == ["組"]


def test_multiple_bindings_independent():
    fired = []
    rounds = [
        {0x41: True, 0x42: False},   # 只有甲(a)上升 → fire 甲
        {0x41: True, 0x42: True},    # 乙(b)上升 → fire 乙（甲維持按著不重複）
    ]
    idx = {"r": 0}
    poller = None

    def key_down_fn(vk):
        return rounds[idx["r"]].get(vk, False)

    def fake_sleep(_):
        idx["r"] += 1
        if idx["r"] >= len(rounds):
            poller.stop()
            idx["r"] = len(rounds) - 1

    poller = ScriptHotkeyPoller(lambda name: fired.append(name),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    poller.start([("甲", [0x41]), ("乙", [0x42])])
    poller._thread.join(timeout=2)
    assert fired == ["甲", "乙"]
