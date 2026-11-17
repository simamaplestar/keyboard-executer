import pytest
from keyboard_executor.platforms.base import TextBox


def classify(boxes):
    from keyboard_executor.core.sequence_prompt import classify_sequence_prompt
    return classify_sequence_prompt(boxes)


@pytest.mark.parametrize('text,confidence,state', [
    ('請按照號碼順序輸入文字。', .99, 'present'), ('请依照编号顺序输入文字', .99, 'present'),
    ('請按順序輸入文字', .8, 'present'), ('請按順序輸入文字', .79, 'unknown'),
    ('確認', .99, 'absent'), ('一般聊天內容', .4, 'unknown'),
    ('請按順序輸入文字', float('nan'), 'unknown'), ('請按順序輸入文字', float('inf'), 'unknown')])
def test_gate(text, confidence, state):
    assert classify([TextBox(text, 0, 0, 300, 30, confidence)]) == state


def test_empty_not_absent():
    assert classify([]) == 'unknown'


def test_multiline_unsorted_and_unrelated_low_confidence():
    assert classify([TextBox('順序輸入文字', 0, 25, 160, 20, .99),
                     TextBox('雜訊', 0, 100, 30, 20, .1),
                     TextBox('請按照號碼', 0, 0, 100, 20, .99)]) == 'present'


def test_far_fragments_not_a_prompt():
    assert classify([TextBox('請按照號碼', 0, 0, 100, 20, .99),
                     TextBox('順序輸入文字', 500, 0, 140, 20, .99)]) == 'absent'


def test_split_low_confidence_prompt_not_absent():
    assert classify([TextBox('請按照號碼', 0, 0, 100, 20, .99),
                     TextBox('順序輸入文字', 110, 0, 140, 20, .7),
                     TextBox('確認', 0, 90, 100, 20, .99)]) == 'unknown'


def test_newline_punctuation_normalization():
    assert classify([TextBox('請按照號碼\n順序，輸入文字！', 0, 0, 300, 50, .99)]) == 'present'
