import time

from keyboard_executor.app.worker import Worker


def test_run_emits_progress_in_order_then_finished(qapp):
    events = []
    records = [{"kind": "step", "index": i, "total": 3, "type": "delay",
                "label": f"延遲 {i}ms"} for i in range(3)]

    def job(progress):
        for record in records:
            progress(record)
        return "結果"

    worker = Worker(job)
    worker.progress.connect(lambda r: events.append(("progress", r)))
    worker.finished.connect(lambda r: events.append(("finished", r)))
    worker.failed.connect(lambda m: events.append(("failed", m)))
    worker.run()
    assert events == [("progress", records[0]), ("progress", records[1]),
                      ("progress", records[2]), ("finished", "結果")]


def test_run_failure_emits_failed_with_chinese_message(qapp):
    def job(progress):
        raise RuntimeError("平台爆炸")

    worker = Worker(job)
    finished = []
    failed = []
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)
    worker.run()
    assert finished == []
    assert failed == ["執行失敗：平台爆炸"]


def test_progress_dict_passed_through_unchanged(qapp):
    record = {"kind": "fire", "rule": "斷線", "trigger": "run_script"}
    seen = []

    worker = Worker(lambda progress: progress(record))
    worker.progress.connect(seen.append)
    worker.run()
    assert seen == [record]


def test_finished_carries_job_result_object(qapp):
    sentinel = object()
    results = []
    worker = Worker(lambda progress: sentinel)
    worker.finished.connect(results.append)
    worker.run()
    assert results[0] is sentinel


def test_start_runs_job_on_worker_thread_and_delivers_finished(qapp):
    from PySide6.QtCore import QThread

    seen = {}
    results = []

    def job(progress):
        seen["thread"] = QThread.currentThread()
        return "完成"

    worker = Worker(job)
    worker.finished.connect(results.append)
    worker.start()
    deadline = time.monotonic() + 5
    while not results and time.monotonic() < deadline:
        qapp.processEvents()
    assert results == ["完成"]
    assert seen["thread"] is not QThread.currentThread()   # 跑在背景執行緒
    assert worker.wait(2000)


def test_start_twice_raises_and_wait_without_start_is_true(qapp):
    import pytest

    worker = Worker(lambda progress: None)
    assert worker.wait() is True     # 未 start 視為已結束
    worker.start()
    with pytest.raises(RuntimeError, match="不能重複啟動"):
        worker.start()
    deadline = time.monotonic() + 5
    while not worker.wait(10) and time.monotonic() < deadline:
        qapp.processEvents()
    assert worker.wait(2000)
