from keyboard_executor.app.region_picker import RegionPickerOverlay
from keyboard_executor.core.geometry import Rect


def test_overlay_constructs_offscreen(qapp):
    overlay = RegionPickerOverlay()
    assert overlay.isVisible() is False


def test_drag_sequence_emits_normalized_region(qapp):
    overlay = RegionPickerOverlay()
    seen = []
    overlay.region_selected.connect(seen.append)
    overlay._begin(40, 60)
    overlay._update(20, 25)
    overlay._finish(10, 20)      # 反向拖曳 → 正規化
    assert seen == [Rect(10, 20, 30, 40)]


def test_overlay_freezes_screen_before_show_and_crops_that_snapshot(qapp):
    import numpy as np

    captures = []

    class FakeCapture:
        def capture(self, rect):
            captures.append(rect)
            image = np.empty((rect.height, rect.width, 3), dtype=np.uint8)
            image[:] = (7, 11, 13)
            return image

    overlay = RegionPickerOverlay(capture_factory=FakeCapture)
    overlay.open_fullscreen()
    crop = overlay.captured_region(
        Rect(overlay.x() + 3, overlay.y() + 4, 12, 9))

    assert len(captures) == 1
    assert overlay._qimage is not None
    assert crop is not None and crop.size > 0
    assert np.all(crop == (7, 11, 13))
    overlay.close()
