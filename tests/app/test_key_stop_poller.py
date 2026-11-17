from keyboard_executor.app.key_stop_poller import AsyncKeyStopPoller


def test_start_returns_false_for_unknown_key():
    p = AsyncKeyStopPoller(lambda: None, key_down_fn=lambda vk: False,
                           sleep=lambda s: None)
    assert p.start("這不是鍵名") is False
    assert p._thread is None


def test_fires_once_per_rising_edge_not_while_held():
    triggers = []
    states = iter([False, False, True, True, False, True])  # 上升緣在 index 2、5
    poller = None
    n = {"i": 0}

    def key_down_fn(vk):
        return next(states)

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 6:
            poller.stop()

    poller = AsyncKeyStopPoller(lambda: triggers.append(1),
                               key_down_fn=key_down_fn, sleep=fake_sleep)
    assert poller.start("f10") is True
    poller._thread.join(timeout=2)
    assert len(triggers) == 2      # 兩次上升緣各一次；按著不放不重複


def test_no_fire_when_key_never_down():
    triggers = []
    poller = None
    n = {"i": 0}

    def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 3:
            poller.stop()

    poller = AsyncKeyStopPoller(lambda: triggers.append(1),
                               key_down_fn=lambda vk: False, sleep=fake_sleep)
    poller.start("f10")
    poller._thread.join(timeout=2)
    assert triggers == []
