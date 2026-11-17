from keyboard_executor.app.main_window import MainWindow
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.models import (
    ScriptValidationError,
    rule_from_dict,
    script_from_dict,
)
from keyboard_executor.core.player import PlayResult
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.scripts import ScriptStorage


class ImmediateWorker(Worker):
    """start() 即同步 run()：widget 測試不開真執行緒。"""

    def start(self):
        self.run()


class FakeRunController:
    def __init__(self, result=None):
        self._result = result if result is not None else PlayResult(ok=True, actions_run=1)
        self.stopped = 0

    def build_job(self, name):
        def job(progress):
            progress({"kind": "step", "index": 0, "total": 1,
                      "type": "key_press", "label": "按鍵 a"})
            return self._result
        return job

    def stop(self):
        self.stopped += 1


def make_window(tmp_path, controller=None):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    return MainWindow(tmp_path, permission_warnings=[],
                      run_controller=controller or FakeRunController(),
                      worker_factory=ImmediateWorker)


def test_double_click_script_opens_editor(qapp, tmp_path):
    window = make_window(tmp_path)
    calls = []
    window._on_edit_script = lambda: calls.append(True)   # 避開 exec() 阻塞
    window.script_list.itemDoubleClicked.emit(window.script_list.item(0))
    assert calls == [True]


def test_window_lists_scripts_from_storage(qapp, tmp_path):
    window = make_window(tmp_path)
    items = [window.script_list.item(i).text()
             for i in range(window.script_list.count())]
    assert items == ["甲"]


def test_main_window_can_shrink_and_scroll_on_small_screens(qapp, tmp_path):
    from PySide6.QtWidgets import QScrollArea

    window = make_window(tmp_path)
    assert isinstance(window.centralWidget(), QScrollArea)
    assert window.centralWidget().widgetResizable()
    assert window.minimumWidth() <= 420
    assert window.minimumHeight() <= 320
    window.resize(420, 320)
    window.show()
    qapp.processEvents()
    assert window._main_scroll.verticalScrollBar().maximum() > 0
    assert window._main_scroll.horizontalScrollBar().maximum() > 0
    window.close()


def test_script_list_shows_hotkey_suffix_and_selects_by_userrole(qapp, tmp_path):
    from PySide6.QtCore import Qt
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "settings": {"hotkey": "ctrl+shift+1"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=FakeRunController(), worker_factory=ImmediateWorker)
    item = window.script_list.item(0)
    assert item.text() == "甲   [Ctrl+Shift+1]"
    assert item.data(Qt.ItemDataRole.UserRole) == "甲"
    window.script_list.setCurrentRow(0)                 # 觸發 currentItemChanged
    assert window._scripts.selected == "甲"             # 用 UserRole 真名 select


def test_run_button_flow_appends_progress_and_result(qapp, tmp_path):
    window = make_window(tmp_path)
    window.script_list.setCurrentRow(0)          # currentItemChanged → select
    window.run_button.click()
    text = window.log_view.toPlainText()
    assert "開始回放：甲" in text
    assert "[1/1] 按鍵 a" in text
    assert "回放完成，共執行 1 個動作" in text
    assert window.run_button.isEnabled()          # 結束後恢復


def test_stop_button_reaches_controller(qapp, tmp_path):
    controller = FakeRunController()
    window = make_window(tmp_path, controller=controller)
    window.stop_button.click()
    assert controller.stopped == 1
    assert "已送出停止訊號" in window.log_view.toPlainText()


class FakeWatchController:
    def __init__(self):
        self.stopped = 0

    def build_job(self):
        def job(progress):
            progress({"kind": "fire", "rule": "斷線", "trigger": "notify"})
            return "已停止監看（1 條規則）"
        return job

    def stop(self):
        self.stopped += 1


def test_watch_buttons_start_watch_and_stop_reach_controller(qapp, tmp_path):
    controller = FakeWatchController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=FakeRunController(),
                        watch_controller=controller,
                        worker_factory=ImmediateWorker)
    window.watch_button.click()
    text = window.log_view.toPlainText()
    assert "開始監看" in text
    assert "規則「斷線」觸發（notify）" in text
    assert "已停止監看（1 條規則）" in text
    window.watch_stop_button.click()
    assert controller.stopped == 1


