import pytest
from keyboard_executor.core.models import ScriptValidationError, script_from_dict, script_to_dict
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict, sequence_config_to_dict
from tests.core.test_sequence_input_config import config_data, script_data


def test_panel_only_requires_one_region_and_roundtrips():
    data = dict(enabled=True, mode="panel", panel_region=[10, 20, 400, 300])
    config = sequence_config_from_dict(data)
    assert config.panel_region == (10, 20, 400, 300)
    assert config.input_point is None
    assert sequence_config_to_dict(config) == data
    script = script_data()
    script['settings']['sequence_input'] = data
    assert script_to_dict(script_from_dict(script))['settings']['sequence_input'] == data


def test_manual_wire_format_unchanged():
    assert sequence_config_to_dict(sequence_config_from_dict(config_data())) == config_data()


def test_disabled_panel_can_be_incomplete():
    assert sequence_config_from_dict(dict(mode="panel", enabled=False)).panel_region is None


@pytest.mark.parametrize('extra', [dict(mode='other'), dict(mode=True),
    dict(panel_region=None), dict(panel_region=[True, 0, 10, 10]),
    dict(panel_region=[0, 0, 0, 10]), dict(panel_region=[0, -1, 10, 10]),
    dict(panel_region=[0, 0, 1.5, 10]), dict(input_point=[10, 10]), dict(timeout_sec=60)])
def test_invalid_panel_rejected(extra):
    with pytest.raises(ScriptValidationError):
        sequence_config_from_dict(dict(enabled=True, mode='panel', panel_region=[0, 0, 400, 300]) | extra)


@pytest.mark.parametrize('changes', [dict(mode='invalid'), dict(panel_region=(0, 0, 400, 300))])
def test_editor_rejects_invalid_dataclass_without_losing_original(changes):
    from dataclasses import replace
    from keyboard_executor.app.script_editor_model import ScriptEditorModel
    model = ScriptEditorModel(script_from_dict(script_data()))
    before = model.sequence_input
    with pytest.raises(ScriptValidationError):
        model.set_sequence_input(replace(before, **changes))
    assert model.sequence_input == before


def test_manual_cannot_silently_ignore_panel_region():
    with pytest.raises(ScriptValidationError):
        sequence_config_from_dict(config_data() | dict(panel_region=[0, 0, 400, 300]))
