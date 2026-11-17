import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from keyboard_executor.app.color_picker import ColorPickerOverlay, _patch_around


class FakeCap:
    def __init__(self, image):
        self.image = image

    def capture(self, rect):
        return self.image


def test_patch_around_center_shape():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _patch_around(img, 5, 5, 2).shape == (5, 5, 3)


def test_patch_around_clamps_at_edge():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _patch_around(img, 0, 0, 2).shape == (3, 3, 3)


def test_pick_emits_sampled_hsv(qapp):
    shot = np.full((20, 20, 3), 128, dtype=np.uint8)
    shot[10, 10] = (0, 0, 255)                  # BGR 紅
    overlay = ColorPickerOverlay(lambda: FakeCap(shot))
    overlay._shot = shot                        # 跳過 open_fullscreen 的螢幕依賴
    seen = []
    overlay.color_picked.connect(lambda h, s, v: seen.append((h, s, v)))
    overlay._pick(10, 10)
    assert seen and seen[0][0] == 0 and seen[0][1] == 255


def test_escape_emits_cancelled(qapp):
    overlay = ColorPickerOverlay(lambda: FakeCap(None))
    seen = []
    overlay.cancelled.connect(lambda: seen.append(True))
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(ev)
    assert seen == [True]


def test_overlay_parented(qapp):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    overlay = ColorPickerOverlay(lambda: FakeCap(None), parent)
    assert overlay.parent() is parent


def test_open_fullscreen_populates_qimage(qapp):
    captured = {}

    class FakeCap:
        def capture(self, rect):
            captured["rect"] = rect
            w = max(1, rect.width)
            h = max(1, rect.height)
            return np.full((h, w, 3), 128, dtype=np.uint8)

    overlay = ColorPickerOverlay(lambda: FakeCap())
    overlay.open_fullscreen()
    assert overlay._shot is not None            # 有擷取到截圖
    assert overlay._qimage is not None          # 已轉成 QImage
    assert not overlay._qimage.isNull()         # buffer 已 copy 脫離、QImage 有效
    overlay.close()


def test_patch_around_clamps_at_bottom_right():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _patch_around(img, 9, 9, 2).shape == (3, 3, 3)
