"""可取消的共用 OCR 子程序；所有請求只使用同一個 v6 tiny/ONNX 引擎。"""
from __future__ import annotations

import multiprocessing
import threading

from keyboard_executor.platforms.base import OcrEngine

_PROCESS_SLOT = threading.Lock()  # 舊程序完全回收後，下一次執行才能載入模型


def _serve(connection, lang):
    from keyboard_executor.platforms.common.process import configure_background_child
    configure_background_child()
    from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine

    # Legacy language values never select a second engine or fallback model.
    del lang
    engine = RapidOcrEngine()
    try:
        connection.send((True, None))  # 已可接收影像，主程序不在 spawn 載入期間阻塞送資料
        while True:
            request = connection.recv()
            try:
                result = engine.recognize(request)
                connection.send((True, result))
            except Exception as exc:
                connection.send((False, str(exc)))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


class ProcessOcrEngine(OcrEngine):
    """每次腳本執行獨享一個子程序；close 僅發取消，由背景工作回收。"""

    def __init__(self, lang, stop_event, *, worker=_serve):
        self._lang = lang
        self._stop = stop_event
        self._worker = worker
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._process = None
        self._connection = None
        self._reaper = None
        self._owns_slot = False

    def _aborted(self):
        return self._stop.is_set() or self._closed.is_set()

    def _start(self):
        while not self._aborted():
            if _PROCESS_SLOT.acquire(timeout=.05):
                self._owns_slot = True
                break
        else:
            raise InterruptedError("聊天辨識已取消")
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=self._worker, args=(child, self._lang),
                              name="chat-ocr", daemon=True)
        try:
            process.start()
        except BaseException:
            parent.close()
            self._owns_slot = False
            _PROCESS_SLOT.release()
            raise
        finally:
            child.close()
        self._connection, self._process = parent, process
        self._receive()

    def _receive(self):
        while not self._aborted():
            if self._connection.poll(.05):
                ok, result = self._connection.recv()
                if self._aborted():
                    break
                if not ok:
                    raise RuntimeError(result)
                return result
            if not self._process.is_alive():
                raise RuntimeError("聊天 OCR 程序已結束")
        raise InterruptedError("聊天辨識已取消")

    def recognize(self, request):
        with self._lock:
            if self._aborted():
                raise InterruptedError("聊天辨識已取消")
            try:
                if self._process is None:
                    self._start()
                self._connection.send(request)
                return self._receive()
            except BaseException:
                self._shutdown()
                raise

    def _shutdown(self):
        process = self._process
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
            self._process = None
        if self._owns_slot:
            self._owns_slot = False
            _PROCESS_SLOT.release()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()

        def reap():
            with self._lock:
                self._shutdown()

        self._reaper = threading.Thread(target=reap, name="chat-ocr-cleanup", daemon=True)
        self._reaper.start()
