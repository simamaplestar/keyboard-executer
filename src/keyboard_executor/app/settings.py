"""GUI 設定（純 Python，無 Qt import）：熱鍵、OCR 語言、日誌等級。

JSON 存於 <root>/settings.json；檔案缺失→預設值；損毀→繁中警告後回預設
（spec §10 報錯不崩潰）。儲存前驗證：熱鍵必須是合法按鍵名稱（keynames）且
兩鍵不同；log_level 限 DEBUG/INFO/WARNING/ERROR。熱鍵與 OCR 語言於
控制器建構時讀取——修改後重新啟動生效（設定頁如實提示）。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from keyboard_executor.core.keynames import is_valid_key
from keyboard_executor.core.models import ScriptValidationError

logger = logging.getLogger(__name__)

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass(frozen=True)
class Settings:
    toggle_key: str = "f9"
    stop_key: str = "f10"
    ocr_language: str = "auto"
    log_level: str = "INFO"
    discord_webhook_url: str = ""
    corner_failsafe: bool = True
    ai_provider: str = ""        # ""=停用 / "anthropic" / "openai" / "openrouter"
    ai_auth_mode: str = "api_key"  # api_key / subscription
    ai_auth_profile: str = ""      # 非祕密；token 存 Credential Manager
    ai_model: str = ""
    ai_api_key: str = ""         # 明文存本機 settings.json（設定頁如實標示）
    ai_privacy_ack: bool = False  # 首次送出的隱私告知已確認
    ai_demo_max_frames: int = 30  # AI 示範錄製：每次最多送幾張截圖
    ai_demo_max_rounds: int = 3   # AI 示範錄製：最多自動試跑幾輪
    auto_update: bool = True      # 打包版啟動後自動檢查／下載新版


def validate_settings(settings: Settings) -> Settings:
    # 正規化成 canonical 小寫：輸入 hook（key_to_name）送出的是小寫按鍵名，
    # SessionGuard 以 event.key == stop_key 精確比對；若這裡不正規化，使用者打
    # 「F10」等大寫就永遠比不中，緊急停止會完全無效。
    toggle = settings.toggle_key.strip().lower()
    stop = settings.stop_key.strip().lower()
    for label, value in (("toggle_key", toggle), ("stop_key", stop)):
        if not is_valid_key(value):
            raise ScriptValidationError(f"設定 {label} 不是可用的按鍵名稱: {value!r}")
    if toggle == stop:
        raise ScriptValidationError("設定 toggle_key 與 stop_key 不可相同")
    if settings.log_level not in _LOG_LEVELS:
        raise ScriptValidationError(
            f"設定 log_level 必須是 {'/'.join(_LOG_LEVELS)}: {settings.log_level!r}")
    webhook = settings.discord_webhook_url.strip()
    if webhook and not (webhook.startswith("https://") and "/webhooks/" in webhook):
        raise ScriptValidationError(
            f"設定 discord_webhook_url 不是合法的 Discord webhook 網址: {webhook!r}")
    if not isinstance(settings.corner_failsafe, bool):
        raise ScriptValidationError(
            f"設定 corner_failsafe 必須是布林值: {settings.corner_failsafe!r}")
    ai_provider = settings.ai_provider.strip()
    if ai_provider not in ("", "anthropic", "openai", "openrouter"):
        raise ScriptValidationError(
            f"設定 ai_provider 必須是空白、anthropic、openai 或 openrouter: {ai_provider!r}")
    ai_auth_mode = settings.ai_auth_mode.strip()
    if ai_auth_mode not in ("api_key", "subscription"):
        raise ScriptValidationError(
            f"設定 ai_auth_mode 必須是 api_key 或 subscription: {ai_auth_mode!r}")
    if ai_provider == "openrouter" and ai_auth_mode != "api_key":
        raise ScriptValidationError("OpenRouter 僅支援 API 金鑰")
    ai_profile = settings.ai_auth_profile.strip()
    ai_model = settings.ai_model.strip()
    ai_key = settings.ai_api_key.strip()
    if ai_provider:
        if ai_auth_mode == "api_key" and not ai_model:
            raise ScriptValidationError("設定 ai_model 不可空白（已選擇 AI 供應商）")
        if ai_auth_mode == "api_key" and not ai_key:
            raise ScriptValidationError("設定 ai_api_key 不可空白（已選擇 AI 供應商）")
        if ai_auth_mode == "subscription" and not ai_profile:
            raise ScriptValidationError("設定 ai_auth_profile 不可空白（尚未完成訂閱登入）")
        if (ai_auth_mode == "subscription" and ai_provider == "openai"
                and ai_profile != "codex"):
            raise ScriptValidationError("OpenAI 訂閱登入 profile 必須是 codex")
        if (ai_auth_mode == "subscription" and ai_provider == "anthropic"
                and ai_profile not in ("claude-cli", "setup-token")):
            raise ScriptValidationError(
                "Anthropic 訂閱登入 profile 必須是 claude-cli 或 setup-token")
    if not isinstance(settings.ai_privacy_ack, bool):
        raise ScriptValidationError(
            f"設定 ai_privacy_ack 必須是布林值: {settings.ai_privacy_ack!r}")
    for label, value, low, high in (("ai_demo_max_frames", settings.ai_demo_max_frames, 4, 100),
                                    ("ai_demo_max_rounds", settings.ai_demo_max_rounds, 1, 10)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ScriptValidationError(f"設定 {label} 必須是 {low}～{high} 的整數: {value!r}")
    if not isinstance(settings.auto_update, bool):
        raise ScriptValidationError(f"設定 auto_update 必須是布林值: {settings.auto_update!r}")
    return replace(settings, toggle_key=toggle, stop_key=stop,
                   discord_webhook_url=webhook, ai_provider=ai_provider,
                   ai_auth_mode=ai_auth_mode, ai_auth_profile=ai_profile,
                   ai_model=ai_model, ai_api_key=ai_key)


def ocr_lang_from_setting(value: str) -> str | None:
    """相容舊設定／平台工廠參數；新版固定 v6 模型不使用此值選擇模型。"""
    value = value.strip()
    if not value or value == "auto":
        return None
    return value


class SettingsStore:
    def __init__(self, root: str | Path):
        self._path = Path(root) / "settings.json"

    def load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return validate_settings(Settings(**data))
        except Exception as e:
            logger.warning("設定檔載入失敗，改用預設值：%s", e)
            return Settings()

    def save(self, settings: Settings) -> Path:
        validate_settings(settings)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
        except OSError as e:
            raise ScriptValidationError(f"設定無法儲存: {e}") from e
        return self._path
