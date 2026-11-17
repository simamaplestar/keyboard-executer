from keyboard_executor.app.logview import format_progress, format_result
from keyboard_executor.core.player import PlayResult


def test_format_progress_variants():
    assert format_progress({"kind": "step", "index": 2, "total": 5,
                            "type": "key_press", "label": "按鍵 a"}) == "[3/5] 按鍵 a"
    assert format_progress({"kind": "fire", "rule": "斷線", "trigger": "run_script"}
                           ) == "規則「斷線」觸發（run_script）"
    assert format_progress({"kind": "notify", "message": "斷線了"}) == "通知：斷線了"
    assert format_progress({"kind": "error", "message": "擷取失敗"}) == "錯誤：擷取失敗"
    assert "未知" in format_progress({"kind": "未知"}) or format_progress(
        {"kind": "未知"}).startswith("{")


def test_format_result_ok():
    assert format_result(PlayResult(ok=True, actions_run=7)) == "回放完成，共執行 7 個動作"


def test_format_result_failure():
    assert format_result(PlayResult(ok=False, actions_run=2, error="目標視窗已關閉")
                         ) == "回放中止：目標視窗已關閉（已執行 2 個動作）"


def test_should_log_filters_by_level():
    from keyboard_executor.app.logview import should_log
    step = {"kind": "step"}
    fire = {"kind": "fire"}
    assert should_log(step, "INFO") and should_log(fire, "INFO")
    assert not should_log(step, "WARNING")     # WARNING 起隱藏逐步進度
    assert should_log(fire, "WARNING")
    assert not should_log({"kind": "怪"}, "INFO")   # 未知 kind 只在 DEBUG 顯示
    assert should_log({"kind": "怪"}, "DEBUG")


def test_error_records_survive_every_level():
    from keyboard_executor.app.logview import should_log
    error = {"kind": "error", "message": "x"}
    for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        assert should_log(error, level)


def test_wait_result_and_branch_format():
    from keyboard_executor.app.logview import format_progress
    assert format_progress({"kind": "wait_result", "index": 2, "type": "wait_text",
                            "matched": False, "elapsed_ms": 5000,
                            "on_timeout": "continue"}) == "等待 #2 逾時（continue）"
    assert format_progress({"kind": "wait_result", "index": 2, "type": "wait_text",
                            "matched": True, "elapsed_ms": 120,
                            "on_timeout": None}) == "等待 #2 命中（120ms）"
    assert format_progress({"kind": "branch", "index": 1, "type": "if_text",
                            "taken": "else"}) == "判斷 #1 走 else"


def test_new_kinds_are_debug_level():
    from keyboard_executor.app.logview import should_log
    assert not should_log({"kind": "wait_result"}, "INFO")
    assert not should_log({"kind": "branch"}, "INFO")
    assert should_log({"kind": "branch"}, "DEBUG")
