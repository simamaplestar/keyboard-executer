import logging

import pytest

from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
from keyboard_executor.storage.rules import RuleStorage


def make_rule(name="規則", enabled=True):
    return rule_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "condition": {"type": "text", "pattern": "x"},
        "trigger": {"type": "stop_all"},
        "enabled": enabled,
    })


def test_save_then_load_in_rules_subdir(tmp_path):
    storage = RuleStorage(tmp_path)
    path = storage.save(make_rule("甲"))
    assert path == tmp_path / "rules" / "甲.json"
    assert path.exists()
    assert storage.load("甲") == make_rule("甲")


def test_load_missing_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到規則"):
        RuleStorage(tmp_path).load("無")


def test_load_broken_json_raises(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "壞.json").write_text("{壞", encoding="utf-8")
    with pytest.raises(ScriptValidationError, match="JSON"):
        RuleStorage(tmp_path).load("壞")


def test_load_enabled_filters_disabled(tmp_path):
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("開", enabled=True))
    storage.save(make_rule("關", enabled=False))
    names = [r.name for r in storage.load_enabled()]
    assert names == ["開"]


def test_save_oserror_wrapped(tmp_path, monkeypatch):
    storage = RuleStorage(tmp_path)
    monkeypatch.setattr("pathlib.Path.write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("滿")))
    with pytest.raises(ScriptValidationError, match="無法儲存"):
        storage.save(make_rule("甲"))


def test_load_non_utf8_file_raises_validation_error(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "big5.json").write_bytes('{"name": "規則"}'.encode("cp950"))
    with pytest.raises(ScriptValidationError, match="無法讀取|JSON"):
        RuleStorage(tmp_path).load("big5")


def test_load_enabled_skips_corrupt_file_and_keeps_others(tmp_path, caplog):
    """單一規則檔損毀（防守式逐檔載入）：不得讓 load_enabled() 整批拋例外，
    其餘規則仍正常載入，且損毀檔案要記錄（不可靜默）。"""
    caplog.set_level(logging.WARNING, logger="keyboard_executor.storage.rules")
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("好"))
    (tmp_path / "rules" / "壞.json").write_text("{壞", encoding="utf-8")
    names = [r.name for r in storage.load_enabled()]
    assert names == ["好"]
    assert "壞" in caplog.text
    assert "跳過" in caplog.text


def test_delete_removes_rule_file(tmp_path):
    storage = RuleStorage(tmp_path)
    storage.save(make_rule("刪我"))
    assert storage.list_names() == ["刪我"]
    storage.delete("刪我")
    assert storage.list_names() == []


def test_delete_missing_rule_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到規則"):
        RuleStorage(tmp_path).delete("無")
