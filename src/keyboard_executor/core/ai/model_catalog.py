"""AI model choices shown by the settings UI.

Fallbacks verified against official docs on 2026-09-30:
https://developers.openai.com/codex/models
https://code.claude.com/docs/en/model-config
Codex model/list supplies account-specific choices; manual IDs remain editable.
"""
from __future__ import annotations


SUBSCRIPTION_MODEL_OPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "openai": (
        ("ChatGPT 自動選擇（推薦）", ""),
        ("GPT-6.1 Sol", "gpt-6.1-sol"),
        ("GPT-6 Astra", "gpt-6-astra"),
        ("GPT-6 Sol", "gpt-6-sol"),
        ("GPT-6 Luna", "gpt-6-luna"),
        ("GPT-5.6 Sol（精細）", "gpt-5.6-sol"),
        ("GPT-5.6 Terra（均衡）", "gpt-5.6-terra"),
        ("GPT-5.6 Luna（快速）", "gpt-5.6-luna"),
    ),
    "anthropic": (
        ("Claude 自動選擇（推薦）", ""),
        ("Claude Sonnet（跟隨 CLI 最新版）", "sonnet"),
        ("Claude Opus（跟隨 CLI 最新版）", "opus"),
        ("Claude Fable（長時間複雜任務）", "fable"),
        ("Claude Haiku（快速）", "haiku"),
        ("Claude Sonnet 5.5", "claude-sonnet-5-5"),
        ("Claude Opus 5.5", "claude-opus-5-5"),
        ("Claude Fable 5.1", "claude-fable-5-1"),
    ),
}


def subscription_model_options(provider: str) -> tuple[tuple[str, str], ...]:
    return SUBSCRIPTION_MODEL_OPTIONS.get(provider, ())
