import numpy as np
import pytest

from keyboard_executor.core.ai.sequence_char_recognizer import (
    CharRecognizer, parse_char_readings,
)
from keyboard_executor.core.ai.sequence_recognizer import SequenceSample


def test_parse_ok_and_uppercases():
    rows = parse_char_readings('{"readings":[{"sample_id":1,"char":"g"},{"sample_id":2,"char":null}]}', {1, 2})
    assert [(r.sample_id, r.char) for r in rows] == [(1, 'G'), (2, None)]


def test_parse_tolerates_single_markdown_fence():
    text = '```json\n{"readings":[{"sample_id":1,"char":"H"}]}\n```'
    assert parse_char_readings(text, {1})[0].char == 'H'


@pytest.mark.parametrize('text', [
    '{"readings":[{"sample_id":1,"char":"AB"}]}',          # 多字元
    '{"readings":[{"sample_id":1,"char":"！"}]}',            # 非 ASCII
    '{"readings":[{"sample_id":1,"char":3}]}',              # 非字串
    '{"readings":[{"sample_id":1}]}',                       # 缺欄位
    '{"readings":[{"sample_id":2,"char":"A"}]}',            # 未知取樣
    '{"readings":[]}',                                      # 缺取樣
    '{"readings":[{"sample_id":1,"char":"A","x":1}]}',      # 多欄位
    'not json',
])
def test_parse_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_char_readings(text, {1})


def test_recognizer_sends_crops_and_parses():
    sent = {}

    class Provider:
        def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
            sent['images'] = messages[0]['images']
            sent['system'] = system
            return type('R', (), {'text': '{"readings":[{"sample_id":7,"char":"n"}]}',
                                  'tool_call': None})()

    sample = SequenceSample(7, np.zeros((60, 60, 3), np.uint8))
    rows = CharRecognizer(Provider()).recognize([sample], should_abort=lambda: False)
    assert [(r.sample_id, r.char) for r in rows] == [(7, 'N')]
    assert sent['images'][0]['media_type'] == 'image/png'


def test_recognizer_rejects_tool_call():
    class Provider:
        def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
            return type('R', (), {'text': '{}', 'tool_call': object()})()

    sample = SequenceSample(1, np.zeros((60, 60, 3), np.uint8))
    with pytest.raises(ValueError):
        CharRecognizer(Provider()).recognize([sample], should_abort=lambda: False)


def test_parse_digit_ok():
    from keyboard_executor.core.ai.sequence_char_recognizer import parse_digit_readings
    rows = parse_digit_readings('{"readings":[{"sample_id":1,"digit":"2"},{"sample_id":2,"digit":null}]}', {1, 2})
    assert [(r.sample_id, r.digit) for r in rows] == [(1, 2), (2, None)]


@pytest.mark.parametrize('text', [
    '{"readings":[{"sample_id":1,"digit":"4"}]}',          # 非 1/2/3
    '{"readings":[{"sample_id":1,"digit":2}]}',            # 非字串
    '{"readings":[{"sample_id":1,"digit":"12"}]}',         # 多字元
    '{"readings":[{"sample_id":1}]}',                      # 缺欄位
    '{"readings":[{"sample_id":1,"digit":"1","char":"A"}]}',  # 多欄位
    '{"readings":[{"sample_id":2,"digit":"1"}]}',          # 未知取樣
])
def test_parse_digit_rejects_invalid(text):
    from keyboard_executor.core.ai.sequence_char_recognizer import parse_digit_readings
    with pytest.raises(ValueError):
        parse_digit_readings(text, {1})


def test_recognize_digits_sends_and_parses():
    class Provider:
        def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
            assert '編號' in system
            return type('R', (), {'text': '{"readings":[{"sample_id":3,"digit":"1"}]}',
                                  'tool_call': None})()

    from keyboard_executor.core.ai.sequence_char_recognizer import DigitReading
    sample = SequenceSample(3, np.zeros((60, 60, 3), np.uint8))
    rows = CharRecognizer(Provider()).recognize_digits([sample], should_abort=lambda: False)
    assert rows == [DigitReading(3, 1)]
