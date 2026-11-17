from keyboard_executor.core.ai.auth.models import AuthProfile
from keyboard_executor.core.ai.auth.secret_store import MemorySecretStore


def test_auth_profile_repr_never_contains_tokens():
    profile = AuthProfile("openai", "default", "access-secret",
                          "refresh-secret", 123.0, "acct", "openai_oauth")
    shown = repr(profile)
    assert "access-secret" not in shown and "refresh-secret" not in shown
    assert "openai_oauth" in shown


def test_memory_secret_store_round_trip_and_delete():
    store = MemorySecretStore()
    profile = AuthProfile("openai", "default", "a", "r")
    assert store.get("openai", "default") is None
    store.put(profile)
    assert store.get("openai", "default") == profile
    store.delete("openai", "default")
    assert store.get("openai", "default") is None
