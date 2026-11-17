"""模板擷取編排（純 Python，無 Qt import）：框選區域 → 擷圖 → 存 PNG。"""
from __future__ import annotations

from keyboard_executor.core.geometry import Rect


def capture_template(capture, store, name: str, screen_rect_points: Rect):
    """screen_rect_points：螢幕絕對「點」矩形（drag_scale 換算後的框選結果）。
    依 capture.scale_factor() 換為實體像素（ScreenCapture 契約，見 base.py）
    後擷取，存入 TemplateStore；回傳 PNG 路徑。名稱不合法/寫入失敗由
    save_template 拋 ScriptValidationError（繁中）。"""
    scale = capture.scale_factor()
    rect = Rect(round(screen_rect_points.x * scale),
                round(screen_rect_points.y * scale),
                round(screen_rect_points.width * scale),
                round(screen_rect_points.height * scale))
    image = capture.capture(rect)
    return store.save_template(name, image)
