import numpy as np
import pytest

from keyboard_executor.app.template_capture import capture_template
from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.storage.templates import TemplateStore
from tests.fakes import FakeScreenCapture


def test_capture_template_scales_rect_to_physical_pixels(tmp_path):
    image = np.zeros((8, 12, 3), dtype=np.uint8)
    cap = FakeScreenCapture(image=image, scale=2.0)
    store = TemplateStore(tmp_path)
    path = capture_template(cap, store, "鈕", Rect(10, 20, 6, 4))
    assert cap.captures == [Rect(20, 40, 12, 8)]   # 點 ×2 → 實體像素
    assert path == tmp_path / "templates" / "鈕.png"
    assert path.exists()


def test_capture_template_saved_png_loads_back(tmp_path):
    image = np.full((8, 12, 3), 200, dtype=np.uint8)
    cap = FakeScreenCapture(image=image, scale=1.0)
    store = TemplateStore(tmp_path)
    capture_template(cap, store, "灰", Rect(0, 0, 12, 8))
    assert store.load_template("灰").shape == (8, 12, 3)


def test_capture_template_invalid_name_propagates(tmp_path):
    cap = FakeScreenCapture(scale=1.0)
    with pytest.raises(ScriptValidationError, match="模板名稱不合法"):
        capture_template(cap, TemplateStore(tmp_path), "a/b", Rect(0, 0, 5, 5))
