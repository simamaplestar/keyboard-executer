"""Conversation persistence uses temporary directories, never user history."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from keyboard_executor.core.chat_observer import ChatMessage


def store_at(root):
    from keyboard_executor.storage.chat_history import ChatHistoryStore
    return ChatHistoryStore(root)


def message(index, *, player="朋友", owner="自己", incoming=True):
    return ChatMessage(index, "whisper", player if incoming else owner,
                       f"聊天 {index}", incoming, "" if incoming else player)


def test_missing_history_is_empty_without_creating_directory(tmp_path):
    root = tmp_path / "absent"
    assert store_at(root).load("自己") == {}
    assert not root.exists()


def test_restart_loads_last_50_incoming_and_own_replies_per_player(tmp_path):
    store = store_at(tmp_path)
    for index in range(58):
        store.append("自己", "朋友", message(index, incoming=index % 2 == 0))
    other = ChatMessage(101, "map", "另一位", "一起打嗎")
    store.append("自己", "另一位", other)

    restored = store_at(tmp_path).load("自己")
    assert [item.id for item in restored["朋友"]] == list(range(8, 58))
    assert sum(item.incoming for item in restored["朋友"]) == 25
    assert restored["朋友"][-1] == message(57, incoming=False)
    assert restored["另一位"] == [other]
    assert len(list(tmp_path.rglob("*.json"))) == 2
    restored["朋友"].clear()
    assert len(store.load("自己")["朋友"]) == 50


def test_normalized_owners_are_isolated_and_exact_player_names_do_not_merge(tmp_path):
    store = store_at(tmp_path)
    first = message(1, player="Alice", owner="Main")
    lower = message(2, player="alice", owner="Main")
    other_owner = message(3, player="Alice", owner="Other")
    store.append(" Ｍａｉｎ ", " Ａｌｉｃｅ ", first)
    store.append("Main", "alice", lower)
    store.append("Other", "Alice", other_owner)

    assert store_at(tmp_path).load("Main") == {"Alice": [first], "alice": [lower]}
    assert store_at(tmp_path).load("Other") == {"Alice": [other_owner]}
    assert store_at(tmp_path).load("main") == {}


def test_windows_special_names_only_produce_hashed_relative_paths(tmp_path):
    store = store_at(tmp_path)
    owner, player = "../CON:*?", "../../NUL<>|\\"
    record = message(1, player=player, owner=owner)
    store.append(owner, player, record)
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    parts = files[0].relative_to(tmp_path).parts
    assert len(parts) == 2
    assert re.fullmatch(r"[a-f0-9]{64}", parts[0])
    assert re.fullmatch(r"[a-f0-9]{64}\.json", parts[1])
    assert store_at(tmp_path).load(owner) == {player: [record]}


@pytest.mark.parametrize("broken", [b"not-json private-chat", b"\xff", b'{"version": 1}'])
def test_corrupt_player_file_is_preserved_and_cannot_be_overwritten(tmp_path, caplog, broken):
    from keyboard_executor.storage.chat_history import ChatHistoryError
    store = store_at(tmp_path)
    store.append("owner-secret", "player-secret", message(1))
    bad = next(tmp_path.rglob("*.json"))
    bad.write_bytes(broken)
    good = message(2, player="good-player")
    store.append("owner-secret", "good-player", good)

    assert store_at(tmp_path).load("owner-secret") == {"good-player": [good]}
    with pytest.raises(ChatHistoryError):
        store.append("owner-secret", "player-secret", message(3))
    assert bad.read_bytes() == broken
    assert caplog.records
    assert all(secret not in caplog.text for secret in
               ("owner-secret", "player-secret", "private-chat"))


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(player="另一人"),
    lambda data: data.update(self_name="另一角色"),
    lambda data: data.update(version=99),
    lambda data: data["messages"][0].update(incoming="false"),
    lambda data: data["messages"][0].update(text=123),
])
def test_invalid_record_or_identity_never_restores_or_replaces_existing_file(tmp_path, mutate):
    from keyboard_executor.storage.chat_history import ChatHistoryError
    store = store_at(tmp_path)
    store.append("自己", "朋友", message(1))
    path = next(tmp_path.rglob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    assert store.load("自己") == {}
    with pytest.raises(ChatHistoryError):
        store.append("自己", "朋友", message(2))
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_atomic_write_failure_keeps_previous_history_and_cleans_temp_file(tmp_path, monkeypatch, operation):
    from keyboard_executor.storage import chat_history
    store = store_at(tmp_path)
    first = message(1)
    store.append("自己", "朋友", first)
    existing = next(tmp_path.rglob("*.json"))
    before = existing.read_bytes()

    def fail(*_args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(chat_history.os, operation, fail)
    with pytest.raises(OSError):
        store.append("自己", "朋友", message(2))
    assert existing.read_bytes() == before
    assert store_at(tmp_path).load("自己") == {"朋友": [first]}
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [existing]


def test_parallel_appends_on_one_store_do_not_lose_messages(tmp_path):
    store = store_at(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda index: store.append("自己", "朋友", message(index)), range(40)))
    restored = store_at(tmp_path).load("自己")["朋友"]
    assert sorted(item.id for item in restored) == list(range(40))


@pytest.mark.parametrize("owner,player", [(" ", "朋友"), ("自己", " ")])
def test_empty_identity_does_not_create_history(tmp_path, owner, player):
    with pytest.raises(ValueError):
        store_at(tmp_path).append(owner, player, message(1))
    assert list(tmp_path.iterdir()) == []
