from keyboard_executor.app.naming import unique_copy_name


def test_no_conflict_returns_base_copy():
    assert unique_copy_name("甲", ["乙"]) == "甲 - 複製"


def test_single_conflict_appends_2():
    assert unique_copy_name("甲", ["甲", "甲 - 複製"]) == "甲 - 複製 2"


def test_multi_conflict_finds_next_free_number():
    assert unique_copy_name("甲", ["甲 - 複製", "甲 - 複製 2"]) == "甲 - 複製 3"


def test_numbered_name_adds_suffix_on_conflict():
    from keyboard_executor.app.naming import numbered_name
    assert numbered_name("練功", []) == "練功"
    assert numbered_name("練功", ["練功"]) == "練功 2"
    assert numbered_name("練功", ["練功", "練功 2"]) == "練功 3"


def test_numbered_name_ignores_case():
    """Windows 檔名不分大小寫：Farm 已存在時 farm 也要加序號，不能覆蓋。"""
    from keyboard_executor.app.naming import numbered_name
    assert numbered_name("farm", ["Farm"]) == "farm 2"
    assert numbered_name("farm", ["Farm", "FARM 2"]) == "farm 3"
