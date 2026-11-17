import base64
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from keyboard_executor.core.ai.provider import ChatResult, AiAborted


def row(**changes):
    return dict(sample_id=8, state='present', index=1, char='a',
                input_box=[100, 600, 600, 750], confirm_box=[650, 600, 900, 750]) | changes


def parse(rows):
    from keyboard_executor.core.ai.sequence_panel_recognizer import parse_panel_readings
    return parse_panel_readings(json.dumps({'readings': rows}), {8})


def test_valid_reading():
    result = parse([row()])[0]
    assert result.char == 'A'
    assert result.input_box == (100, 600, 600, 750)


@pytest.mark.parametrize('changes', [dict(index=True), dict(char='Ａ'), dict(char='AB'),
    dict(input_box=[0, 0, True, 20]), dict(input_box=[0, 0, 1001, 20]),
    dict(input_box=[1, 2, 1, 9]), dict(input_box=[1.5, 2, 4, 9]),
    dict(confirm_box=[100, 600, 650, 800]), dict(sample_id=True), dict(sample_id=9),
    dict(state='absent'), dict(state='unknown'), dict(state='click'), dict(action='click'), dict(char=None)])
def test_invalid_reading(changes):
    with pytest.raises(ValueError): parse([row(**changes)])


@pytest.mark.parametrize('rows', [[], [row(), row()]])
def test_ids_exactly_once(rows):
    with pytest.raises(ValueError): parse(rows)


def test_unknown_null():
    result = parse([row(state='unknown', index=None, char=None, input_box=None, confirm_box=None)])[0]
    assert result.state == 'unknown'


def test_duplicate_json_key_rejected():
    from keyboard_executor.core.ai.sequence_panel_recognizer import parse_panel_readings
    with pytest.raises(ValueError):
        parse_panel_readings('{"readings":[],"readings":[]}', {8})


@pytest.mark.parametrize('failure', ['none', 'network', 'tool', 'cancel'])
def test_crop_only_and_cleanup(failure):
    from keyboard_executor.core.ai.sequence_panel_recognizer import PanelRecognizer
    from keyboard_executor.core.ai.sequence_recognizer import SequenceSample
    paths, aborted = [], [False]
    def stream(messages, **kwargs):
        assert kwargs['tools'] == []
        assert len(messages[0]['images']) == 1
        image = messages[0]['images'][0]
        paths.append(Path(image['path']))
        assert paths[-1].read_bytes() == base64.b64decode(image['data'])
        if failure == 'network': raise RuntimeError('offline')
        if failure == 'cancel': aborted[0] = True
        return SimpleNamespace(text=json.dumps({'readings': [row()]}),
                               tool_call='bad' if failure == 'tool' else None)
    recognizer = PanelRecognizer(SimpleNamespace(stream_chat=stream))
    samples = [SequenceSample(8, np.zeros((20, 30, 3), np.uint8))]
    if failure == 'none': assert recognizer.recognize(samples, should_abort=lambda: aborted[0])[0].char == 'A'
    else:
        with pytest.raises((RuntimeError, ValueError, AiAborted)):
            recognizer.recognize(samples, should_abort=lambda: aborted[0])
    assert paths and not paths[0].exists()


def test_cancel_during_png_encoding_never_dispatches_provider(monkeypatch):
    from keyboard_executor.core.ai import sequence_panel_recognizer as module
    from keyboard_executor.core.ai.sequence_recognizer import SequenceSample
    aborted, calls = [False], []
    original = module.encode_png
    def encode(image):
        result = original(image)
        aborted[0] = True
        return result
    monkeypatch.setattr(module, 'encode_png', encode)
    def stream(*args, **kwargs):
        calls.append(args)
        return ChatResult(json.dumps({'readings': [row()]}))
    recognizer = module.PanelRecognizer(SimpleNamespace(stream_chat=stream))
    with pytest.raises(AiAborted):
        recognizer.recognize([SequenceSample(8, np.zeros((20, 30, 3), np.uint8))],
                             should_abort=lambda: aborted[0])
    assert calls == []


def test_precancel_no_request():
    from keyboard_executor.core.ai.sequence_panel_recognizer import PanelRecognizer
    with pytest.raises(AiAborted): PanelRecognizer(None).recognize([], should_abort=lambda: True)
