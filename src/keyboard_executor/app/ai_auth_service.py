"""設定頁與 core 認證元件之間的薄協調層。"""
from __future__ import annotations

from keyboard_executor.app.settings import Settings
from keyboard_executor.core.ai.auth.claude_auth import ClaudeAuthManager
from keyboard_executor.core.ai.auth.codex_account import CodexAuthManager
from keyboard_executor.core.ai.auth.models import AuthProfile, AuthStatus
from keyboard_executor.core.ai.auth.secret_store import SecretStore, default_secret_store


class AiAuthService:
    def __init__(self, *, secret_store: SecretStore | None = None,
                 codex: CodexAuthManager | None = None,
                 claude: ClaudeAuthManager | None = None) -> None:
        self.secret_store = secret_store or default_secret_store()
        self.codex = codex or CodexAuthManager()
        self.claude = claude or ClaudeAuthManager(self.secret_store)

    def status(self, provider: str, profile_id: str = "") -> AuthStatus:
        if provider == "openai":
            return self.codex.status(refresh=False)
        if provider == "anthropic":
            if profile_id == "setup-token":
                return self.claude.setup_token_status()
            return self.claude.cli_status()
        return AuthStatus(configured=False)

    def login_openai(self, *, device_code=False, on_info=None,
                     should_abort=None) -> AuthStatus:
        return self.codex.login(device_code=device_code, on_info=on_info,
                                should_abort=should_abort)

    def login_claude(self, *, should_abort=None) -> AuthStatus:
        return self.claude.login_cli(should_abort=should_abort)

    def list_openai_models(self) -> tuple[tuple[str, str], ...]:
        return self.codex.list_models()

    def save_claude_token(self, token: str) -> AuthStatus:
        return self.claude.save_setup_token(token)

    def logout(self, provider: str, profile_id: str) -> None:
        if provider == "openai":
            self.codex.logout()
        elif provider == "anthropic":
            self.claude.logout(profile_id)

    def resolve_profile(self, settings: Settings) -> AuthProfile | None:
        if settings.ai_auth_mode != "subscription":
            return None
        if settings.ai_provider == "openai":
            if settings.ai_auth_profile != "codex":
                return None
            # OpenAI app-server owns the secret. This sentinel carries no token.
            return AuthProfile("openai", "codex", "", source="codex_app_server")
        if settings.ai_provider == "anthropic":
            if settings.ai_auth_profile == "setup-token":
                return self.claude.get_setup_profile()
            if settings.ai_auth_profile == "claude-cli":
                return AuthProfile("anthropic", "claude-cli", "", source="claude_cli")
            return None
        return None
