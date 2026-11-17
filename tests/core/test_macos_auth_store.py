import json

import pytest

from keyboard_executor.core.ai.auth.models import AuthProfile
from keyboard_executor.core.ai.auth import secret_store


class Keychain:
    def __init__(self):
        self.items = {}

    def get_password(self, service, account):
        return self.items.get((service, account))

    def set_password(self, service, account, password):
        self.items[service, account] = password

    def delete_password(self, service, account):
        del self.items[service, account]


def test_mac_keychain_round_trip_delete_and_provider_isolation():
    backend = Keychain()
    store = secret_store.MacOSKeychainStore(backend=backend)
    profile = AuthProfile("anthropic", "setup-token", "access-secret", source="anthropic_setup_token")
    assert store.get("anthropic", "setup-token") is None
    store.put(profile)
    assert store.get("anthropic", "setup-token") == profile
    assert store.get("openai", "setup-token") is None
    assert list(backend.items) == [("KeyboardExecutor/ai/anthropic/setup-token", "setup-token")]
    store.delete("anthropic", "setup-token")
    assert store.get("anthropic", "setup-token") is None
    store.delete("anthropic", "setup-token")


def test_mac_keychain_rejects_corrupt_or_wrong_identity():
    backend = Keychain()
    store = secret_store.MacOSKeychainStore(backend=backend)
    key = ("KeyboardExecutor/ai/anthropic/setup-token", "setup-token")
    for raw in ["not json", json.dumps({"provider": "openai", "profile_id": "setup-token", "access_token": "x"})]:
        backend.items[key] = raw
        with pytest.raises(secret_store.SecretStoreError):
            store.get("anthropic", "setup-token")


@pytest.mark.parametrize("method,args", [
    ("get", ("anthropic", "setup-token")),
    ("put", (AuthProfile("anthropic", "setup-token", "private-token"),)),
    ("delete", ("anthropic", "setup-token")),
])
def test_mac_keychain_errors_do_not_expose_secret(method, args):
    class LockedKeychain:
        def __getattr__(self, name):
            def fail(*args):
                raise RuntimeError("private-token")
            return fail
    store = secret_store.MacOSKeychainStore(backend=LockedKeychain())
    with pytest.raises(secret_store.SecretStoreError) as error:
        getattr(store, method)(*args)
    assert "private-token" not in str(error.value)
    assert error.value.__suppress_context__


def test_mac_default_store_is_keychain_without_accessing_it(monkeypatch):
    monkeypatch.setattr(secret_store.sys, "platform", "darwin")
    assert isinstance(secret_store.default_secret_store(), secret_store.MacOSKeychainStore)
