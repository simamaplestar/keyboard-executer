from keyboard_executor.app.application import (
    build_app,
    collect_permission_warnings,
    request_missing_permissions,
    settings_urls_for_missing,
)


def failing_checks():
    return {"螢幕錄製": (lambda: False, "請授予螢幕錄製權限"),
            "輔助使用": (lambda: True, "請授予輔助使用權限")}


def test_collect_permission_warnings_returns_failing_guides():
    assert collect_permission_warnings(failing_checks()) == ["請授予螢幕錄製權限"]
    assert collect_permission_warnings({}) == []


def test_collect_permission_warnings_exception_counts_as_missing():
    def boom():
        raise RuntimeError("preflight 失敗")

    warnings = collect_permission_warnings({"輸入監控": (boom, "請授予輸入監控權限")})
    assert warnings == ["請授予輸入監控權限"]


def test_build_app_constructs_window_with_title(qapp, tmp_path):
    app, window = build_app(data_dir=tmp_path, permission_checks={},
                            request_permissions=lambda: None)
    assert app is qapp                       # 重用既有 QApplication
    assert "Keyboard Executor" in window.windowTitle()


def test_main_window_has_core_panels(qapp, tmp_path):
    _, window = build_app(data_dir=tmp_path, permission_checks={},
                          request_permissions=lambda: None)
    for attr in ("permission_banner", "script_list", "rule_list", "summary_label",
                 "run_button", "stop_button", "watch_button", "watch_stop_button",
                 "record_button", "edit_button", "rule_edit_button",
                 "settings_button", "log_view"):
        assert hasattr(window, attr), f"MainWindow 缺少 {attr}"
    assert window.log_view.isReadOnly()


def test_permission_banner_visible_with_warnings(qapp, tmp_path):
    _, window = build_app(data_dir=tmp_path, permission_checks=failing_checks(),
                          request_permissions=lambda: None)
    assert not window.permission_banner.isHidden()
    assert "螢幕錄製" in window.permission_banner.text()


def test_permission_banner_hidden_without_warnings(qapp, tmp_path):
    _, window = build_app(data_dir=tmp_path, permission_checks={},
                          request_permissions=lambda: None)
    assert window.permission_banner.isHidden()


def test_build_app_sets_up_logging_in_data_dir(qapp, tmp_path):
    build_app(data_dir=tmp_path, permission_checks={},
             request_permissions=lambda: None)
    assert (tmp_path / "logs" / "app.log").exists()


def test_build_app_bridges_logger_records_to_log_view(qapp, tmp_path):
    import logging

    _, window = build_app(data_dir=tmp_path, permission_checks={},
                          request_permissions=lambda: None)
    logging.getLogger("keyboard_executor.core.rule_engine").error("規則甲觸發失敗")
    qapp.processEvents()
    assert "規則甲觸發失敗" in window.log_view.toPlainText()


def test_request_missing_permissions_calls_all_requesters():
    calls = []
    request_missing_permissions(requesters=(lambda: calls.append("a") or True,
                                            lambda: calls.append("b") or True))
    assert calls == ["a", "b"]


def test_mac_startup_requests_all_three_permissions(monkeypatch):
    from keyboard_executor.app import application
    from keyboard_executor.platforms.darwin import permissions
    calls = []
    monkeypatch.setattr(application.sys, "platform", "darwin")
    for name in ("accessibility", "screen_recording", "input_monitoring"):
        monkeypatch.setattr(permissions, f"request_{name}", lambda name=name: calls.append(name),
                            raising=False)
    application.request_missing_permissions()
    assert calls == ["accessibility", "screen_recording", "input_monitoring"]


def test_request_missing_permissions_swallows_requester_exceptions():
    calls = []

    def boom():
        raise RuntimeError("原生呼叫失敗")

    request_missing_permissions(requesters=(boom, lambda: calls.append("b")))
    assert calls == ["b"]   # 前一個失敗不阻斷後續請求（spec §10 啟動不崩潰）


def test_settings_urls_for_missing_maps_panes():
    checks = {"螢幕錄製": (lambda: False, "guide"),
              "輔助使用": (lambda: True, "guide"),
              "輸入監控": (lambda: False, "guide"),
              "未知權限": (lambda: False, "guide")}
    assert settings_urls_for_missing(checks) == [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    ]


def test_build_app_requests_permissions_on_startup(qapp, tmp_path):
    calls = []
    build_app(data_dir=tmp_path, permission_checks={},
              request_permissions=lambda: calls.append(1))
    assert calls == [1]


def test_default_update_exe_only_when_frozen_windows(monkeypatch):
    import sys
    from pathlib import Path
    from keyboard_executor.app.application import default_update_exe
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert default_update_exe() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "C:/apps/KE.exe")
    assert default_update_exe() == Path("C:/apps/KE.exe")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert default_update_exe() is None


def test_build_app_not_frozen_has_disabled_updater(qapp, tmp_path):
    _, window = build_app(data_dir=tmp_path, permission_checks={},
                          request_permissions=lambda: None)
    assert window._updater.enabled is False


def test_build_app_frozen_keeps_old_exe_at_startup(qapp, tmp_path, monkeypatch):
    from keyboard_executor.app import application
    exe = tmp_path / "bin" / "KE.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    (exe.parent / "KE.exe.old").write_bytes(b"old")
    monkeypatch.setattr(application, "default_update_exe", lambda: exe)
    _, window = build_app(data_dir=tmp_path / "data", permission_checks={},
                          request_permissions=lambda: None)
    assert (exe.parent / "KE.exe.old").exists()   # 啟動不立刻刪：新版跑穩才刪
    assert window._updater.enabled is True
    window._updater.shutdown()


def test_self_test_flag_runs_self_test(monkeypatch):
    from keyboard_executor import gui
    from keyboard_executor.app import self_test
    called = []
    monkeypatch.setattr(self_test, "run_self_test", lambda: called.append(True) or 0)
    assert gui.main(["--self-test"]) == 0
    assert called == [True]


def test_run_self_test_success_and_failure(qapp, capsys):
    from keyboard_executor.app.self_test import run_self_test
    seen = []
    assert run_self_test(build=lambda data_dir: seen.append(data_dir) or (qapp, _Closable()),
                         load_ocr=lambda: None, modules=("json",)) == 0
    assert seen
    def boom():
        raise FileNotFoundError("OCR 模型不存在")
    assert run_self_test(build=lambda data_dir: (qapp, _Closable()), load_ocr=boom,
                         modules=("json",)) == 1
    assert "OCR 模型不存在" in capsys.readouterr().out
    assert run_self_test(build=lambda data_dir: (qapp, _Closable()), load_ocr=lambda: None,
                         modules=("no_such_module_xyz",)) == 1


class _Closable:
    def close(self):
        return True
