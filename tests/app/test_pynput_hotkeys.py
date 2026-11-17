from keyboard_executor.platforms.base import EventKind, InputEvent


class Hook:
    def __init__(self):
        self.callback = None
        self.stopped = False

    def start(self, callback):
        self.callback = callback

    def stop(self):
        self.stopped = True

    def send(self, kind, key):
        self.callback(InputEvent(kind, 0, key=key))


def test_mac_hotkey_fires_once_until_key_is_released():
    from keyboard_executor.app.pynput_hotkeys import PynputScriptHotkeys
    fired = []
    hook = Hook()
    hotkeys = PynputScriptHotkeys(fired.append, hook_factory=lambda: hook)
    hotkeys.start([("甲", ["cmd", "f5"])])
    hook.send(EventKind.KEY_DOWN, "cmd")
    hook.send(EventKind.KEY_DOWN, "f5")
    hook.send(EventKind.KEY_DOWN, "f5")
    assert fired == ["甲"]
    hook.send(EventKind.KEY_UP, "f5")
    hook.send(EventKind.KEY_DOWN, "f5")
    assert fired == ["甲", "甲"]
    hotkeys.stop()
    hook.send(EventKind.KEY_UP, "f5")
    hook.send(EventKind.KEY_DOWN, "f5")
    assert fired == ["甲", "甲"]
    assert hook.stopped


def test_mac_hotkeys_restart_replaces_bindings_and_clears_pressed_keys():
    from keyboard_executor.app.pynput_hotkeys import PynputScriptHotkeys
    hooks = []
    def new_hook():
        hook = Hook()
        hooks.append(hook)
        return hook
    fired = []
    hotkeys = PynputScriptHotkeys(fired.append, hook_factory=new_hook)
    hotkeys.start([("舊", ["f5"])])
    hooks[0].send(EventKind.KEY_DOWN, "f5")
    hotkeys.start([("新", ["f6"])])
    assert hooks[0].stopped
    hooks[1].send(EventKind.KEY_DOWN, "f5")
    hooks[1].send(EventKind.KEY_DOWN, "f6")
    assert fired == ["舊", "新"]
    hotkeys.stop()
    hotkeys.stop()


def test_mac_binding_builder_filters_stop_key_duplicates_and_bad_scripts(qapp, tmp_path):
    from keyboard_executor.app.main_window import MainWindow
    from keyboard_executor.core.models import script_from_dict
    from keyboard_executor.storage.scripts import ScriptStorage
    storage = ScriptStorage(tmp_path)
    for name, hotkey in [("a", "cmd+f5"), ("b", "super+f5"), ("c", "ctrl+f10"),
                         ("d", "f6"), ("e", "")]:
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "TextEdit"},
            "settings": {"hotkey": hotkey},
            "actions": [{"type": "key_press", "key": "a"}]}))
    window = MainWindow(tmp_path)
    try:
        assert window._build_darwin_script_bindings() == [
            ("a", ["cmd", "f5"]), ("d", ["f6"])]
    finally:
        window.close()
