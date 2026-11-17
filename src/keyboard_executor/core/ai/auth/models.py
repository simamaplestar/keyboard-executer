"""訂閱認證的純資料模型；不得在 repr/log 中暴露 token。"""
from __future__ import annotations

from dataclasses import dataclass, field


class AuthError(Exception):
    """可安全顯示的訂閱認證錯誤。"""


@dataclass(frozen=True, repr=False)
class AuthProfile:
    provider: str
    profile_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    expires_at: float | None = None
    account_id: str = ""
    source: str = ""

    def __repr__(self) -> str:
        return (f"AuthProfile(provider={self.provider!r}, "
                f"profile_id={self.profile_id!r}, expires_at={self.expires_at!r}, "
                f"account_id={self.account_id!r}, source={self.source!r})")


@dataclass(frozen=True)
class AuthStatus:
    configured: bool
    expired: bool = False
    provider: str = ""
    profile_id: str = ""
    source: str = ""
    account_label: str = ""
