"""mss 螢幕擷取：把螢幕絕對實體像素區域擷成 BGR numpy 影像。

M3 最終審查（C2）：mss 的 grab() 在所有後端上都是以「點」（monitors() 幾何的同一單位）
解讀傳入的 region dict——即便某些後端的回傳影像解析度是實體像素（如 Retina 未加
nominal-resolution 旗標時）。本類別對外的 capture() 契約與 core 層一致，維持
「region 是螢幕絕對實體像素」（見 platforms/base.py），因此 capture() 內部會先把
呼叫端傳入的實體像素 rect 除以 scale_factor() 換算回點，才交給 grab()；在目前釘選的
mss 10.x（darwin 後端用 kCGWindowImageNominalResolution 旗標，回傳影像解析度即點，
scale_factor() 量出來是 1.0）此除法是 no-op，但在會回傳真正實體像素的後端/版本上，
這一步是避免多擷 scale 倍（Retina 上點兩倍）的必要換算。

scale_factor 以「grab 主螢幕的回傳影像寬 ÷ monitors() 量得的邏輯寬」推得
（Windows=1.0、實體輸出的 Retina 後端=2.0；目前 mss 10.x nominal-resolution 下=1.0），
供呼叫端把「點」單位的視窗/區域幾何換算為呼叫 capture() 用的「實體像素」座標。
sct 注入供測試；None 時延後到首次擷取才建立 mss 實例（macOS 需「螢幕錄製」權限）——
如此 get_platform() 建構本類別不會在無頭/無權限環境即刻建立螢幕擷取器。
"""
from __future__ import annotations

import numpy as np
import threading

from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.base import ScreenCapture


class MssScreenCapture(ScreenCapture):
    def __init__(self, sct=None):
        self._sct = sct
        self._scale: float | None = None
        self._local = threading.local()

    def _grabber(self):
        if self._sct is not None:
            return self._sct
        if not hasattr(self._local, "sct"):
            import mss
            self._local.sct = mss.MSS()
        return self._local.sct

    def close_current_thread(self):
        """MSS 的原生資源只能在建立它的執行緒使用與釋放。"""
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            del self._local.sct

    def capture(self, region: Rect) -> np.ndarray:
        # C2：呼叫端傳入的 region 是螢幕絕對「實體像素」（契約見 base.py），
        # 但 mss 的 grab() 一律以「點」解讀 region dict，因此先 ÷ scale_factor()
        # 換算回點，才交給 grab（scale_factor()==1.0 時是 no-op，見模組 docstring）。
        scale = self.scale_factor()
        left = round(region.x / scale)
        top = round(region.y / scale)
        width = round(region.width / scale)
        height = round(region.height / scale)
        shot = self._grabber().grab({"left": left, "top": top,
                                     "width": width, "height": height})
        arr = np.asarray(shot)              # (h, w, 4) BGRA
        return np.ascontiguousarray(arr[:, :, :3])  # 去 alpha，保留 BGR

    def scale_factor(self) -> float:
        if self._scale is None:
            sct = self._grabber()
            mon = sct.monitors[1]           # [1] = 主螢幕
            shot = np.asarray(sct.grab(mon))
            logical_w = mon["width"]
            self._scale = float(shot.shape[1]) / logical_w if logical_w else 1.0
        return self._scale
