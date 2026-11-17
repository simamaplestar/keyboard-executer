"""Player context is isolated all the way to the provider and reply queue."""
import base64
import json
import threading
from dataclasses import replace

import cv2
import numpy as np

from keyboard_executor.core.chat_reply import ChatReplySession
from tests.core.test_chat_observer import frame
from tests.core.test_chat_reply import Provider, close_sessions, make_session, scan, trigger
from tests.core.test_chat_reply_monitor import background_session, eventually


def observed(session, *lines):
    image, boxes = frame(*lines)
    return image, session._observer.observe(image, boxes)


def payload(provider, index=0):
    return json.loads(provider.calls[index][0][0]['content'])


def test_each_request_contains_only_one_players_own_conversation():
    provider = Provider()
    session, *_ = make_session(provider)
    old = [('甲[CH.301]>>甲的舊話', 'green'), ('乙[CH.301]>>乙的秘密', 'green')]
    observed(session, *old)
    image, candidates = observed(session, *old,
                                 ('甲[CH.302]>>甲的新話', 'green'),
                                 ('乙[CH.301]>>乙的新話', 'green'))
    session._start_ai(image, candidates)
    prepared = session._ai_result.result(timeout=2)
    assert [m.sender for m in prepared[0]] == ['甲']
    data = payload(provider)
    assert data['conversation_with'] == '甲'
    assert [m['text'] for m in data['history']] == ['甲的舊話']
    assert [m['text'] for m in data['new_messages']] == ['甲的新話']
    assert '乙的' not in json.dumps(data, ensure_ascii=False)
    encoded = provider.calls[0][0][0]['images'][0]['data']
    isolated = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8), cv2.IMREAD_COLOR)
    assert isolated.shape[0] < image.shape[0]


def test_map_request_cannot_include_same_players_private_conversation():
    provider = Provider()
    session, *_ = make_session(provider)
    old = [('甲[CH.301]>>私下才說的話', 'green'), ('甲：公開的舊話', 'white')]
    observed(session, *old)
    image, candidates = observed(session, *old, ('甲：公開的新話', 'white'))
    session._start_ai(image, candidates)
    session._ai_result.result(timeout=2)
    data = payload(provider)
    assert [m['text'] for m in data['history']] == ['公開的舊話']
    assert all(m['channel'] == 'map' for m in data['history'] + data['new_messages'])


def test_reply_to_another_player_cannot_enter_current_players_context():
    provider = Provider()
    session, *_ = make_session(provider)
    observed(session, ('甲[CH.301]>>甲的問題', 'green'))
    _, first = observed(session, ('甲[CH.301]>>甲的問題', 'green'),
                        ('乙[CH.301]>>乙的問題', 'green'))
    session._observer.record_reply(first[0], '只回給乙的答案')
    image, current = observed(session, ('甲[CH.301]>>甲的新問題', 'green'))
    session._start_ai(image, current)
    session._ai_result.result(timeout=2)
    assert '只回給乙' not in json.dumps(payload(provider), ensure_ascii=False)


def test_unrelated_queued_player_does_not_regenerate_a_ready_reply():
    provider = Provider()
    session, _, _, _, _, stop = background_session(provider)
    try:
        observed(session, ('甲[CH.301]>>甲的舊话', 'green'))
        image, first = observed(session, ('甲[CH.301]>>甲的新話', 'green'))
        session._on_chat_messages(image, first)
        session._refresh_ai()
        ready = session._ai_result
        ready.result(timeout=2)
        eventually(lambda: not session._prepare_worker.is_alive())
        image, second = observed(session, ('乙[CH.301]>>乙的新話', 'green'))
        session._on_chat_messages(image, second)
        session._refresh_ai()
        assert session._ai_result is ready
        assert len(provider.calls) == 1
        # Consuming the first result allows the next independent request.
        session._ai_result = None
        session._refresh_ai()
        session._ai_result.result(timeout=2)
        assert payload(provider, 1)['conversation_with'] == '乙'
        assert [m['sender'] for m in payload(provider, 1)['new_messages']] == ['乙']
    finally:
        stop.set()
        session.close()


