import json

import pytest

from keyboard_executor.core.chat_observer import ChatMessage
from keyboard_executor.core.chat_reply import parse_replies


MESSAGE = ChatMessage(1, 'whisper', '朋友', '在嗎')
REPLY = json.dumps({'replies': [{'message_id': 1, 'text': '在啊'}]})


@pytest.mark.parametrize('opening,newline', [
    ('```', '\n'), ('```json', '\n'), ('```json', '\r\n'),
    ('```JSON', '\r\n'),
])
def test_complete_json_code_block_uses_same_reply_validation(opening, newline):
    text = f'{opening}{newline}{REPLY}{newline}```'
    assert parse_replies(text, [MESSAGE], 40) == [(MESSAGE, '在啊')]


@pytest.mark.parametrize('text,reason', [
    ('', '空白'), (' \r\n ', '空白'), ('```json\n\n```', '空白'),
    ('在啊', '不是有效 JSON'),
    ('說明\n' + REPLY, '不是有效 JSON'),
    ('```json\n' + REPLY + '\n```\n額外說明', '不是有效 JSON'),
    ('data: private-payload', '不是有效 JSON'),
])
def test_invalid_reply_has_actionable_reason_without_exposing_content(text, reason):
    with pytest.raises(ValueError, match=reason) as caught:
        parse_replies(text, [MESSAGE], 40)
    assert 'private-payload' not in str(caught.value)


@pytest.mark.parametrize('entry', [
    {'message_id': 99, 'text': '在啊'},
    {'message_id': 1, 'text': '/command'},
    {'message_id': 1, 'text': '第一行\n第二行'},
    {'message_id': 1, 'text': '在啊', 'recipient': '別人'},
])
def test_fenced_reply_cannot_bypass_recipient_or_text_guards(entry):
    text = '```\r\n' + json.dumps({'replies': [entry]}) + '\r\n```'
    with pytest.raises(ValueError):
        parse_replies(text, [MESSAGE], 40)
