"""macOS 權限檢查。模擬輸入需要「輔助使用」；錄製/全域熱鍵需「輸入監控」；截圖需「螢幕錄製」。"""
from __future__ import annotations

ACCESSIBILITY_GUIDE = (
    "尚未授予「輔助使用」權限，無法模擬鍵盤滑鼠。\n"
    "請開啟：系統設定 → 隱私權與安全性 → 輔助使用，"
    "將執行本程式的終端機（或打包後的 App）加入並勾選，然後重新啟動程式。"
)


def check_accessibility(_ax_is_trusted=None) -> bool:
    if _ax_is_trusted is None:
        from ApplicationServices import AXIsProcessTrusted as _ax_is_trusted
    return bool(_ax_is_trusted())


def request_accessibility(_request=None, _prompt_key=None) -> bool:
    """讓 App 出現在輔助使用清單；系統不會在未授權時自動給予權限。"""
    if _request is None:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        _request = AXIsProcessTrustedWithOptions
        _prompt_key = kAXTrustedCheckOptionPrompt
    return bool(_request({_prompt_key or "AXTrustedCheckOptionPrompt": True}))


SCREEN_RECORDING_GUIDE = (
    "尚未授予「螢幕錄製」權限，無法擷取畫面（wait_text/click_image 與監看規則將失效）。\n"
    "請開啟：系統設定 → 隱私權與安全性 → 螢幕錄製，"
    "將執行本程式的終端機（或打包後的 App）加入並勾選，然後重新啟動程式。"
)

INPUT_MONITORING_GUIDE = (
    "尚未授予「輸入監控」權限，無法錄製與使用全域熱鍵（F9/F10、滑鼠角落緊急停止）。\n"
    "請開啟：系統設定 → 隱私權與安全性 → 輸入監控，"
    "將執行本程式的終端機（或打包後的 App）加入並勾選，然後重新啟動程式。"
)


def check_screen_recording(_preflight=None) -> bool:
    if _preflight is None:
        from Quartz import CGPreflightScreenCaptureAccess as _preflight  # pragma: no cover - 需原生環境
    return bool(_preflight())


def check_input_monitoring(_preflight=None) -> bool:
    if _preflight is None:
        from Quartz import CGPreflightListenEventAccess as _preflight  # pragma: no cover - 需原生環境
    return bool(_preflight())


_SETTINGS_PANES = {
    "accessibility": "Privacy_Accessibility",
    "screen-recording": "Privacy_ScreenCapture",
    "input-monitoring": "Privacy_ListenEvent",
}


def system_settings_url(pane: str) -> str:
    """「系統設定 → 隱私權與安全性」對應分頁的 deep link（spec §10 直達連結）。
    pane ∈ accessibility / screen-recording / input-monitoring。"""
    if pane not in _SETTINGS_PANES:
        raise ValueError(f"未知的權限分頁: {pane!r}")
    return ("x-apple.systempreferences:com.apple.preference.security"
            f"?{_SETTINGS_PANES[pane]}")


def request_screen_recording(_request=None) -> bool:
    """主動觸發「螢幕錄製」授權對話框——簽章打包後的 .app 首次啟動呼叫，
    讓本程式出現在系統設定清單。回傳當下是否已授權（未授權時系統只提示，
    授權後需重新啟動程式才生效）。"""
    if _request is None:
        from Quartz import CGRequestScreenCaptureAccess as _request  # pragma: no cover - 需原生環境
    return bool(_request())


def request_input_monitoring(_request=None) -> bool:
    """主動觸發「輸入監控」授權對話框。行為同 request_screen_recording。
    輔助使用另以 AXIsProcessTrustedWithOptions 請求。"""
    if _request is None:
        from Quartz import CGRequestListenEventAccess as _request  # pragma: no cover - 需原生環境
    return bool(_request())