class SpyWorker:
    """closeEvent 測試用假 worker：只記錄 wait() 是否被呼叫（模擬仍在跑的 QThread）。"""

    def __init__(self):
        self.waited = 0

    def wait(self, timeout_ms=5000):
        self.waited += 1
        return True


def test_close_event_stops_controllers_and_waits_running_workers(qapp, tmp_path):
    """關窗時若回放/監看仍在跑，closeEvent 必須先送停止訊號並等背景執行緒真正
    結束，避免 teardown 時「QThread: Destroyed while thread is still running」
    與背景 worker 仍繼續送輸入。"""
    run_controller = FakeRunController()
    watch_controller = FakeWatchController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=run_controller,
                        watch_controller=watch_controller,
                        worker_factory=ImmediateWorker)
    run_worker = SpyWorker()
    watch_worker = SpyWorker()
    window._worker = run_worker
    window._watch_worker = watch_worker

    window.close()

    assert run_controller.stopped == 1
    assert watch_controller.stopped == 1
    assert run_worker.waited == 1
    assert watch_worker.waited == 1


def test_close_event_safe_when_nothing_running(qapp, tmp_path):
    """沒有任何 worker 在跑時關窗不得拋例外（_worker/_watch_worker 皆為 None）。"""
    window = make_window(tmp_path)
    window.close()   # 不得拋例外


def test_close_event_calls_ai_panel_shutdown(qapp, tmp_path):
    """I-1：關窗必須連 AI 助手的串流 worker 一併停下等待，否則 app 關閉時
    若 AI 正在串流中會留下「QThread: Destroyed while thread is still
    running」的 abort。"""
    window = make_window(tmp_path)
    calls = []
    window._ai_panel.shutdown = lambda: calls.append(True)
    window.close()
    assert calls == [True]


def test_open_settings_button_opens_first_missing_pane(qapp, tmp_path):
    opened = []
    checks = {"螢幕錄製": (lambda: False, "請授予螢幕錄製權限")}
    window = MainWindow(tmp_path, permission_warnings=["請授予螢幕錄製權限"],
                        permission_checks=checks, url_opener=opened.append)
    assert not window.open_settings_button.isHidden()
    window.open_settings_button.click()
    assert opened == ["x-apple.systempreferences:com.apple.preference.security"
                      "?Privacy_ScreenCapture"]
    window_ok = MainWindow(tmp_path, permission_warnings=[], permission_checks={})
    assert window_ok.open_settings_button.isHidden()


def _save_script(tmp_path, name):
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": name, "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))


def test_delete_script_button_confirmed_deletes_and_logs(qapp, tmp_path):
    _save_script(tmp_path, "甲")
    messages = []
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: messages.append(m) or True)
    window.script_list.setCurrentRow(0)   # currentItemChanged → 控制器 select("甲")
    window.script_delete_button.click()
    assert "甲" in messages[0]                       # 確認訊息含名稱
    assert ScriptStorage(tmp_path).list_names() == []
    assert window.script_list.count() == 0
    assert "已刪除腳本「甲」" in window.log_view.toPlainText()


def test_delete_script_cancelled_keeps_file(qapp, tmp_path):
    _save_script(tmp_path, "甲")
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: False)
    window.script_list.setCurrentRow(0)
    window.script_delete_button.click()
    assert ScriptStorage(tmp_path).list_names() == ["甲"]
    assert "已刪除" not in window.log_view.toPlainText()


def test_delete_rule_button_confirmed_deletes(qapp, tmp_path):
    RuleStorage(tmp_path).save(rule_from_dict({
        "name": "斷線", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "中斷", "mode": "contains"},
        "trigger": {"type": "stop_all"}}))
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: True)
    window.rule_list.setCurrentRow(0)
    window.rule_delete_button.click()
    assert RuleStorage(tmp_path).list_names() == []
    assert "已刪除規則「斷線」" in window.log_view.toPlainText()


