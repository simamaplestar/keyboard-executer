"""OAuth token 儲存；Windows 使用 Credential Manager，macOS 使用 Keychain。"""
from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from dataclasses import asdict
from typing import Protocol

from keyboard_executor.core.ai.auth.models import AuthProfile

_PREFIX = "KeyboardExecutor/ai"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


class SecretStoreError(Exception):
    """安全憑證儲存失敗；訊息不得包含 credential 內容。"""


class SecretStore(Protocol):
    def get(self, provider: str, profile_id: str) -> AuthProfile | None: ...
    def put(self, profile: AuthProfile) -> None: ...
    def delete(self, provider: str, profile_id: str) -> None: ...


class MemorySecretStore:
    """測試／暫存用；不落盤。"""

    def __init__(self) -> None:
        self._profiles: dict[tuple[str, str], AuthProfile] = {}

    def get(self, provider: str, profile_id: str) -> AuthProfile | None:
        return self._profiles.get((provider, profile_id))

    def put(self, profile: AuthProfile) -> None:
        self._profiles[(profile.provider, profile.profile_id)] = profile

    def delete(self, provider: str, profile_id: str) -> None:
        self._profiles.pop((provider, profile_id), None)


class UnavailableSecretStore:
    def _fail(self):
        raise SecretStoreError("此平台尚未提供安全憑證儲存")

    def get(self, provider: str, profile_id: str):
        self._fail()

    def put(self, profile: AuthProfile) -> None:
        self._fail()

    def delete(self, provider: str, profile_id: str) -> None:
        self._fail()


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _target(provider: str, profile_id: str) -> str:
    if not provider or not profile_id or any(c in provider + profile_id for c in "\r\n"):
        raise SecretStoreError("憑證識別資訊不合法")
    return f"{_PREFIX}/{provider}/{profile_id}"


class WindowsCredentialStore:
    def __init__(self, advapi32=None) -> None:
        if advapi32 is None:
            if sys.platform != "win32":
                raise SecretStoreError("此平台尚未提供安全憑證儲存")
            advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._api = advapi32

    def put(self, profile: AuthProfile) -> None:
        raw = json.dumps(asdict(profile), ensure_ascii=False).encode("utf-8")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        cred = _CREDENTIALW(Type=_CRED_TYPE_GENERIC,
                            TargetName=_target(profile.provider, profile.profile_id),
                            CredentialBlobSize=len(raw), CredentialBlob=blob,
                            Persist=_CRED_PERSIST_LOCAL_MACHINE,
                            UserName=profile.profile_id)
        try:
            ok = self._api.CredWriteW(ctypes.byref(cred), 0)
        except Exception as exc:
            raise SecretStoreError("Windows Credential Manager 寫入失敗") from exc
        if not ok:
            raise SecretStoreError("Windows Credential Manager 寫入失敗")

    def get(self, provider: str, profile_id: str) -> AuthProfile | None:
        ptr = ctypes.POINTER(_CREDENTIALW)()
        try:
            ok = self._api.CredReadW(_target(provider, profile_id),
                                     _CRED_TYPE_GENERIC, 0, ctypes.byref(ptr))
        except Exception as exc:
            raise SecretStoreError("Windows Credential Manager 讀取失敗") from exc
        if not ok:
            # ERROR_NOT_FOUND
            if ctypes.get_last_error() == 1168:
                return None
            raise SecretStoreError("Windows Credential Manager 讀取失敗")
        try:
            cred = ptr.contents
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            data = json.loads(raw.decode("utf-8"))
            return AuthProfile(**data)
        except Exception as exc:
            raise SecretStoreError("儲存的 AI 登入憑證無法解析") from exc
        finally:
            self._api.CredFree(ptr)

    def delete(self, provider: str, profile_id: str) -> None:
        try:
            ok = self._api.CredDeleteW(_target(provider, profile_id),
                                       _CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            raise SecretStoreError("Windows Credential Manager 刪除失敗") from exc
        if not ok and ctypes.get_last_error() != 1168:
            raise SecretStoreError("Windows Credential Manager 刪除失敗")


class MacOSKeychainStore:
    """直接指定原生 Keychain 後端，避免落入其他可明文儲存的 keyring 後端。"""

    def __init__(self, backend=None) -> None:
        self._backend = backend

    def _keychain(self):
        if self._backend is None:
            from keyring.backends.macOS import Keyring
            self._backend = Keyring()
        return self._backend

    def get(self, provider: str, profile_id: str) -> AuthProfile | None:
        target = _target(provider, profile_id)
        try:
            raw = self._keychain().get_password(target, profile_id)
            if raw is None:
                return None
            profile = AuthProfile(**json.loads(raw))
            if (profile.provider, profile.profile_id) != (provider, profile_id):
                raise ValueError("憑證身分不符")
            return profile
        except Exception:
            raise SecretStoreError("macOS Keychain 讀取失敗，請確認鑰匙圈已解鎖並允許存取") from None

    def put(self, profile: AuthProfile) -> None:
        target = _target(profile.provider, profile.profile_id)
        try:
            raw = json.dumps(asdict(profile), ensure_ascii=False)
            self._keychain().set_password(target, profile.profile_id, raw)
        except Exception:
            raise SecretStoreError("macOS Keychain 寫入失敗，請確認鑰匙圈已解鎖並允許存取") from None

    def delete(self, provider: str, profile_id: str) -> None:
        target = _target(provider, profile_id)
        try:
            backend = self._keychain()
            if backend.get_password(target, profile_id) is not None:
                backend.delete_password(target, profile_id)
        except Exception:
            raise SecretStoreError("macOS Keychain 刪除失敗，請確認鑰匙圈已解鎖並允許存取") from None


def default_secret_store() -> SecretStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    if sys.platform == "darwin":
        return MacOSKeychainStore()
    return UnavailableSecretStore()
