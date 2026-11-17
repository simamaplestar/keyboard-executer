import numpy as np
import pytest

from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.storage.templates import TemplateStore


def test_save_template_writes_png_in_templates_subdir(tmp_path):
    store = TemplateStore(tmp_path)
    img = np.zeros((8, 12, 3), dtype=np.uint8)
    img[:, :, 2] = 255
    path = store.save_template("紅", img)
    assert path == tmp_path / "templates" / "紅.png"
    assert path.exists()


def test_load_template_returns_ndarray(tmp_path):
    store = TemplateStore(tmp_path)
    img = np.zeros((8, 12, 3), dtype=np.uint8)
    img[2:6, 3:9] = (0, 255, 0)
    store.save_template("綠", img)
    loaded = store.load_template("綠")
    assert isinstance(loaded, np.ndarray)
    assert loaded.shape == (8, 12, 3)


def test_load_template_missing_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到模板"):
        TemplateStore(tmp_path).load_template("無")


def test_list_names_sorted_and_empty(tmp_path):
    store = TemplateStore(tmp_path)
    assert store.list_names() == []
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    store.save_template("乙", img)
    store.save_template("甲", img)
    assert store.list_names() == ["乙", "甲"]   # sorted()


def test_delete_removes_template(tmp_path):
    store = TemplateStore(tmp_path)
    store.save_template("刪我", np.zeros((4, 4, 3), dtype=np.uint8))
    store.delete("刪我")
    assert store.list_names() == []


def test_delete_missing_template_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到模板"):
        TemplateStore(tmp_path).delete("無")


def test_load_template_corrupt_file_distinct_message(tmp_path):
    store = TemplateStore(tmp_path)
    (tmp_path / "templates").mkdir(parents=True)
    (tmp_path / "templates" / "壞.png").write_bytes(b"\x00\x01" + "不是PNG".encode("utf-8"))
    with pytest.raises(ScriptValidationError, match="損毀"):
        store.load_template("壞")


# --- 匯出/匯入用的原始位元組存取 ---

def test_read_bytes_returns_file_verbatim(tmp_path):
    import numpy as np
    store = TemplateStore(tmp_path)
    path = store.save_template("圖", np.zeros((4, 4, 3), dtype=np.uint8))
    assert store.read_bytes("圖") == path.read_bytes()   # 不重新壓縮


def test_read_bytes_missing_raises_chinese(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到模板"):
        TemplateStore(tmp_path).read_bytes("不存在")


def test_write_bytes_round_trips_and_is_loadable(tmp_path):
    import numpy as np
    src = TemplateStore(tmp_path / "a")
    src.save_template("圖", np.zeros((4, 4, 3), dtype=np.uint8))
    data = src.read_bytes("圖")

    dst = TemplateStore(tmp_path / "b")
    dst.write_bytes("圖", data)
    assert dst.read_bytes("圖") == data
    assert dst.load_template("圖").shape == (4, 4, 3)


def test_write_bytes_rejects_non_image(tmp_path):
    """匯入來源是外部檔案：不驗證就會讓任意位元組變成 templates/*.png。"""
    store = TemplateStore(tmp_path)
    with pytest.raises(ScriptValidationError, match="不是可讀影像"):
        store.write_bytes("壞圖", b"definitely not a png")
    assert store.list_names() == []          # 壞資料不得落地


def test_write_bytes_supports_unicode_names(tmp_path):
    import numpy as np
    src = TemplateStore(tmp_path / "a")
    src.save_template("測謊文字", np.zeros((2, 2, 3), dtype=np.uint8))
    dst = TemplateStore(tmp_path / "b")
    dst.write_bytes("測謊文字", src.read_bytes("測謊文字"))
    assert dst.list_names() == ["測謊文字"]