def test_apply_settings_updates_snapshot_controllers_hotkey_and_labels(qapp, tmp_path):
    from keyboard_executor.app.settings import Settings

    class RecCtrl:
        def __init__(self):
            self.applied = None
        def apply_settings(self, **kw):
            self.applied = kw
        def stop(self):
            pass

    class FakeHotkey:
        def __init__(self):
            self.calls = []
        def unregister(self):
            self.calls.append("unreg")
        def register(self, key):
            self.calls.append(("reg", key))
            return True

    run_c, watch_c = RecCtrl(), RecCtrl()
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        run_controller=run_c, watch_controller=watch_c,
                        worker_factory=ImmediateWorker)
    window._global_hotkey = FakeHotkey()
    new = Settings(toggle_key="f7", stop_key="f8", ocr_language="en",
                   log_level="DEBUG",
                   discord_webhook_url="https://discord.com/api/webhooks/1/x")
    window._apply_settings(new)

    assert window._settings is new                              # 快照更新（日誌等級即時）
    assert run_c.applied["stop_key"] == "f8"
    assert watch_c.applied["discord_webhook_url"] == "https://discord.com/api/webhooks/1/x"
    assert window._global_hotkey.calls == ["unreg", ("reg", "f8")]  # 熱鍵重註冊
    assert "F8" in window._estop_label.text()                  # 標籤刷新
    assert "F7" in window.record_button.toolTip()


def test_reregister_restarts_poller_even_when_hotkey_none(qapp, tmp_path):
    """RegisterHotKey 註冊失敗（_global_hotkey 為 None，例如熱鍵被占用）時，
    輪詢器仍須獨立隨設定更新到新鍵，不可被早退路徑擋住。"""
    class _FakePoller:
        def __init__(self):
            self.started_with = None
            self.stopped = 0
        def stop(self):
            self.stopped += 1
        def start(self, key):
            self.started_with = key
            return True

    window = make_window(tmp_path)
    fp = _FakePoller()
    window._key_poller = fp
    window._global_hotkey = None          # 模擬 RegisterHotKey 註冊失敗
    window._reregister_hotkey("f8")
    assert fp.stopped == 1 and fp.started_with == "f8"   # 輪詢器仍更新到新鍵


def test_apply_settings_relevels_logging_subsystem(qapp, tmp_path):
    import logging
    from keyboard_executor.app.settings import Settings
    from keyboard_executor.core.logging_config import PACKAGE_LOGGER

    class RecCtrl:
        def apply_settings(self, **kw):
            pass
        def stop(self):
            pass

    class RecHandler:
        def __init__(self):
            self.level = None
        def setLevel(self, lvl):
            self.level = lvl

    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        run_controller=RecCtrl(), watch_controller=RecCtrl(),
                        worker_factory=ImmediateWorker)
    window.gui_log_handler = RecHandler()
    prev = logging.getLogger(PACKAGE_LOGGER).level
    try:
        window._apply_settings(Settings(log_level="DEBUG"))
        assert logging.getLogger(PACKAGE_LOGGER).level == logging.DEBUG   # 套件 logger 重定級
        assert window.gui_log_handler.level == "DEBUG"                    # GUI handler 重定級
    finally:
        logging.getLogger(PACKAGE_LOGGER).setLevel(prev)   # 還原，避免污染其他測試


def test_emergency_signal_stops_only_run_not_watch(qapp, tmp_path):
    run = FakeRunController()
    watch = FakeWatchController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=run, watch_controller=watch)
    window.emergency_stop_requested.emit()      # 同執行緒 → 同步呼叫 _on_emergency_hotkey
    assert run.stopped == 1 and watch.stopped == 0   # 只停回放，監看不動


def test_duplicate_script_button_creates_copy(qapp, tmp_path):
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    window = make_window(tmp_path)
    window.script_list.setCurrentRow(0)          # 選「甲」
    window.script_duplicate_button.click()
    assert ScriptStorage(tmp_path).list_names() == ["甲", "甲 - 複製"]
    assert window.script_list.count() == 2


def test_duplicate_rule_button_creates_copy(qapp, tmp_path):
    RuleStorage(tmp_path).save(rule_from_dict({
        "name": "甲", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "x"},
        "triggers": [{"type": "notify", "message": "m"}]}))
    window = make_window(tmp_path)
    window.rule_list.setCurrentRow(0)
    window.rule_duplicate_button.click()
    assert RuleStorage(tmp_path).list_names() == ["甲", "甲 - 複製"]


class RunningWorker:
    """模擬仍在跑的 worker：只需 wait()（_cleanup_worker 用 getattr 守門其餘訊號）。"""

    def __init__(self):
        self.waited = 0

    def wait(self, timeout_ms=5000):
        self.waited += 1
        return True


