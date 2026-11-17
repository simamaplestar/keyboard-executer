"""使用者決定：密語一律用 H 帶入的對象直接送出，不再用聊天畫面的名字比對或略過。

名字讀不準、被擠出畫面或讀到相近寫法，都照樣按 H 回覆，且不輸入名字。"""
from dataclasses import replace

import pytest

from tests.core.test_chat_observer import frame
from tests.core.test_chat_reply import close_sessions, make_session


def prepared_reply(session, name='Wwawa98'):
    session._observer.observe(*frame(('系統公告', 'blue')))
    candidates = session._observer.observe(*frame((f'{name}[CH.301]>>你好', 'green')))
    return candidates, [(candidates[0], '收到')]


def latest_frame(session, image, boxes):
    session._platform.screen_capture.capture = lambda _: image.copy()
    session._platform.ocr_engine.recognize = lambda _: boxes


def spam_frame():
    # 實機：攻擊時系統訊息洗版，密語幾秒內被擠出只有 6 行的聊天框。
    return frame(*[('前方沒有可攻擊的怪物。', 'blue')] * 6)


@pytest.mark.parametrize('latest', [
    ('wawa98[CH.301]>>你好', 'green'),
    ('Wwawa98<<已送出的舊話', 'green'),
    ('Wwawa98：地圖對話', 'white'),
    ('其他人[CH.301]>>你好', 'green'),
    ('系統公告', 'blue'),
])
def test_unconfirmed_whisper_name_still_replies_via_h_without_typing_name(latest):
    session, _, win, backend, records, *_ = make_session()
    prepared = prepared_reply(session)
    latest_frame(session, *frame(latest))
    session._confirm_and_send(prepared, win)
    assert [c[1] for c in backend.calls] == ['h', 'enter', '收到', 'enter']
    assert not any('略過' in r['message'] for r in records)
    # 其他玩家的新密語仍排進自己的佇列，不併入這次回覆。
    if latest[0].startswith('wawa98['):
        assert [m.sender for m in session._deferred_messages] == ['wawa98']


def test_saved_conversation_never_counts_as_visible_sender():
    session, *_ = make_session()
    prepared_reply(session)
    observer = session._observer
    assert observer.sees_incoming_sender('Wwawa98', 'whisper')
    observer.restore_conversations(observer.conversations)
    assert not observer.sees_incoming_sender('Wwawa98', 'whisper')


def test_old_reads_expire():
    session, *_ = make_session()
    observer = session._observer
    prepared_reply(session, 'Startuuuuuu')
    observer.observe(*frame(('Startuuuuuu[CH.301]>>你好', 'green'), ('系統', 'blue')))
    image, boxes = spam_frame()
    observer.observe(image, boxes)
    assert observer.sees_incoming_sender('Startuuuuuu', 'whisper')
    for _ in range(60):
        observer.observe(image, boxes)
    assert not observer.sees_incoming_sender('Startuuuuuu', 'whisper')
