from PySide6.QtGui import QImage

from keyboard_executor.app.ai_images import (
    MAX_IMAGE_EDGE,
    attachment_pixmap,
    load_image_attachment,
)


def test_load_image_attachment_resizes_and_caches(qapp, tmp_path):
    source = tmp_path / "大圖.png"
    image = QImage(2400, 1200, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(source), "PNG")

    attachment = load_image_attachment(str(source), tmp_path / "cache")
    assert attachment["name"] == "大圖.png"
    assert attachment["media_type"] == "image/png"
    assert max(attachment["width"], attachment["height"]) == MAX_IMAGE_EDGE
    assert attachment["data"] and attachment["path"] != str(source)
    assert not attachment_pixmap(attachment).isNull()