def test_hotkey_signal_runs_named_script(qapp, tmp_path):
    window = make_window(tmp_path)                 # storage 內有「甲」
    window.script_hotkey_requested.emit("甲")
    assert "開始回放：甲" in window.log_view.toPlainText()


def test_run_script_stops_running_worker_before_new_run(qapp, tmp_path):
    controller = FakeRunController()
    window = make_window(tmp_path, controller=controller)
    running = RunningWorker()
    window._worker = running                        # 模擬有腳本正在跑
    window._run_script("甲")
    assert controller.stopped == 1                  # 先送停止
    assert running.waited == 1                      # 等舊 worker 結束
    assert "開始回放：甲" in window.log_view.toPlainText()   # 再跑新的


def test_stale_worker_finished_is_ignored_after_switch(qapp, tmp_path):
    from PySide6.QtCore import QObject, Signal

    class MiniEmitter(QObject):
        finished = Signal(object)

    window = make_window(tmp_path)
    old = MiniEmitter()
    old.finished.connect(window._on_run_finished)
    current = RunningWorker()                 # 現任 worker（非 old）
    window._worker = current
    window.run_button.setEnabled(False)
    old.finished.emit(PlayResult(ok=True, actions_run=1))   # 舊 worker 殘留訊號，sender=old
    assert current.waited == 0                # 現任 worker 未被 _cleanup_worker wait
    assert not window.run_button.isEnabled()  # 按鈕狀態未被舊訊號改動


class OrderRecordingController:
    """記錄 build_job / stop 的呼叫順序（模擬 RunController：build_job 會覆寫
    stop_event，故 stop 必須在 build_job 之前才停得到舊 job）。"""

    def __init__(self):
        self.order = []

    def build_job(self, name):
        self.order.append("build")

        def job(progress):
            return PlayResult(ok=True, actions_run=1)
        return job

    def stop(self):
        self.order.append("stop")


def test_run_script_stops_running_worker_before_building_new_job(qapp, tmp_path):
    controller = OrderRecordingController()
    window = make_window(tmp_path, controller=controller)
    window._worker = RunningWorker()          # 模擬有舊腳本在跑
    window._run_script("甲")
    assert controller.order == ["stop", "build"]   # 先停舊的、再 build 新的


class RaisingRunController:
    """build_job 一律拋 ScriptValidationError（模擬熱鍵綁定後腳本檔損毀/被刪）。"""

    def __init__(self):
        self.stopped = 0

    def build_job(self, name):
        raise ScriptValidationError("壞掉的腳本")

    def stop(self):
        self.stopped += 1


def test_run_script_reenables_button_when_new_script_fails_to_load(qapp, tmp_path):
    controller = RaisingRunController()
    window = make_window(tmp_path, controller=controller)
    window.run_button.setEnabled(False)      # 模擬舊腳本正在跑（按鈕停用中）
    window._worker = RunningWorker()
    window._run_script("甲")
    assert controller.stopped == 1            # 舊的有被停
    assert window.run_button.isEnabled()      # 載入失敗後按鈕恢復（不卡死）
    assert "腳本載入失敗" in window.log_view.toPlainText()


def test_build_script_bindings_dedup_and_skips(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)

    def save(name, hotkey):
        storage.save(script_from_dict({
            "name": name, "target_window": {"title_pattern": "x"},
            "settings": {"hotkey": hotkey},
            "actions": [{"type": "key_press", "key": "a"}]}))

    save("s1_ctrl_a", "ctrl+a")     # 排序在前 → 拿走 ctrl+a
    save("s2_ctrl_a", "ctrl+a")     # 與 s1 同鍵 → 去重略過
    save("s3_stopkey", "f10")       # == 緊急停止鍵（預設 f10）→ 略過
    save("s4_ok", "f6")             # OK
    save("s5_none", "")             # 無熱鍵 → 略過
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=FakeRunController(),
                        worker_factory=ImmediateWorker)
    bindings = dict(window._build_script_bindings())
    assert "s1_ctrl_a" in bindings and "s2_ctrl_a" not in bindings
    assert "s3_stopkey" not in bindings
    assert "s4_ok" in bindings
    assert "s5_none" not in bindings
    assert bindings["s1_ctrl_a"] == [0x11, ord("A")]


def test_ai_dock_hidden_by_default_and_toggles(qapp, tmp_path):
    window = make_window(tmp_path)
    assert window._ai_dock.isHidden()
    window.ai_button.click()
    assert not window._ai_dock.isHidden()
    window.ai_button.click()
    assert window._ai_dock.isHidden()


