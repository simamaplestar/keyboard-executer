import numpy as np

from keyboard_executor.core.geometry import Rect
from keyboard_executor.platforms.common.capture_mss import MssScreenCapture


class StubSct:
    """模擬 mss.mss()：monitors[1] 為主螢幕邏輯尺寸；grab 回傳固定 BGRA 陣列。"""

    def __init__(self, logical_w=100, logical_h=80, phys_scale=1):
        self.monitors = [
            {"left": 0, "top": 0, "width": logical_w, "height": logical_h},   # [0] 全部
            {"left": 0, "top": 0, "width": logical_w, "height": logical_h},   # [1] 主
        ]
        self._scale = phys_scale
        self.grabs = []

    def grab(self, region):
        self.grabs.append(region)
        w = region["width"] if isinstance(region, dict) else region.width
        h = region["height"] if isinstance(region, dict) else region.height
        # 模擬 mss：Retina 時 grab 回傳 scale 倍的實體像素影像
        s = self._scale
        arr = np.zeros((h * s if h else self.monitors[1]["height"] * s,
                        w * s if w else self.monitors[1]["width"] * s, 4), dtype=np.uint8)
        arr[..., 0] = 10  # B
        arr[..., 1] = 20  # G
        arr[..., 2] = 30  # R
        arr[..., 3] = 255
        return arr


def test_capture_returns_bgr_ndarray_dropping_alpha():
    cap = MssScreenCapture(sct=StubSct())
    img = cap.capture(Rect(0, 0, 4, 3))
    assert isinstance(img, np.ndarray)
    assert img.shape == (3, 4, 3)  # 去掉 alpha 通道
    assert tuple(img[0, 0]) == (10, 20, 30)  # BGR 順序保留


def test_capture_passes_absolute_region_to_grab():
    # C2：grab 是「點」座標契約。scale=1（目前 mss 10.x 的 nominal-resolution 行為）
    # 時 ÷scale 是 no-op，grab 收到的數值恰好與呼叫端傳入的實體像素 region 相同。
    sct = StubSct()
    MssScreenCapture(sct=sct).capture(Rect(200, 100, 40, 30))
    assert sct.grabs[-1] == {"left": 200, "top": 100, "width": 40, "height": 30}


def test_capture_converts_physical_region_to_points_when_scale_is_two():
    # C2：呼叫端傳入的 region 是實體像素（已 ×scale_factor()）；capture() 必須先
    # ÷scale_factor() 換算成 grab 要的「點」，否則實體輸出的後端會多擷取 scale 倍。
    sct = StubSct(logical_w=100, logical_h=80, phys_scale=2)  # scale_factor() == 2.0
    cap = MssScreenCapture(sct=sct)
    img = cap.capture(Rect(200, 100, 40, 30))
    assert sct.grabs[-1] == {"left": 100, "top": 50, "width": 20, "height": 15}
    # capture() 的回傳仍是 grab 真正回傳的影像（stub 依 phys_scale 放大 h/w，去 alpha）
    assert img.shape == (15 * 2, 20 * 2, 3)


def test_scale_factor_retina_is_two():
    cap = MssScreenCapture(sct=StubSct(logical_w=100, logical_h=80, phys_scale=2))
    assert cap.scale_factor() == 2.0


def test_scale_factor_non_retina_is_one_and_cached():
    sct = StubSct(logical_w=100, logical_h=80, phys_scale=1)
    cap = MssScreenCapture(sct=sct)
    assert cap.scale_factor() == 1.0
    cap.scale_factor()
    assert len(sct.grabs) == 1  # 快取：只 grab 一次


def test_player_and_chat_threads_own_separate_capture_resources(monkeypatch):
    import threading
    import mss

    instances = []

    class OwnedSct(StubSct):
        def __init__(self):
            super().__init__()
            self.owner = threading.get_ident()
            self.closed = False
            instances.append(self)

        def grab(self, region):
            assert threading.get_ident() == self.owner
            return super().grab(region)

        def close(self):
            assert threading.get_ident() == self.owner
            self.closed = True

    monkeypatch.setattr(mss, "MSS", OwnedSct)
    cap = MssScreenCapture()
    cap.capture(Rect(0, 0, 4, 3))
    errors = []

    def chat():
        try:
            cap.capture(Rect(0, 0, 4, 3))
        except Exception as exc:
            errors.append(exc)
        finally:
            cap.close_current_thread()

    worker = threading.Thread(target=chat)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert not errors
    assert len(instances) == 2
    assert not instances[0].closed and instances[1].closed
    cap.capture(Rect(0, 0, 4, 3))
    cap.close_current_thread()
    assert instances[0].closed
