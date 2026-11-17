"""Real v6 adapter with fake native models; covers Player and rule OCR consumers."""
import pytest

from keyboard_executor.core.models import rule_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
from tests.core.test_player_vision import make_platform, make_script
from tests.fakes import FakeScreenCapture
from tests.platforms.test_ocr_rapid import native


@pytest.mark.parametrize('kind', ['wait_text', 'if_text', 'click_text'])
def test_player_text_actions_use_the_unified_adapter(native, kind):
    folder, constructions, calls, result = native
    result.txts = ('trigger',)
    engine = RapidOcrEngine(model_dir=folder)
    platform, backend, _ = make_platform(capture=FakeScreenCapture(), ocr=engine)
    action = {'type': kind, 'pattern': 'trigger'}
    if kind == 'if_text':
        action.update(then=[{'type': 'delay', 'ms': 0}], **{'else': []})
    outcome = Player(platform, sleep=lambda _: None).play(make_script([action]))
    assert outcome.ok, outcome.error
    assert len(constructions) == len(calls) == 1
    assert result.txts == ('trigger',)
    if kind == 'click_text':
        assert backend.calls[0][0] == 'mouse_click'


def test_rule_text_condition_uses_same_adapter(native):
    folder, constructions, calls, result = native
    result.txts = ('trigger',)
    platform, backend, _ = make_platform(capture=FakeScreenCapture(), ocr=RapidOcrEngine(model_dir=folder))
    rule = rule_from_dict({'name': 'ocr route', 'target_window': {'title_pattern': '記事本'},
        'condition': {'type': 'text', 'pattern': 'trigger'},
        'interval_sec': 1, 'cooldown_sec': 1, 'trigger': {'type': 'notify', 'message': 'matched'}})
    notes = []
    RuleEngine(platform, storage=None, notifier=notes.append).evaluate_once([rule])
    assert notes == ['matched']
    assert len(constructions) == len(calls) == 1
    assert backend.calls == []


@pytest.mark.parametrize('kind', ['if_text', 'click_text'])
def test_transient_native_failure_preserves_generic_action_tolerance(native, kind):
    folder, _, _, _ = native
    engine = RapidOcrEngine(model_dir=folder)
    def fail(*a, **kw):
        raise RuntimeError('transient native inference failure')
    engine._engine = fail
    platform, backend, _ = make_platform(capture=FakeScreenCapture(), ocr=engine)
    action = {'type': kind, 'pattern': 'trigger'}
    if kind == 'if_text':
        action.update(then=[{'type': 'key_press', 'key': 'y'}], **{'else': []})
    outcome = Player(platform, sleep=lambda _: None).play(make_script([
        action, {'type': 'key_press', 'key': 'x'}]))
    assert outcome.ok, outcome.error
    assert outcome.actions_run == 2
    assert not any(call[0] == 'mouse_click' for call in backend.calls)


def test_missing_models_still_fail_clearly_instead_of_becoming_no_text(tmp_path):
    engine = RapidOcrEngine(model_dir=tmp_path)
    platform, _, _ = make_platform(capture=FakeScreenCapture(), ocr=engine)
    outcome = Player(platform).play(make_script([{'type': 'click_text', 'pattern': 'trigger'}]))
    assert not outcome.ok
    assert 'OCR 模型不存在' in outcome.error