def test_ai_dock_custom_titlebar_close_hides_dock(qapp, tmp_path):
    """自訂標題列取代原生的浮動/關閉鈕，收合鈕要等同 ai_button 的切換。"""
    window = make_window(tmp_path)
    window.ai_button.click()
    assert not window._ai_dock.isHidden()
    assert window._ai_dock.titleBarWidget() is not None
    window.ai_close_button.click()
    assert window._ai_dock.isHidden()


def test_ai_titlebar_height_matches_main_titlebar(qapp, tmp_path):
    """dock 貼在主標題列右側，兩者底線要切齊，否則視窗頂端出現錯位階梯。"""
    window = make_window(tmp_path)
    assert (window._ai_dock.titleBarWidget().height()
            == window._titlebar.sizeHint().height())


def test_ai_panel_scripts_changed_refreshes_list(qapp, tmp_path):
    from PySide6.QtCore import Qt

    window = make_window(tmp_path)
    window._script_storage.save(script_from_dict({
        "name": "AI新增", "target_window": {"title_pattern": "t"},
        "actions": [{"type": "delay", "ms": 1}]}))
    window._ai_panel.scripts_changed.emit()
    names = [window.script_list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(window.script_list.count())]
    assert "AI新增" in names


def test_ai_privacy_ack_persists_via_callback(qapp, tmp_path):
    window = make_window(tmp_path)
    window._ack_ai_privacy()
    assert window._settings.ai_privacy_ack is True


def test_titlebar_has_transfer_entry(qapp, tmp_path):
    """匯出／匯入是跨腳本與規則的全域操作，入口放標題列。"""
    window = make_window(tmp_path)
    assert window.transfer_button.text() == "匯出／匯入"
    assert window.transfer_button.toolTip()


def test_transfer_dialog_opens_and_lists_refresh_after(qapp, tmp_path, monkeypatch):
    """對話框關閉後兩份清單都要重讀——匯入可能同時動到腳本與規則。"""
    window = make_window(tmp_path)
    opened = []
    refreshed = []

    class FakeDialog:
        def __init__(self, scripts, rules, templates, parent=None):
            opened.append((scripts, rules, templates))

        def exec(self):
            return 0

    monkeypatch.setattr("keyboard_executor.app.transfer_dialog.TransferDialog",
                        FakeDialog)
    monkeypatch.setattr(window, "refresh_scripts", lambda: refreshed.append("scripts"))
    monkeypatch.setattr(window, "refresh_rules", lambda: refreshed.append("rules"))
    window.transfer_button.click()
    assert len(opened) == 1
    assert refreshed == ["scripts", "rules"]


class FakeDemoController:
    """AI 示範控制器替身：只有 MainWindow 會用到的訊號與方法。"""
    def __new__(cls):
        from PySide6.QtCore import QObject, Signal

        class _C(QObject):
            progress = Signal(dict)
            finished = Signal(object)
            reset_needed = Signal(str)
            active_changed = Signal(bool)
            scripts_changed = Signal()

            def __init__(self):
                super().__init__()
                self.active = False
                self.interrupts, self.stops, self.shutdowns = [], 0, 0
                self.busy = []
                self.session = None

            def interrupt(self, reason):
                self.interrupts.append(reason)

            def set_external_busy(self, busy):
                self.busy.append(busy)

            def stop(self):
                self.stops += 1

            def shutdown(self):
                self.shutdowns += 1

        return _C()


def make_demo_window(tmp_path, controller=None):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    demo = FakeDemoController()
    window = MainWindow(tmp_path, permission_warnings=[],
                        run_controller=controller or FakeRunController(),
                        worker_factory=ImmediateWorker, demo_controller=demo)
    return window, demo


def test_run_button_disabled_while_demo_active(qapp, tmp_path):
    window, demo = make_demo_window(tmp_path)
    demo.active = True
    demo.active_changed.emit(True)
    assert not window.run_button.isEnabled()
    window._run_script("甲")                      # 腳本快捷鍵走同一條路
    assert "開始回放" not in window.log_view.toPlainText()
    assert "AI 示範試跑中" in window.log_view.toPlainText()
    demo.active = False
    demo.active_changed.emit(False)
    assert window.run_button.isEnabled()


