"""OpenRouter 的 OpenAI 相容 Chat Completions 串流介面。"""
from __future__ import annotations

from keyboard_executor.core.ai.openai_provider import OpenAiProvider


class OpenRouterProvider(OpenAiProvider):
    def __init__(self, api_key: str, model: str, opener=None):
        super().__init__(api_key, model, opener,
                         endpoint="https://openrouter.ai/api/v1/chat/completions")
