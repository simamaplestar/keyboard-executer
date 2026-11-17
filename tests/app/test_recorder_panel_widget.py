from keyboard_executor.app.recorder_panel import RecorderPanel
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.storage.scripts import ScriptStorage
from tests.fakes import FakeInputHook, FakeWindowManager


class SpySession:
    instances = []

    def __init__(self, hook, origin, *, mode="simplified", toggle_key="f9",
                 stop_key="f10", on_state=None, on_event=None):
        self.started = 0
        self.toggles = 0
        self.marked = 0
        self.mode = mode
        self.on_state = on_state
        self.on_event = on_event
        SpySession.instances.append(self)

    def start(self):
        self.started += 1

    def toggle(self):
        self.toggles += 1

    def mark_stop_button_pressed(self):
        self.marked += 1

    def finish(self):
        return []


def test_panel_constructs_and_toggle_reaches_session(qapp, tmp_path):
    wm = FakeWindowManager([WindowInfo(handle=object(), title="記事本",
                                       app_name="App", x=1, y=2, width=3,
                                       height=4, is_active=False)])
    panel = RecorderPanel(wm, ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    assert panel.window_combo.count() == 1
    panel.toggle_button.click()
    session = SpySession.instances[-1]
    assert session.started == 1 and session.toggles == 1


def test_stop_button_pressed_signal_marks_session_before_click_fires(qapp, tmp_path):
    """M4 最終審查：STOP 鈕的 pressed 訊號（早於 clicked）要先告知 session 忽略
    這次點擊本身的滑鼠事件。第一次按下（開始錄製）當下 session 尚未建立，
    應為 no-op；第二次按下（停止錄製）當下 session 已存在，應標記一次。"""
    wm = FakeWindowManager([WindowInfo(handle=object(), title="記事本",
                                       app_name="App", x=1, y=2, width=3,
                                       height=4, is_active=False)])
    panel = RecorderPanel(wm, ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    panel.toggle_button.click()          # 開始錄製：press 當下 session 尚未建立
    session = SpySession.instances[-1]
    assert session.marked == 0
    panel.toggle_button.click()          # 停止錄製：press 當下 session 已存在
    assert session.marked == 1


def test_recorder_panel_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.core.models import action_from_dict
    win = WindowInfo(handle=object(), title="記事本", app_name="App",
                     x=1, y=2, width=3, height=4, is_active=False)
    panel = RecorderPanel(FakeWindowManager([win]), ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    panel._win = win
    panel._actions = [action_from_dict({"type": "key_press", "key": "a"})]
    panel.name_edit.setText("錄我")
    panel._on_save_clicked()
    assert panel.result() == QDialog.DialogCode.Accepted         # 成功 → 關閉


def test_recorder_panel_stays_open_when_nothing_recorded(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    win = WindowInfo(handle=object(), title="記事本", app_name="App",
                     x=1, y=2, width=3, height=4, is_active=False)
    panel = RecorderPanel(FakeWindowManager([win]), ScriptStorage(tmp_path),
                          hook_factory=FakeInputHook, session_factory=SpySession)
    panel._on_save_clicked()                          # _actions 為 None → 無可儲存
    assert panel.result() != QDialog.DialogCode.Accepted         # 不關
    assert "沒有可儲存" in panel.status_label.text()


# --- 錄製中的即時按鍵浮動窗 ---

class SpyOverlay:
    def __init__(self, parent=None):
        self.pushed = []
        self.shown = 0
        self.hidden = 0

    def show_at_top(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def push(self, text):
        self.pushed.append(text)


def _panel_with_overlay(tmp_path, overlays):
    wm = FakeWindowManager([WindowInfo(handle=object(), title="記事本",
                                       app_name="App", x=1, y=2, width=3,
                                       height=4, is_active=False)])

    def factory(parent=None):
        overlay = SpyOverlay(parent)
        overlays.append(overlay)
        return overlay

    return RecorderPanel(wm, ScriptStorage(tmp_path), hook_factory=FakeInputHook,
                         session_factory=SpySession, overlay_factory=factory)


def test_overlay_shows_while_recording_and_hides_after(qapp, tmp_path):
    overlays = []
    panel = _panel_with_overlay(tmp_path, overlays)
    panel.toggle_button.click()
    panel._on_state("recording")
    assert overlays[0].shown == 1
    panel._on_state("done")
    assert overlays[0].hidden == 1


def test_recorded_events_reach_the_overlay(qapp, tmp_path):
    """session 的 on_event（listener 執行緒）→ signal → 浮動窗，只顯示會產生動作的事件。"""
    from keyboard_executor.platforms.base import EventKind, InputEvent

    overlays = []
    panel = _panel_with_overlay(tmp_path, overlays)
    panel.toggle_button.click()
    panel._on_state("recording")
    session = SpySession.instances[-1]

    session.on_event(InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=0, key="home"))
    session.on_event(InputEvent(kind=EventKind.KEY_UP, timestamp_ms=0, key="home"))
    session.on_event(InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=0, key="num7"))
    assert overlays[0].pushed == ["home", "num7"]   # KEY_UP 不顯示


def test_overlay_hidden_when_panel_closes(qapp, tmp_path):
    overlays = []
    panel = _panel_with_overlay(tmp_path, overlays)
    panel.toggle_button.click()
    panel._on_state("recording")
    panel.close()
    assert overlays[0].hidden >= 1