def test_rule_fire_interrupts_demo(qapp, tmp_path):
    window, demo = make_demo_window(tmp_path)
    demo.active = True
    window._on_progress({"kind": "fire", "rule": "通知", "trigger": "notify"})
    assert demo.interrupts == []                 # 只發通知不會動到角色
    window._on_progress({"kind": "fire", "rule": "測謊", "trigger": "notify+run_script"})
    assert demo.interrupts == ["規則「測謊」觸發"]
    assert demo.busy == [True]                   # 規則的腳本跑完前試跑要等
    window._on_progress({"kind": "fire_done", "rule": "測謊"})
    assert demo.busy == [True, False]
    demo.active = False
    window._on_progress({"kind": "fire", "rule": "測謊", "trigger": "run_script"})
    assert len(demo.interrupts) == 1


def test_rule_stop_all_stops_demo(qapp, tmp_path):
    controller = FakeRunController()
    window, demo = make_demo_window(tmp_path, controller=controller)
    window._on_rule_stop_all()                   # WatchController 的 on_stop_all
    assert controller.stopped == 1
    assert demo.stops == 1


def test_emergency_hotkey_stops_demo(qapp, tmp_path):
    window, demo = make_demo_window(tmp_path)
    window._on_emergency_hotkey()
    assert demo.stops == 1


def test_demo_scripts_changed_refreshes_list(qapp, tmp_path):
    window, demo = make_demo_window(tmp_path)
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": "乙", "target_window": {"title_pattern": "x"},
        "actions": [{"type": "key_press", "key": "b"}]}))
    demo.scripts_changed.emit()
    names = [window.script_list.item(i).text() for i in range(window.script_list.count())]
    assert "乙" in names


def test_open_demo_refused_while_script_running(qapp, tmp_path):
    window, demo = make_demo_window(tmp_path)
    window._worker = object()                     # 有腳本正在跑
    try:
        window._on_open_demo()
    finally:
        window._worker = None
    assert "請先停止" in window.log_view.toPlainText()


# ---- 自動更新 ----

class FakeUpdater:
    def __init__(self, exe):
        from PySide6.QtCore import QObject, Signal

        class _Sigs(QObject):
            update_ready = Signal(object)
            manual_update_needed = Signal(str)
            check_finished = Signal(str)
        self._sigs = _Sigs()
        self.update_ready = self._sigs.update_ready
        self.manual_update_needed = self._sigs.manual_update_needed
        self.check_finished = self._sigs.check_finished
        self.exe = exe
        self.enabled = True
        self.postponed = 0
        self.started = 0
        self.shut = 0
        self.failed = []
        self.replaced = False

    def exe_replaced(self):
        return self.replaced

    def install_failed(self, version):
        self.failed.append(version)

    def start(self):
        self.started += 1

    def postpone(self):
        self.postponed += 1

    def shutdown(self):
        self.shut += 1


def update_window(tmp_path, *, accept=True):
    from keyboard_executor.core.update.download import staged_path, version_marker
    exe = tmp_path / "bin" / "KE.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"old")
    staged_path(exe).write_bytes(b"new")
    version_marker(exe).write_text("0.6.0", encoding="utf-8")
    updater = FakeUpdater(exe)
    window = MainWindow(tmp_path, permission_warnings=[], run_controller=FakeRunController(),
                        worker_factory=ImmediateWorker, update_controller=updater)
    calls = {"popen": [], "quit": 0, "errors": [], "asked": []}
    window._confirm_update = lambda info: calls["asked"].append(info) or accept
    window._popen = lambda cmd, env: calls["popen"].append((cmd, env))
    window._quit = lambda: calls.__setitem__("quit", calls["quit"] + 1)
    window._show_update_error = lambda text: calls["errors"].append(text)
    return window, updater, exe, calls



def _info():
    from keyboard_executor.core.update.release import ReleaseInfo
    return ReleaseInfo("0.6.0", "修正", "https://x/e", 3, "https://x/s")


def test_updater_started_on_construction(qapp, tmp_path):
    window, updater, _exe, _calls = update_window(tmp_path)
    assert updater.started == 1


def test_is_busy_reflects_worker_watch_demo(qapp, tmp_path):
    window, *_ = update_window(tmp_path)
    assert window.is_busy() is False
    window._worker = object()
    assert window.is_busy() is True
    window._worker = None
    window._watch_worker = object()
    assert window.is_busy() is True
    window._watch_worker = None
    window._demo._worker = object()
    assert window.is_busy() is True
    window._demo._worker = None


