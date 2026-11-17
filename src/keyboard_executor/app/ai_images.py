"""AI 聊天圖片附件：用 Qt 解碼、縮放與建立安全暫存副本。"""
from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QImageWriter, QPixmap

MAX_IMAGE_COUNT = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_EDGE = 2000
MAX_SOURCE_EDGE = 8000


class ImageAttachmentError(Exception):
    pass


def load_image_attachment(path: str, cache_dir: str | Path) -> dict:
    """讀圖、依官方建議縮至 2000px 內，回內部附件 dict。"""
    source = Path(path)
    if not source.is_file():
        raise ImageAttachmentError(f"找不到圖片：{source.name}")
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    if not reader.canRead():
        raise ImageAttachmentError(f"不支援或無法讀取圖片：{source.name}")
    source_size = reader.size()
    if (source_size.isValid()
            and max(source_size.width(), source_size.height()) > MAX_SOURCE_EDGE):
        raise ImageAttachmentError(
            f"圖片邊長不可超過 {MAX_SOURCE_EDGE}px：{source.name}")
    if (source_size.isValid()
            and max(source_size.width(), source_size.height()) > MAX_IMAGE_EDGE):
        reader.setScaledSize(source_size.scaled(
            QSize(MAX_IMAGE_EDGE, MAX_IMAGE_EDGE),
            Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ImageAttachmentError(f"圖片內容損壞：{source.name}")
    if max(image.width(), image.height()) > MAX_IMAGE_EDGE:
        image = image.scaled(
            MAX_IMAGE_EDGE, MAX_IMAGE_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

    original_suffix = source.suffix.lower()
    use_jpeg = original_suffix in (".jpg", ".jpeg") and not image.hasAlphaChannel()
    encoded, media_type, suffix = _encode(image, jpeg=use_jpeg)
    if len(encoded) > MAX_IMAGE_BYTES and not use_jpeg:
        encoded, media_type, suffix = _encode(_on_white(image), jpeg=True)
    if len(encoded) > MAX_IMAGE_BYTES:
        raise ImageAttachmentError(
            f"圖片處理後仍超過 {MAX_IMAGE_BYTES // 1024 // 1024}MB：{source.name}")

    destination = Path(cache_dir) / f"{uuid4().hex}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    return {
        "name": source.name,
        "media_type": media_type,
        "data": base64.b64encode(encoded).decode("ascii"),
        "path": str(destination.resolve()),
        "width": image.width(),
        "height": image.height(),
        "size_bytes": len(encoded),
    }


def attachment_pixmap(attachment: dict, size: int = 72) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(base64.b64decode(attachment["data"]))
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def _encode(image: QImage, *, jpeg: bool) -> tuple[bytes, str, str]:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    fmt = b"JPEG" if jpeg else b"PNG"
    writer = QImageWriter(buffer, fmt)
    if jpeg:
        writer.setQuality(90)
    if not writer.write(image):
        raise ImageAttachmentError(f"圖片轉檔失敗：{writer.errorString()}")
    data = bytes(buffer.data())
    buffer.close()
    return (data, "image/jpeg", ".jpg") if jpeg else (data, "image/png", ".png")


def _on_white(image: QImage) -> QImage:
    if not image.hasAlphaChannel():
        return image
    flattened = QImage(image.size(), QImage.Format.Format_RGB32)
    flattened.fill(Qt.GlobalColor.white)
    from PySide6.QtGui import QPainter
    painter = QPainter(flattened)
    painter.drawImage(0, 0, image)
    painter.end()
    return flattened