def test_detection_notice_is_emitted_while_previous_ai_is_still_busy():
    entered, release = threading.Event(), threading.Event()

    class SlowProvider(Provider):
        def stream_chat(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)
            return super().stream_chat(*args, **kwargs)

    session, _, _, backend, records, stop = background_session(SlowProvider())
    try:
        observed(session, ('甲[CH.301]>>舊訊息', 'green'))
        image, first = observed(session, ('甲[CH.301]>>新訊息', 'green'))
        session._on_chat_messages(image, first)
        session._refresh_ai()
        assert entered.wait(1)
        records.clear()
        image, second = observed(session, ('乙[CH.301]>>另一位玩家', 'green'))
        session._on_chat_messages(image, second)
        assert any('偵測到' in item['message'] for item in records)
        assert not session._ai_result.done() and not backend.calls
    finally:
        release.set()
        stop.set()
        session.close()


def test_context_survives_suspend_resume_without_replaying_messages():
    session, *_ = make_session()
    image, boxes = frame(('甲[CH.301]>>重啟前的話', 'green'))
    session._observer.observe(image, boxes)
    session.suspend()
    session.resume()
    assert session._observer.observe(image, boxes) == []
    assert [m.text for m in session._observer.history_for('甲')] == ['重啟前的話']


def test_saved_context_is_restored_and_new_player_messages_are_persisted(tmp_path):
    from keyboard_executor.storage.chat_history import ChatHistoryStore
    store = ChatHistoryStore(tmp_path)
    original, *_ = make_session()
    first = ChatReplySession(original._platform, original._config, Provider(), threading.Event(),
                             history_store=store)
    second = None
    try:
        observed(first, ('甲[CH.301]>>記住這一句', 'green'))
        first.close()
        second = ChatReplySession(original._platform, original._config, Provider(), threading.Event(),
                                  history_store=ChatHistoryStore(tmp_path))
        observed(second, ('甲[CH.301]>>記住這一句', 'green'))
        image, candidates = observed(second, ('甲[CH.301]>>記住這一句', 'green'),
                                     ('甲[CH.301]>>接著說', 'green'))
        second._start_ai(image, candidates)
        second._ai_result.result(timeout=2)
        assert [m['text'] for m in payload(second._provider)['history']] == ['記住這一句']
        assert [m.text for m in store.load(original._config.self_name)['甲']] == ['記住這一句', '接著說']
    finally:
        first.close()
        if second is not None:
            second.close()


def test_two_players_are_sent_separately_without_dropping_or_repeating_either():
    provider = Provider(lambda data: {'replies': [
        {'message_id': data['new_messages'][0]['id'], 'text': '回給' + data['conversation_with']}]})
    session, script, win, backend, _, clock, _ = make_session(provider)
    _, old_boxes = frame(('甲[CH.301]>>舊甲', 'green'), ('乙[CH.301]>>舊乙', 'green'))
    image, new_boxes = frame(('甲[CH.301]>>新甲', 'green'), ('乙[CH.301]>>新乙', 'green'))
    session._config = replace(session._config, region=(0, 0, image.shape[1], image.shape[0]))
    win = replace(win, width=1200)
    session._platform.window_manager.windows = [win]
    session._platform.screen_capture.image = image
    session._platform.ocr_engine._boxes = [old_boxes, new_boxes, new_boxes, new_boxes]
    trigger(session, script, win, clock)
    scan(session, script, win)
    assert [c[1] for c in backend.calls if c[0] == 'type_text'] == ['回給甲', '回給乙']
    assert [payload(provider, i)['conversation_with'] for i in range(len(provider.calls))] == ['甲', '乙']
    assert session._observer.history_for('甲')[-1].recipient == '甲'
    assert session._observer.history_for('乙')[-1].recipient == '乙'
    clock[0] = 10
    scan(session, script, win)
    assert len(provider.calls) == 2


def test_history_io_failure_does_not_abort_chat_or_log_private_contents():
    class BrokenStore:
        def load(self, _):
            raise OSError('PRIVATE_FILENAME')

        def append(self, *args):
            raise OSError('PRIVATE_CONTENT')

    original, *_ = make_session()
    records = []
    session = ChatReplySession(original._platform, original._config, Provider(), threading.Event(),
                               records.append, history_store=BrokenStore())
    try:
        observed(session, ('甲[CH.301]>>仍然記在記憶體', 'green'))
        assert session._observer.history_for('甲')[0].text == '仍然記在記憶體'
        assert len(records) == 1
        assert 'PRIVATE' not in json.dumps(records)
    finally:
        session.close()
