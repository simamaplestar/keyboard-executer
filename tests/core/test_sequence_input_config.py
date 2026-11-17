from dataclasses import replace
import pytest
from keyboard_executor.core.models import ScriptValidationError, script_from_dict, script_to_dict
from keyboard_executor.app.script_editor_model import ScriptEditorModel


def config_data():
    return dict(enabled=True, prompt_region=[10, 10, 300, 50],
                image_region=[30, 70, 130, 130], input_point=[80, 220],
                confirm_point=[330, 220], prompt_text="請按照號碼順序輸入文字")


def script_data():
    return dict(name="順序輸入", target_window={"title_pattern": "記事本"},
                settings={"sequence_input": config_data()},
                actions=[{"type": "key_press", "key": "a"}])


def test_round_trip_and_old_script_default():
    data = script_data()
    script = script_from_dict(data)
    assert script_to_dict(script)["settings"]["sequence_input"] == config_data()
    data["settings"] = {}
    assert script_from_dict(data).settings.sequence_input is None


@pytest.mark.parametrize("field,value", [
    ("input_point", [True, 2]), ("input_point", [-1, 2]),
    ("confirm_point", [1.2, 2]), ("confirm_point", [1]),
    ("input_point", "1,2"), ("prompt_region", [0, 0, 0, 2]),
    ("image_region", None), ("enabled", 1), ("prompt_text", " "),
    ("timeout_sec", 60), ("image_region", [0, 0, True, 20]),
])
def test_invalid_config_rejected(field, value):
    data = script_data()
    data["settings"]["sequence_input"][field] = value
    with pytest.raises(ScriptValidationError):
        script_from_dict(data)


def test_disabled_can_be_incomplete_and_settings_are_atomic():
    from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
    assert not sequence_config_from_dict({"enabled": False}).enabled
    model = ScriptEditorModel(script_from_dict(script_data()))
    before = model.sequence_input
    with pytest.raises(ScriptValidationError):
        model.set_sequence_input(replace(before, input_point=(-1, 0)))
    assert model.sequence_input == before
    model.set_sequence_input(None)
    assert "sequence_input" not in script_to_dict(model.to_script())["settings"]
