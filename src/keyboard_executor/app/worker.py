"""QThread 工作橋（spec §7：回放/監看於背景執行緒執行，GUI 保持可操作）。

Worker 把一個「job」（接收 progress callback 的 callable）搬上 QThread，
並以 Qt signal 送回進度/結果/失敗——這是 GUI 與 core 之間唯一的執行緒橋樑：
core（Player/RuleEngine）完全不知道 Qt，只透過注入 callback（on_step/on_fire/
notifier/on_error）回報；job 把這些 callback 接到 Worker 提供的 progress 上，
Worker 再以跨執行緒安全的 signal emit 投遞回 GUI 執行緒。

job 契約：job(progress: Callable[[dict], None]) -> Any。progress 收到的 dict
原樣成為 progress signal 的 payload（kind="step"/"fire"/"notify"/"error"，
見計畫跨任務契約）。Worker 為一次性：一個 job 一個 Worker，不可重複 start。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class Worker(QObject):
    progress = Signal(dict)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job
        self._thread: QThread | None = None

    def start(self) -> None:
        """把自己搬上新 QThread 並執行 run()；一次性，重複 start 拋錯。"""
        if self._thread is not None:
            raise RuntimeError("Worker 已啟動，不能重複啟動")
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self.run)
        self._thread.start()

    def run(self) -> None:
        """執行 job。直接呼叫＝在當前執行緒同步執行（測試/ImmediateWorker 用）；
        經 start() 呼叫＝在背景 QThread 執行，signal 以 queued connection 投遞。"""
        try:
            result = self._job(self.progress.emit)
        except Exception as e:  # job 例外不可讓背景執行緒無聲死亡
            self.failed.emit(f"執行失敗：{e}")
        else:
            self.finished.emit(result)
        finally:
            if self._thread is not None:
                self._thread.quit()

    def wait(self, timeout_ms: int = 5000) -> bool:
        """等待背景執行緒結束（測試與關閉流程用）；未曾 start 視為已結束。"""
        if self._thread is None:
            return True
        return self._thread.wait(timeout_ms)