def test_update_ready_accept_installs_and_restarts(qapp, tmp_path):
    window, updater, exe, calls = update_window(tmp_path)
    updater.update_ready.emit(_info())
    assert calls["asked"][0].version == "0.6.0"
    assert exe.read_bytes() == b"new"
    cmd, env = calls["popen"][0]
    assert cmd[0] == str(exe)
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert calls["quit"] == 1


def test_update_ready_later_postpones(qapp, tmp_path):
    window, updater, exe, calls = update_window(tmp_path, accept=False)
    updater.update_ready.emit(_info())
    assert updater.postponed == 1
    assert exe.read_bytes() == b"old"
    assert calls["popen"] == [] and calls["quit"] == 0


def test_install_failure_shows_error_and_keeps_running(qapp, tmp_path):
    from keyboard_executor.core.update.download import staged_path
    window, updater, exe, calls = update_window(tmp_path)
    staged_path(exe).unlink()                     # 新版檔案不見 → install 失敗
    updater.update_ready.emit(_info())
    assert "舊版仍可正常使用" in calls["errors"][0]
    assert calls["quit"] == 0 and calls["popen"] == []
    assert exe.read_bytes() == b"old"
    assert updater.failed == ["0.6.0"]


def test_restart_failure_still_quits_with_message(qapp, tmp_path):
    window, updater, exe, calls = update_window(tmp_path)

    def boom(cmd, env):
        raise OSError("blocked")
    window._popen = boom
    updater.update_ready.emit(_info())
    assert "手動" in calls["errors"][0]
    assert calls["quit"] == 1


def test_manual_update_needed_opens_page(qapp, tmp_path):
    window, updater, exe, calls = update_window(tmp_path)
    opened = []
    window._url_opener = opened.append
    window._confirm_manual_update = lambda url: True
    updater.manual_update_needed.emit("https://example/releases")
    assert opened == ["https://example/releases"]


def test_close_shuts_down_updater(qapp, tmp_path):
    window, updater, *_ = update_window(tmp_path)
    window.close()
    assert updater.shut == 1


def test_default_window_has_disabled_updater(qapp, tmp_path):
    window = make_window(tmp_path)
    assert window._updater.enabled is False


def test_busy_after_confirm_postpones(qapp, tmp_path):
    window, updater, exe, calls = update_window(tmp_path)

    def confirm(info):
        window._worker = object()              # 對話框開著時熱鍵啟動了腳本
        return True
    window._confirm_update = confirm
    updater.update_ready.emit(_info())
    window._worker = None
    assert exe.read_bytes() == b"old"
    assert calls["quit"] == 0 and updater.postponed == 1


def test_exe_replaced_restarts_without_install(qapp, tmp_path):
    from keyboard_executor.core.update.download import staged_path
    window, updater, exe, calls = update_window(tmp_path)
    staged_path(exe).unlink()
    exe.write_bytes(b"installed-by-other")
    updater.replaced = True
    updater.update_ready.emit(_info())
    assert calls["errors"] == []
    assert calls["popen"][0][0][0] == str(exe)
    assert calls["quit"] == 1


def test_window_title_has_no_version(qapp, tmp_path):
    window = make_window(tmp_path)   # 版本號只顯示在頂部標籤（使用者要求標題不寫版本）
    assert window.windowTitle() == "Keyboard Executor"


def test_header_badge_shows_current_version(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel
    from keyboard_executor import __version__
    window = make_window(tmp_path)
    badge = window.findChild(QLabel, "ver")
    assert badge is not None and badge.text() == f"v{__version__}"


def test_settings_dialog_does_not_block_update_prompt(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.app.settings_page import SettingsPage
    window, *_ = update_window(tmp_path)
    page = SettingsPage(SettingsStore(tmp_path), permission_checks={}, parent=window)
    page.open()                                   # 非阻塞的 modal
    assert qapp.activeModalWidget() is page
    assert window.is_busy() is False              # 設定頁開著不算忙（使用者正在按檢查更新）
    page.close()
    other = QDialog(window)
    other.open()
    assert window.is_busy() is True               # 其他對話框（錄製、編輯）仍算忙
    other.close()
