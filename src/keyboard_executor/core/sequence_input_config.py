"""Numbered-image input settings; fixed timing policy is not script-overridable."""
from dataclasses import asdict, dataclass
from functools import lru_cache
import unicodedata

SAMPLE_INTERVAL_SEC = 1.0
TOTAL_TIMEOUT_SEC = 30.0
SUBMIT_CUTOFF_SEC = 18.0
CONFIRM_CUTOFF_SEC = 20.0
MAX_FRAMES = 30


@lru_cache(maxsize=1)
def _prompt_converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def normalize_prompt(text: str) -> str:
    """Canonical comparison only; never rewrite raw OCR or the stored prompt."""
    text = _prompt_converter().convert(unicodedata.normalize('NFKC', text))
    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


@dataclass(frozen=True)
class SequenceInputConfig:
    enabled: bool = False
    prompt_region: tuple[int, int, int, int] | None = None
    image_region: tuple[int, int, int, int] | None = None
    input_point: tuple[int, int] | None = None
    confirm_point: tuple[int, int] | None = None
    prompt_text: str = "請按照號碼順序輸入文字"
    mode: str = "manual"
    panel_region: tuple[int, int, int, int] | None = None


def sequence_config_from_dict(data: dict) -> SequenceInputConfig:
    from keyboard_executor.core.models import ScriptValidationError

    def fail(detail):
        raise ScriptValidationError(f"圖片順序輸入：{detail}")

    if not isinstance(data, dict):
        fail("設定必須是物件")
    defaults = asdict(SequenceInputConfig())
    if set(data) - set(defaults):
        fail("含不支援的設定欄位")
    values = defaults | data
    if type(values["enabled"]) is not bool:
        fail("啟用必須是布林值")
    mode = values["mode"]
    if not isinstance(mode, str) or mode not in {"manual", "panel"}:
        fail("模式必須是 manual 或 panel")
    if mode == "panel":
        if any(values[name] is not None for name in ("prompt_region", "image_region", "input_point", "confirm_point")):
            fail("完整面板模式不可混用手動座標")
        region = values["panel_region"]
        if region is None and not values["enabled"]:
            return SequenceInputConfig(enabled=False, mode="panel")
        if (not isinstance(region, (tuple, list)) or len(region) != 4
                or any(type(v) is not int or v < 0 for v in region)
                or region[2] == 0 or region[3] == 0):
            fail("panel_region 必須是有效的視窗相對區域")
        return SequenceInputConfig(enabled=values["enabled"], mode="panel", panel_region=tuple(region))
    if values["panel_region"] is not None:
        fail("手動模式不可混用完整面板區域")
    text = values["prompt_text"]
    if not isinstance(text, str) or not normalize_prompt(text):
        fail("提示文字不可只有空白或標點")
    values["prompt_text"] = text.strip()
    for name, size in (("prompt_region", 4), ("image_region", 4),
                       ("input_point", 2), ("confirm_point", 2)):
        value = values[name]
        if value is None and not values["enabled"]:
            continue
        if (not isinstance(value, (tuple, list)) or len(value) != size
                or any(type(v) is not int or v < 0 for v in value)
                or size == 4 and (value[2] == 0 or value[3] == 0)):
            fail(f"{name} 必須是有效的視窗相對座標")
        values[name] = tuple(value)
    return SequenceInputConfig(**values)


def sequence_config_to_dict(config: SequenceInputConfig) -> dict:
    # Validate before omitting fields: otherwise invalid mixed-mode dataclasses
    # could bypass the editor's atomic validation through serialization.
    config = sequence_config_from_dict(asdict(config))
    if config.mode == "panel":
        return dict(enabled=config.enabled, mode="panel",
                    panel_region=list(config.panel_region) if config.panel_region is not None else None)
    return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(config).items()
            if k not in {"mode", "panel_region"}}
