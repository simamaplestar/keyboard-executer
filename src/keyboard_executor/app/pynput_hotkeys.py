"""以現有輸入 hook 處理 macOS 腳本啟動熱鍵；回呼由主視窗轉為 Qt signal。"""
from __future__ import annotations

from threading import RLock

from keyboard_executor.platforms.base import EventKind
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook


class PynputScriptHotkeys:
    def __init__(self, on_trigger, *, hook_factory=PynputInputHook):
        self._on_trigger = on_trigger
        self._hook_factory = hook_factory
        self._hook = None
        self._bindings = []
        self._pressed = set()
        self._active = set()
        self._generation = 0
        self._lock = RLock()

    def start(self, bindings: list[tuple[str, list[str]]]) -> None:
        self.stop()
        if not bindings:
            return
        with self._lock:
            self._bindings = [(name, frozenset(keys)) for name, keys in bindings if keys]
            self._hook = self._hook_factory()
            generation = self._generation
        try:
            self._hook.start(lambda event: self._on_event(event, generation))
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            hook, self._hook = self._hook, None
            self._bindings = []
            self._pressed.clear()
            self._active.clear()
        if hook is not None:
            hook.stop()

    def _on_event(self, event, generation) -> None:
        with self._lock:
            if self._hook is None or generation != self._generation or event.key is None:
                return
            if event.kind == EventKind.KEY_UP:
                self._pressed.discard(event.key)
                self._active = {name for name, keys in self._bindings
                                if keys <= self._pressed and name in self._active}
            elif event.kind == EventKind.KEY_DOWN and event.key not in self._pressed:
                self._pressed.add(event.key)
                for name, keys in self._bindings:
                    if keys <= self._pressed and name not in self._active:
                        self._active.add(name)
                        self._on_trigger(name)
