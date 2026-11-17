import pytest

from keyboard_executor.core.models import ScriptValidationError, script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage


def make_script(name="測試"):
    return script_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "text_input", "text": "哈囉"}],
    })


def test_list_names_excludes_settings_json(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    storage.save(make_script("甲"))
    (tmp_path / "scripts" / "settings.json").write_text("{}", encoding="utf-8")
    assert storage.list_names() == ["甲"]        # settings.json 不是腳本


def test_reserved_settings_name_rejected(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    with pytest.raises(ScriptValidationError):
        storage.save(make_script("settings"))    # 不可覆蓋設定檔


def test_layout_sidecar_roundtrip_and_isolated(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    storage.save(make_script("甲"))
    storage.save_layout("甲", {"positions": [[1, 2], [3, 4]], "zoom": 1.2})
    assert storage.load_layout("甲") == {"positions": [[1, 2], [3, 4]], "zoom": 1.2}
    assert storage.load_layout("不存在") is None
    assert storage.list_names() == ["甲"]          # sidecar 不污染腳本清單


def test_delete_also_removes_layout(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    storage.save(make_script("乙"))
    storage.save_layout("乙", {"positions": [[0, 0]]})
    storage.delete("乙")
    assert storage.load_layout("乙") is None


def test_save_then_load_round_trip(tmp_path):
    storage = ScriptStorage(tmp_path / "scripts")
    script = make_script()
    path = storage.save(script)
    assert path.exists()
    loaded = storage.load("測試")
    assert loaded == script


def test_saved_json_is_human_readable_utf8(tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(make_script())
    text = (tmp_path / "測試.json").read_text(encoding="utf-8")
    assert "哈囉" in text          # ensure_ascii=False
    assert "\n  " in text          # indent=2


def test_load_missing_raises(tmp_path):
    storage = ScriptStorage(tmp_path)
    with pytest.raises(ScriptValidationError, match="找不到腳本"):
        storage.load("不存在")


def test_load_broken_json_raises(tmp_path):
    (tmp_path / "壞.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ScriptValidationError, match="JSON"):
        ScriptStorage(tmp_path).load("壞")


def test_load_invalid_script_raises(tmp_path):
    (tmp_path / "缺.json").write_text('{"name": "缺"}', encoding="utf-8")
    with pytest.raises(ScriptValidationError):
        ScriptStorage(tmp_path).load("缺")


def test_list_names_sorted(tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(make_script("b"))
    storage.save(make_script("a"))
    (tmp_path / "not-a-script.txt").write_text("x", encoding="utf-8")
    assert storage.list_names() == ["a", "b"]


def test_load_non_utf8_file_raises_validation_error(tmp_path):
    (tmp_path / "big5.json").write_bytes('{"name": "測試"}'.encode("cp950"))
    with pytest.raises(ScriptValidationError, match="無法讀取|JSON"):
        ScriptStorage(tmp_path).load("big5")


def test_path_traversal_name_rejected(tmp_path):
    storage = ScriptStorage(tmp_path)
    with pytest.raises(ScriptValidationError, match="名稱不合法"):
        storage.load("../evil")
    with pytest.raises(ScriptValidationError, match="名稱不合法"):
        storage.path_for("a/b")


def test_save_oserror_wrapped_as_validation_error(tmp_path, monkeypatch):
    storage = ScriptStorage(tmp_path)

    def boom(*a, **k):
        raise OSError("磁碟已滿")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(ScriptValidationError, match="無法儲存"):
        storage.save(make_script("甲"))


def test_delete_removes_script_file(tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(make_script("刪我"))
    assert storage.list_names() == ["刪我"]
    storage.delete("刪我")
    assert storage.list_names() == []
    assert not (tmp_path / "刪我.json").exists()


def test_delete_missing_script_raises(tmp_path):
    with pytest.raises(ScriptValidationError, match="找不到腳本"):
        ScriptStorage(tmp_path).delete("無")
