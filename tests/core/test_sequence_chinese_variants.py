import pytest

from keyboard_executor.core.sequence_input_config import normalize_prompt
from keyboard_executor.core.sequence_prompt import classify_sequence_prompt
from keyboard_executor.platforms.base import TextBox


@pytest.mark.parametrize('parts', [
    ['讀按照號碼顺序輸入文字。'],
    ['讀按照號碼', '顺序輸入文字。'],
    ['按照號碼顺序輸入文字。'],
    ['讀依照編號順序輸入文字。'],
])
def test_misread_or_missing_first_glyph_cannot_prove_prompt_disappearance(parts):
    boxes = [TextBox(text, i * 80, 0, 80, 20, .97) for i, text in enumerate(parts)]
    boxes.append(TextBox('DRH', 0, 180, 40, 20, .99))
    assert classify_sequence_prompt(boxes) == 'unknown'


def test_reliable_full_prompt_has_priority_over_body_only_search_budget():
    body = '按照號碼順序輸入文字'
    boxes = [TextBox(body[x+y], x*10, y*10, 10, 10, .99)
             for y in range(5) for x in range(5)]
    boxes.append(TextBox('請按照號碼順序輸入文字', 1000, 0, 240, 20, .99))
    assert classify_sequence_prompt(boxes) == 'present'


@pytest.mark.parametrize('traditional,simplified,mixed', [
    ('請按照號碼順序輸入文字', '请按照号码顺序输入文字', '请按照號碼順序输入文字'),
    ('請依照編號順序輸入文字', '请依照编号顺序输入文字', '請依照编号順序输入文字'),
    ('請輸入驗證碼與確認資訊', '请输入验证码与确认资讯', '请輸入验证码與確認资讯'),
])
def test_manual_prompt_comparison_accepts_traditional_simplified_and_mixed(traditional, simplified, mixed):
    assert normalize_prompt(traditional) == normalize_prompt(simplified) == normalize_prompt(mixed)


@pytest.mark.parametrize('text', [
    '請按照號碼順序輸入文字。', '请按照号码顺序输入文字。', '请按照號碼順序输入文字。',
    '請依照編號順序輸入文字', '请依照编号顺序输入文字', '請按順序輸入文字', '请按顺序输入文字',
])
@pytest.mark.parametrize('confidence,expected', [(.97, 'present'), (.79, 'unknown')])
def test_panel_prompt_keeps_confidence_guard_for_every_script_variant(text, confidence, expected):
    assert classify_sequence_prompt([TextBox(text, 0, 0, 240, 20, confidence)]) == expected


def test_normalization_does_not_modify_the_raw_ocr_box():
    box = TextBox('请按照號碼順序输入文字。', 9, 5, 234, 22, .97013)
    assert classify_sequence_prompt([box]) == 'present'
    assert box.text == '请按照號碼順序输入文字。'
