"""腳本 JSON 檔案存取。一個腳本一個檔：<root>/<name>.json。"""
from __future__ import annotations

import json
from pathlib import Path

from keyboard_executor.core.models import (
    Script,
    ScriptValidationError,
    script_from_dict,
    script_to_dict,
)


# 與腳本同目錄、但不是腳本的保留檔名（SettingsStore 寫 settings.json 於此）。
# 不排除的話 list_names 會把它當成一個叫「settings」的腳本列出來。
_RESERVED_NAMES = {"settings"}


class ScriptStorage:
    def __init__(self, root: str | Path):
        self._root = Path(root)

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or not name.strip():
            raise ScriptValidationError(f"腳本名稱不合法: {name!r}")
        if name.strip().lower() in _RESERVED_NAMES:
            raise ScriptValidationError(f"腳本名稱 {name!r} 為系統保留字，請換一個")
        return self._root / f"{name}.json"

    def save(self, script: Script) -> Path:
        path = self.path_for(script.name)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(script_to_dict(script), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            raise ScriptValidationError(f"腳本 {script.name!r} 無法儲存: {e}") from e
        return path

    def load(self, name: str) -> Script:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到腳本 {name!r}（{path}）")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ScriptValidationError(f"腳本 {name!r} 不是合法 JSON: {e}") from e
        except (UnicodeDecodeError, OSError) as e:
            raise ScriptValidationError(f"腳本 {name!r} 無法讀取: {e}") from e
        return script_from_dict(data)

    def delete(self, name: str) -> None:
        path = self.path_for(name)
        if not path.exists():
            raise ScriptValidationError(f"找不到腳本 {name!r}（{path}）")
        try:
            path.unlink()
        except OSError as e:
            raise ScriptValidationError(f"腳本 {name!r} 無法刪除: {e}") from e
        self._layout_path(name).unlink(missing_ok=True)     # 一併清掉版面 sidecar
        for extra in self._map_paths(name):
            extra.unlink(missing_ok=True)

    # -- 編輯器版面 sidecar（純 UI：chip 座標/縮放），與腳本本體分離，不入核心 schema。
    #    存於 .layouts/ 子目錄，避開 list_names 的 *.json glob。 --

    def _layout_path(self, name: str) -> Path:
        self.path_for(name)                                  # 沿用名稱合法性檢查
        return self._root / ".layouts" / f"{name}.json"

    def save_layout(self, name: str, layout: dict) -> None:
        """儲存編輯器版面（失敗不影響腳本本體，靜默略過）。"""
        path = self._layout_path(name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def load_layout(self, name: str) -> dict | None:
        """讀回編輯器版面；不存在或壞掉回傳 None（呼叫端退回自動排列）。"""
        path = self._layout_path(name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    # -- 小地圖分析 sidecar（學路線時產生：地圖分析、原始錄製、小地圖截圖），存於 .maps/。

    def _map_paths(self, name: str) -> tuple[Path, Path]:
        self.path_for(name)
        base = self._root / ".maps"
        return base / f"{name}.json", base / f"{name}.png"

    def save_route_map(self, name: str, data: dict, png: bytes | None = None) -> None:
        """儲存地圖分析（失敗不影響腳本本體，靜默略過）。"""
        json_path, png_path = self._map_paths(name)
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if png:
                png_path.write_bytes(png)
            else:
                png_path.unlink(missing_ok=True)
        except OSError:
            pass

    def load_route_map(self, name: str) -> dict | None:
        json_path, _ = self._map_paths(name)
        if not json_path.exists():
            return None
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def route_map_image(self, name: str) -> Path | None:
        _, png_path = self._map_paths(name)
        return png_path if png_path.exists() else None

    def copy_route_map(self, src: str, dst: str) -> None:
        data = self.load_route_map(src)
        if data is None:
            return
        image = self.route_map_image(src)
        self.save_route_map(dst, data, image.read_bytes() if image is not None else None)

    def list_names(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json")
                      if p.stem.lower() not in _RESERVED_NAMES)
