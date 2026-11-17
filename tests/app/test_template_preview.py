import numpy as np

from keyboard_executor.app.template_preview import (
    TemplatePreview,
    bgr_to_qimage,
    load_pixmap,
)
from keyboard_executor.storage.templates import TemplateStore


def store_with(tmp_path, **images):
    store = TemplateStore(tmp_path)
    for name, image in images.items():
        store.save_template(name, image)
    return store


def solid(h, w, colour=(0, 0, 255)):
    image = np.zeros((h, w, 3), dtype=np.uint8)
    image[:, :] = colour
    return image


def test_bgr_to_qimage_swaps_channels(qapp):
    """OpenCV 是 BGR、Qt 是 RGB：轉錯的話預覽顏色會反過來。"""
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    image[0, 0] = (255, 0, 0)          # BGR 的藍
    qimage = bgr_to_qimage(image)
    assert qimage.pixelColor(0, 0).blue() == 255
    assert qimage.pixelColor(0, 0).red() == 0


def test_bgr_to_qimage_owns_its_memory(qapp):
    """copy() 之後即使原陣列消失，QImage 仍可用。"""
    image = solid(2, 2)
    qimage = bgr_to_qimage(image)
    del image
    assert qimage.pixelColor(0, 0).red() == 255


def test_load_pixmap_scales_large_image_down(qapp, tmp_path):
    store = store_with(tmp_path, 大圖=solid(400, 600))
    pixmap = load_pixmap(store, "大圖", (240, 180))
    assert pixmap.width() <= 240 and pixmap.height() <= 180
    assert abs(pixmap.width() / pixmap.height() - 600 / 400) < 0.05   # 維持比例


def test_load_pixmap_does_not_enlarge_small_image(qapp, tmp_path):
    """模板常是十幾像素的小圖示，放大只會糊掉。"""
    store = store_with(tmp_path, 小圖=solid(12, 20))
    pixmap = load_pixmap(store, "小圖", (240, 180))
    assert (pixmap.width(), pixmap.height()) == (20, 12)


def test_load_pixmap_returns_none_for_missing_or_blank(qapp, tmp_path):
    store = store_with(tmp_path, 有=solid(4, 4))
    assert load_pixmap(store, "沒有這張", (100, 100)) is None
    assert load_pixmap(store, "", (100, 100)) is None
    assert load_pixmap(store, "   ", (100, 100)) is None


def test_preview_shows_image_when_found(qapp, tmp_path):
    preview = TemplatePreview(store_with(tmp_path, 圖=solid(30, 40)))
    preview.show_template("圖")
    assert not preview.pixmap().isNull()
    assert preview.text() == ""
    assert preview.name == "圖"


def test_preview_names_the_missing_template(qapp, tmp_path):
    """規則裡模板名打錯一個字，過去要等監看靜默比對不到才發現；現在當場看得到。"""
    preview = TemplatePreview(store_with(tmp_path, 正確名=solid(4, 4)))
    preview.show_template("正確銘")
    assert preview.pixmap().isNull()
    assert "找不到模板" in preview.text() and "正確銘" in preview.text()


def test_preview_blank_name_says_so(qapp, tmp_path):
    preview = TemplatePreview(store_with(tmp_path))
    preview.show_template("")
    assert "未指定模板" in preview.text()


def test_preview_trims_whitespace(qapp, tmp_path):
    preview = TemplatePreview(store_with(tmp_path, 圖=solid(4, 4)))
    preview.show_template("  圖  ")
    assert not preview.pixmap().isNull()
    assert preview.name == "圖"


def test_preview_switching_back_to_missing_clears_old_image(qapp, tmp_path):
    """換到不存在的名稱時要清掉舊圖，否則會顯示上一張、看起來像有這張模板。"""
    preview = TemplatePreview(store_with(tmp_path, 圖=solid(4, 4)))
    preview.show_template("圖")
    preview.show_template("不存在")
    assert preview.pixmap().isNull()


def test_size_text_reports_pixel_dimensions(qapp, tmp_path):
    preview = TemplatePreview(store_with(tmp_path, 圖=solid(30, 40)))
    preview.show_template("圖")
    assert preview.size_text() == "40 × 30 px"


def test_size_text_empty_when_no_template(qapp, tmp_path):
    preview = TemplatePreview(store_with(tmp_path))
    preview.show_template("沒有")
    assert preview.size_text() == ""
