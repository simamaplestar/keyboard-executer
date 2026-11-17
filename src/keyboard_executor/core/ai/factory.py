"""依設定建立 ChatProvider；providers 不互相 import，工廠獨立一檔避免循環。"""
from __future__ import annotations

from keyboard_executor.core.ai.anthropic_provider import AnthropicProvider
from keyboard_executor.core.ai.auth.models import AuthProfile
from keyboard_executor.core.ai.claude_subscription_provider import ClaudeSubscriptionProvider
from keyboard_executor.core.ai.openai_provider import OpenAiProvider
from keyboard_executor.core.ai.openai_subscription_provider import OpenAiSubscriptionProvider
from keyboard_executor.core.ai.openrouter_provider import OpenRouterProvider
from keyboard_executor.core.ai.provider import ChatProvider


def make_provider(provider: str, api_key: str, model: str, *,
                  auth_mode: str = "api_key",
                  auth_profile: AuthProfile | None = None,
                  reasoning_effort: str | None = None) -> ChatProvider | None:
    if auth_mode == "subscription":
        if provider == "openai":
            return OpenAiSubscriptionProvider(model=model, reasoning_effort=reasoning_effort)
        if provider == "anthropic":
            return ClaudeSubscriptionProvider(
                model=model,
                oauth_token=auth_profile.access_token if auth_profile else "")
        return None
    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if provider == "openai":
        return OpenAiProvider(api_key=api_key, model=model)
    if provider == "openrouter":
        return OpenRouterProvider(api_key=api_key, model=model)
    return None
