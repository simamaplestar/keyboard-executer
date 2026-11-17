import logging
from keyboard_executor.core.models import script_from_dict
from keyboard_executor.storage.scripts import ScriptStorage
from tests.core.test_sequence_input_config import script_data


def panel_script():
    data = script_data()
    data['settings']['sequence_input'] = dict(enabled=True, mode='panel', panel_region=[0, 0, 400, 300])
    return script_from_dict(data)


def test_cli_panel_requires_runtime(tmp_path, capsys):
    from keyboard_executor.cli import main
    from tests.core.test_player_flow import make_platform
    platform, backend = make_platform()
    ScriptStorage(tmp_path).save(panel_script())
    assert main(['play', '順序輸入', '--dir', str(tmp_path)], check_permissions=lambda: True,
                get_platform=lambda **kw: platform, guard_starter=lambda p: None) == 1
    assert '圖片順序輸入' in capsys.readouterr().err
    assert not backend.calls


def test_rule_panel_requires_runtime(caplog):
    from tests.core.test_rule_engine import make_platform, FakeScreenCapture, FakeOcrEngine, tbox, DictStorage, text_rule
    from keyboard_executor.core.rule_engine import RuleEngine
    platform = make_platform(FakeScreenCapture(), FakeOcrEngine([tbox('連線中斷')]))
    script = panel_script()
    engine = RuleEngine(platform, DictStorage({script.name: script}))
    with caplog.at_level(logging.WARNING):
        engine.evaluate_once([text_rule(trigger={'type': 'run_script', 'script_name': script.name})])
    assert '圖片順序輸入' in caplog.text
    assert not platform.input_backend.calls


def test_panel_export_import_excludes_credentials(tmp_path):
    from tests.storage.test_transfer_service import make_service
    source, target = tmp_path/'src', tmp_path/'dst'
    ScriptStorage(source).save(panel_script())
    (source/'settings.json').write_text('{"ai_api_key":"private-key"}', encoding='utf-8')
    out = tmp_path/'export.json'
    make_service(source).export(out, ['順序輸入'], [])
    assert 'private-key' not in out.read_text(encoding='utf-8')
    service = make_service(target)
    service.apply(service.read(out))
    config = ScriptStorage(target).load('順序輸入').settings.sequence_input
    assert config.mode == 'panel'
    assert config.panel_region == (0, 0, 400, 300)
    assert config.input_point is None
