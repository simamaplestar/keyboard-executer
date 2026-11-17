from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import TAP_HOLD_MS, Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window():
    return WindowInfo(handle=object(), title="記事本", app_name="App",
                      x=0, y=0, width=100, height=100, is_active=False)


class CloseAfterFirstKey(FakeInputBackend):
    """第一個 key_press 執行後把視窗關閉。"""

    def __init__(self, manager):
        super().__init__()
        self._manager = manager

    def key_press(self, key, hold_ms=0):
        super().key_press(key, hold_ms)
        self._manager.windows = []


def make_setup():
    manager = FakeWindowManager([make_window()])
    backend = CloseAfterFirstKey(manager)
    platform = Platform(input_backend=backend, window_manager=manager)
    return platform, backend


def make_script(actions):
    return script_from_dict({
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    })


def test_key_press_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "key_press", "key": "b"},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert result.actions_run == 1
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]  # b 沒有送出


def test_key_combo_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "key_combo", "keys": ["ctrl", "s"]},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]


def test_text_input_aborts_after_window_closes():
    platform, backend = make_setup()
    script = make_script([
        {"type": "key_press", "key": "a"},
        {"type": "text_input", "text": "不該出現"},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert backend.calls == [("key_press", "a", TAP_HOLD_MS)]
