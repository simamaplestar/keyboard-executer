import pytest

from keyboard_executor.cli import main
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import PlayResult
from keyboard_executor.storage.scripts import ScriptStorage


class FakePlayer:
    def __init__(self, result):
        self._result = result
        self.played = []
        import threading
        self.stop_event = threading.Event()

    def play(self, script):
        self.played.append(script.name)
        return self._result


def save_script(tmp_path, name="簽到"):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": name,
        "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}],
    }))
    return storage


def test_list_empty_prints_placeholder(tmp_path, capsys):
    code = main(["list", "--dir", str(tmp_path)])
    assert code == 0
    assert "（沒有腳本）" in capsys.readouterr().out


def test_list_nonempty_prints_names(tmp_path, capsys):
    save_script(tmp_path, "甲")
    save_script(tmp_path, "乙")
    code = main(["list", "--dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "甲" in out and "乙" in out


def test_play_load_error_exits_1(tmp_path, capsys):
    code = main(["play", "不存在", "--dir", str(tmp_path)],
                check_permissions=lambda: True)
    assert code == 1
    assert "腳本載入失敗" in capsys.readouterr().err


def test_play_happy_dispatch_returns_0(tmp_path, capsys):
    save_script(tmp_path, "甲")
    player = FakePlayer(PlayResult(ok=True, actions_run=1))
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                player_factory=lambda *a, **k: player,
                guard_starter=lambda p: None)
    assert code == 0
    assert player.played == ["甲"]
    assert "回放完成" in capsys.readouterr().out


def test_play_dispatch_passes_templates_loader(tmp_path):
    """C1：play 分支必須把 templates loader 接進 player_factory，否則 wait_image/
    if_image/click_image 一律以「未提供模板來源」中止（見 Player._load_template）。"""
    save_script(tmp_path, "甲")
    player = FakePlayer(PlayResult(ok=True, actions_run=1))
    captured = {}

    def spy_player_factory(*args, **kwargs):
        captured["kwargs"] = kwargs
        return player

    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                player_factory=spy_player_factory,
                guard_starter=lambda p: None)
    assert code == 0
    assert captured["kwargs"].get("templates") is not None


def test_cli_rejects_sequence_input_without_silent_fallback(tmp_path, capsys):
    from tests.core.test_sequence_input_config import script_data
    from tests.core.test_player_flow import make_platform
    platform, backend = make_platform()
    ScriptStorage(tmp_path).save(script_from_dict(script_data()))
    code = main(["play", "順序輸入", "--dir", str(tmp_path)],
                check_permissions=lambda: True, get_platform=lambda **kw: platform,
                guard_starter=lambda p: None)
    assert code == 1
    assert "圖片順序輸入" in capsys.readouterr().err
    assert not backend.calls


def test_play_result_failure_exits_1(tmp_path, capsys):
    save_script(tmp_path, "甲")
    player = FakePlayer(PlayResult(ok=False, actions_run=2, error="視窗已關閉"))
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                player_factory=lambda *a, **k: player,
                guard_starter=lambda p: None)
    assert code == 1
    assert "回放中止" in capsys.readouterr().err


def test_play_permission_denied_blocks(tmp_path):
    save_script(tmp_path, "甲")
    called = []
    code = main(["play", "甲", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                player_factory=lambda *a, **k: called.append(1) or FakePlayer(None))
    assert code == 1
    assert called == []  # 權限擋下，不建 Player


def test_record_dispatches_to_run_record(tmp_path):
    seen = {}

    def spy_run_record(platform, storage, hook, *, title_pattern, full_trajectory):
        seen["title"] = title_pattern
        seen["full"] = full_trajectory
        return 0

    code = main(["record", "--dir", str(tmp_path), "--title", "記事本.*",
                 "--full-trajectory"],
                check_permissions=lambda: True,
                get_platform=lambda **k: object(),
                hook_factory=lambda: object(),
                run_record_fn=spy_run_record)
    assert code == 0
    assert seen == {"title": "記事本.*", "full": True}


def test_record_permission_denied_blocks(tmp_path):
    called = []
    code = main(["record", "--dir", str(tmp_path)],
                check_permissions=lambda: False,
                run_record_fn=lambda *a, **k: called.append(1) or 0)
    assert code == 1
    assert called == []


def test_main_sets_up_rolling_log_under_data_dir(tmp_path):
    main(["list", "--dir", str(tmp_path)])
    assert (tmp_path / "logs" / "app.log").exists()
