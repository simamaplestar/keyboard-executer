"""模板圖檔（PNG）存取：<root>/templates/<name>.png。OpenCV 讀寫（BGR）。"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from keyboard_executor.core.models import ScriptValidationError


class TemplateStore:
    def __init__(self, root: str | Path):
        self._dir = Path(root) / "templates"

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or not name.strip():
            raise ScriptValidationError(f"模板名稱不合法: {name!r}")
        return self._dir / f"{name}.png"

    def save_template(self, name: str, image: np.ndarray) -> Path:
        path = self.path_for(name)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            # 不用 cv2.imwrite：它在 Windows 以系統 ANSI 編碼處理路徑，非 ASCII（中文）
            # 模板名會寫入失敗。改走 imencode + Path.write_bytes，跨平台且支援 Unicode 檔名。
            ok, buf = cv2.imencode(".png", image)
            if not ok:
                raise OSError("cv2.imencode 失敗")
            path.write_bytes(buf.tobytes())
        except OSError as e:
            raise ScriptValidationError(f"模板 {name!r} 無法儲存: {e}") from e
        return path

    def load_template(self, name: str) -> np.ndarray:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到模板 {name!r}（{path}）")
        # 同上：不用 cv2.imread（Windows 非 ASCII 路徑會回 None），改 read_bytes + imdecode。
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ScriptValidationError(f"模板 {name!r} 檔案損毀或非可讀影像（{path}）")
        return image

    def read_bytes(self, name: str) -> bytes:
        """讀原始 PNG 位元組（匯出用）。

        刻意不走 load_template：那會 imdecode 成陣列、匯出端再 imencode 回去，
        等於重新壓縮一次，白白改變檔案內容。匯出要的是原封不動的那張圖。
        """
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到模板 {name!r}（{path}）")
        try:
            return path.read_bytes()
        except OSError as e:
            raise ScriptValidationError(f"模板 {name!r} 無法讀取: {e}") from e

    def write_bytes(self, name: str, data: bytes) -> Path:
        """寫入原始 PNG 位元組（匯入用）；先確認真的是可解碼的影像才落地。

        匯入來源是外部檔案，不驗證就等於讓任意位元組變成 templates/*.png，
        之後每次比對都會炸在 load_template。
        """
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ScriptValidationError(f"模板 {name!r} 的資料不是可讀影像，已略過")
        path = self.path_for(name)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as e:
            raise ScriptValidationError(f"模板 {name!r} 無法儲存: {e}") from e
        return path

    def list_names(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.png"))

    def delete(self, name: str) -> None:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到模板 {name!r}（{path}）")
        try:
            path.unlink()
        except OSError as e:
            raise ScriptValidationError(f"模板 {name!r} 無法刪除: {e}") from e
