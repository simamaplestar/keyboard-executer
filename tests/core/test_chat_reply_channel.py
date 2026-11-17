"""Exercise routing against a fake game UI whose channel changes only on clicks."""
from dataclasses import replace
import threading
import time

import cv2
import numpy as np
import pytest

from keyboard_executor.core.chat_observer import ChatMessage
from keyboard_executor.core.models import action_from_dict
from keyboard_executor.platforms.base import TextBox
from tests.core.test_chat_reply import make_session


class ChannelScene:
    def __init__(self, session, win, backend, *, scale=1):
        self.session, self.win, self.backend = session, win, backend
        self.scale = scale
        self.channel = 'whisper'
        self.menu = False
        self.fail_switch = False
        self.missing_menu = False
        self.ignored_button_clicks = 0
        self.has_input_bar = True
        self.label_override = None
        self.input_focused = False
        self.input_stage = None
        self.draft = ''
        self.sent = []
        self.ignored_enters = 0
        self.ignored_recipient_enters = 0
        self.recipient_draft = ''
        self.prefill = '朋友'
        self.recipient_highlighted = False
        self.recipient_selected = False
        self.recipient_caret = False
        self.dialog_title = '請輸入密語對象。'
        self.open_recipient = True
        self.ignored_h = 0
        self.after_recipient_enter = lambda: None
        self.header_obscured = False
        self.header_color = (210, 150, 25)
        self.typing_latency = 0.0
        self.text_ready_at = 0.0
        self.discarded_drafts = []
        self.submit_latency = 0.0
        self.keep_focus_after_submit = False
        self.clear_at = None
        self.ocr_entered = threading.Event()
        self.ocr_release = None
        self.last_region = None
        self.calls = []
        self.typed_channels = []
        self._click = backend.mouse_click
        self._type = backend.type_text
        self._key = backend.key_press
        self._key_up = backend.key_up
        self._key_combo_up = backend.key_combo_up
        backend.mouse_click, backend.type_text = self.click, self.type_text
        backend.key_press = self.key_press
        backend.key_up = self.key_up
        backend.key_combo_up = self.key_combo_up

    def scale_factor(self):
        return self.scale

    def capture(self, region):
        if self.clear_at is not None and time.monotonic() >= self.clear_at:
            self.draft, self.clear_at = '', None
        x, y = round(region.x / self.scale) - self.win.x, round(region.y / self.scale) - self.win.y
        width, height = round(region.width / self.scale), round(region.height / self.scale)
        self.last_region = (x, y, width, height)
        canvas = np.zeros((self.win.height, self.win.width, 3), dtype=np.uint8)
        if self.has_input_bar:
            canvas[460:500, 15:146] = 120 if self.channel == 'public' else 95
            canvas[465:495, 148:330] = 255
            if self.draft and time.monotonic() >= self.text_ready_at:
                cv2.putText(canvas, 'hello', (152, 487), cv2.FONT_HERSHEY_SIMPLEX,
                            .55, (20, 20, 20), 1)
            cv2.putText(canvas, 'All' if self.channel == 'public' else 'Friend',
                        (35, 485), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        if self.menu:
            canvas[290:410, 15:146] = 85
        if self.input_stage == 'recipient':
            canvas[90:235, 380:760] = self.header_color
            if self.header_obscured:
                canvas[90:159, 380:760] = 100
            cv2.putText(canvas, 'Whisper' if self.dialog_title == '請輸入密語對象。' else 'Other',
                        (440, 140), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
            canvas[159:225, 392:748] = 238
            canvas[160:182, 400:730] = 255
            if self.recipient_draft and self.recipient_highlighted:
                # 實機：H 帶入的名字是反白選取，白底黑字判斷結果為「不確定」
                canvas[163:179, 402:470] = (200, 120, 40)
                cv2.putText(canvas, 'Friend', (404, 176), cv2.FONT_HERSHEY_SIMPLEX,
                            .5, (255, 255, 255), 1)
            elif self.recipient_draft:
                cv2.putText(canvas, 'Friend', (404, 176), cv2.FONT_HERSHEY_SIMPLEX,
                            .5, (20, 20, 20), 1)
                if self.recipient_caret:
                    canvas[160:182, 470:471] = 0
            canvas[200:220, 610:665] = (20, 200, 150)
            canvas[200:220, 680:735] = (20, 200, 150)
        return cv2.resize(canvas[y:y+height, x:x+width],
                          (region.width, region.height), interpolation=cv2.INTER_NEAREST)

    def recognize(self, image):
        self.calls.append(image)
        if self.menu and self.ocr_release is not None:
            self.ocr_entered.set()
            assert self.ocr_release.wait(3)
        x, y, width, height = self.last_region
        labels = [(self.label_override or ('對所有人' if self.channel == 'public' else '朋友'),
                   30, 470, 100, 20)]
        if self.menu:
            labels += [('對好友', 30, 300, 90, 20), ('對群組', 30, 330, 90, 20)]
            if not self.missing_menu:
                labels += [('對所有人', 30, 375, 100, 20)]
        if self.input_stage == 'recipient':
            labels += [(self.dialog_title, 440, 120, 190, 20)]
        if not self.has_input_bar:
            labels = [('對所有人', 20, 360, 100, 20)]  # ordinary chat is not a channel button
        return [TextBox(text, round((left-x)*self.scale), round((top-y)*self.scale),
                        round(w*self.scale), round(h*self.scale), .99)
                for text, left, top, w, h in labels
                if x <= left and y <= top and left+w <= x+width and top+h <= y+height]

    def click(self, x, y, button, count):
        self._click(x, y, button, count)
        x, y = x-self.win.x, y-self.win.y
        if 15 <= x < 146 and 460 <= y < 500:
            if self.ignored_button_clicks:
                # A busy game frame can miss a press that lands as the pointer arrives.
                self.ignored_button_clicks -= 1
                return
            self.menu = not self.menu
        elif self.menu and 15 <= x < 146 and 370 <= y < 400:
            if not self.fail_switch:
                self.channel = 'public'
            self.menu = False
            self.input_focused, self.input_stage = True, 'chat'

    def key_press(self, key, hold_ms=0):
        self._key(key, hold_ms)
        self.apply_key(key)

    def key_up(self, key):
        self._key_up(key)
        self.apply_key(key)

    def key_combo_up(self, keys):
        self._key_combo_up(keys)
        if set(keys) == {'ctrl', 'a'} and self.input_stage == 'recipient':
            self.recipient_selected = True

    def apply_key(self, key):
        key = key.strip().lower()
        if key == 'return':
            key = 'enter'
        if key == 'h':
            if self.input_stage == 'recipient':
                # 密語視窗已開：H 會打進名字欄，取代反白帶入的名字
                self.recipient_draft = 'h' if self.recipient_highlighted else self.recipient_draft + 'h'
            elif self.ignored_h:
                self.ignored_h -= 1   # 遊戲忙時漏收按鍵
            elif self.open_recipient:
                self.input_focused, self.input_stage = True, 'recipient'
                # 遊戲按 H 會自動帶入最後密我的人
                self.recipient_draft = self.prefill
        elif key == 'esc':
            if self.draft:
                self.discarded_drafts.append(self.draft)
                self.draft = ''
            self.input_focused, self.input_stage = False, None
        elif key == 'enter':
            if self.input_stage == 'recipient' and self.ignored_recipient_enters:
                self.ignored_recipient_enters -= 1
                self.after_recipient_enter()
                return
            if self.input_stage == 'recipient' or self.input_stage is None:
                self.input_focused, self.input_stage = True, 'chat'
            else:
                if self.draft:
                    if time.monotonic() < self.text_ready_at:
                        return
                    if self.ignored_enters:
                        self.ignored_enters -= 1
                        return
                    self.sent.append((self.draft, self.channel))
                    if self.submit_latency:
                        self.clear_at = time.monotonic() + self.submit_latency
                    else:
                        self.draft = ''
                self.input_focused = self.keep_focus_after_submit
                self.input_stage = 'chat' if self.input_focused else None

    def type_text(self, text):
        assert self.input_focused, 'Game has no focused text input'
        self.typed_channels.append((text, self.channel))
        if self.input_stage == 'chat':
            self.draft += text
            self.text_ready_at = time.monotonic() + self.typing_latency
        elif self.input_stage == 'recipient':
            self.recipient_draft = text if self.recipient_selected else self.recipient_draft + text
            self.recipient_selected = False
        self._type(text)


def expect_skipped(session, replies, win, match=''):
    """回覆失敗不停腳本：不丟例外，通知「回覆失敗…腳本繼續」。"""
    import re
    seen = []
    notify = session._notify
    session._notify = lambda message: (seen.append(message), notify(message))
    try:
        session._send_replies(replies, win)
    finally:
        session._notify = notify
    assert any('回覆失敗' in m and '腳本繼續' in m and re.search(match, m) for m in seen), seen


@pytest.fixture
def channel_session():
    session, _, win, backend, records, _, stop = make_session(visual_delivery=True)
    win = replace(win, x=100, y=80, width=800, height=600)
    session._platform.window_manager.windows = [win]
    session._config = replace(session._config, region=(10, 300, 320, 200))
    scene = ChannelScene(session, win, backend)
    session._platform = replace(session._platform, screen_capture=scene, ocr_engine=scene)
    yield session, win, backend, records, stop, scene
    stop.set()
    session.close()


def test_whisper_is_sent_then_clicks_open_menu_and_returns_to_public(channel_session):
    session, win, backend, _, _, scene = channel_session
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '你好'), '收到')], win)
    assert scene.channel == 'public'
    assert not scene.menu
    assert scene.typed_channels == [('收到', 'whisper')]   # 名字由 H 帶入，不輸入
    kinds = [c[0] for c in backend.calls]
    assert kinds[-4:] == ['mouse_click', 'mouse_click', 'mouse_move', 'key_press']
    assert backend.calls[-1][1] == 'esc'
    assert not scene.input_focused
    assert session._observer.history[-1].text == '收到'


@pytest.mark.parametrize('channel', ['map', 'whisper'])
@pytest.mark.parametrize('scale', [1, 2])
def test_returning_to_public_clears_pointer_from_chat_before_recognition(
        channel_session, channel, scale):
    session, win, backend, _, _, scene = channel_session
    # A tall/wide chat box still leaves a safe strip above it. The clearance
    # must cover the cursor, not expand by twice the entire chat box height.
    session._config = replace(session._config, region=(10, 200, 500, 310))
    scene.scale = scale
    pointer = [win.x + 700, win.y + 70]
    selected_at = [None]
    moved_at = [None]
    captures_after_selection = []
    click, move, capture = backend.mouse_click, backend.mouse_move, scene.capture

    def mouse_click(x, y, button, count):
        pointer[:] = [x, y]
        was_open = scene.menu
        click(x, y, button, count)
        if was_open and not scene.menu and scene.channel == 'public':
            selected_at[0] = time.monotonic()
        elif scene.menu:
            selected_at[0] = None

    def mouse_move(x, y):
        pointer[:] = [x, y]
        moved_at[0] = time.monotonic()
        move(x, y)

    def read_image(rect):
        if selected_at[0] is not None:
            captures_after_selection.append((tuple(pointer), time.monotonic(), moved_at[0]))
        return capture(rect)

    backend.mouse_click, backend.mouse_move = mouse_click, mouse_move
    scene.capture = read_image
    session._send_replies([(ChatMessage(1, channel, '朋友', '在嗎'), '有喔')], win)

    assert captures_after_selection
    for (x, y), captured_at, moved in captures_after_selection:
        # Real screenshot coordinates are scaled, input coordinates are not.
        assert win.x < x < win.x + win.width - 1
        assert win.y < y < win.y + win.height - 1
        assert not (win.x + 10 - 48 <= x <= win.x + 510 + 48
                    and win.y + 200 - 48 <= y <= win.y + 510 + 48)
        assert moved is not None and captured_at - moved >= .25
    assert scene.channel == 'public' and not scene.input_focused
    assert scene.sent == [('有喔', 'public' if channel == 'map' else 'whisper')]


def test_whisper_uses_h_prefilled_recipient_without_typing_or_comparing(channel_session):
    # 使用者決定：H 會自動帶入最後密我的人，直接確認，不比對也不輸入名字。
    session, win, backend, _, _, scene = channel_session
    scene.prefill = 'Startuuuuuu'
    session._send_replies([(ChatMessage(1, 'whisper', 'Startuuuuu', '在嗎'), '有收到~')], win)
    assert scene.recipient_draft == 'Startuuuuuu'
    assert scene.typed_channels == [('有收到~', 'whisper')]
    assert not any(c[0] == 'key_combo_down' and set(c[1]) == {'ctrl', 'a'} for c in backend.calls)
    assert scene.sent == [('有收到~', 'whisper')]
    assert scene.channel == 'public' and not scene.input_focused


def test_empty_h_recipient_is_cancelled_and_skipped(channel_session):
    session, win, backend, records, _, scene = channel_session
    scene.prefill = ''
    session._send_replies([(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), '有收到~')], win)
    assert scene.sent == [] and scene.typed_channels == []
    assert ('key_press', 'esc') in [c[:2] for c in backend.calls]
    assert scene.input_stage is None
    assert any('沒有名字' in r['message'] and '略過' in r['message'] for r in records)


@pytest.mark.parametrize('ignored', [1, 2])
def test_recipient_enter_must_complete_before_reply_text(channel_session, ignored):
    session, win, _, _, _, scene = channel_session
    scene.ignored_recipient_enters = ignored
    session._send_replies([(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), '有收到~')], win)
    assert scene.recipient_draft == '朋友'   # H 帶入的名字，不輸入
    assert scene.sent == [('有收到~', 'whisper')]
    assert scene.channel == 'public'


def test_recipient_full_height_caret_does_not_block_enter_retry(channel_session):
    session, win, _, _, _, scene = channel_session
    scene.ignored_recipient_enters = 1
    scene.after_recipient_enter = lambda: setattr(scene, 'recipient_caret', True)
    session._send_replies([(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), '有收到~')], win)
    assert scene.recipient_draft == '朋友'   # H 帶入的名字，不輸入
    assert scene.sent == [('有收到~', 'whisper')]
    assert scene.channel == 'public'


def test_unconfirmed_recipient_closes_dialog_skips_reply_and_continues(channel_session):
    session, win, backend, records, _, scene = channel_session
    scene.ignored_recipient_enters = 100
    expect_skipped(session, [(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), '有收到~')], win, match='密語對象')
    assert scene.draft == '' and scene.sent == []
    assert ('key_press', 'esc') in [c[:2] for c in backend.calls]   # 關掉密語對象視窗
    assert scene.input_stage is None and not scene.input_focused
    assert not any('已回覆' in r['message'] for r in records)


@pytest.mark.parametrize('change', ['obscured', 'other_dialog'])
def test_changed_recipient_dialog_does_not_allow_reply_or_blind_enter_retry(channel_session, change):
    session, win, backend, _, _, scene = channel_session
    scene.ignored_recipient_enters = 100
    def change_dialog():
        if change == 'obscured':
            scene.header_obscured = True
        else:
            scene.dialog_title = '請輸入交易金額'
    scene.after_recipient_enter = change_dialog
    expect_skipped(session, [(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), 'reply')], win, match='密語對象')
    assert scene.recipient_draft == '朋友'   # H 帶入的名字，不輸入
    assert len([c for c in backend.calls
                if c[0] in {'key_press', 'key_down'} and c[1] == 'enter']) == 1


@pytest.mark.parametrize('change_title', [False, True])
def test_recipient_title_is_rechecked_after_ocr_even_when_geometry_stays_same(channel_session, change_title):
    session, win, backend, _, _, scene = channel_session
    scene.ignored_recipient_enters = 1
    retry = [False]
    def after_enter():
        retry[0] = True
        scene.header_color = (211, 151, 25)  # changed background requires fresh OCR
    scene.after_recipient_enter = after_enter
    recognize = scene.recognize
    def replace_during_ocr(image):
        result = recognize(image)
        if retry[0] and any('密語對象' in box.text for box in result):
            if change_title:
                scene.dialog_title = '請輸入交易金額'
            else:
                scene.header_color = (212, 152, 25)
        return result
    scene.recognize = replace_during_ocr
    if change_title:
        expect_skipped(session, [(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), 'reply')], win, match='密語對象')
        assert scene.recipient_draft == '朋友'   # H 帶入的名字，不輸入
        assert len([c for c in backend.calls
                    if c[0] in {'key_press', 'key_down'} and c[1] == 'enter']) == 1
    else:
        session._send_replies([(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), 'reply')], win)
        assert scene.sent == [('reply', 'whisper')]


@pytest.mark.parametrize('failure', ['missing', 'other_dialog'])
def test_missing_or_wrong_recipient_dialog_never_types_name(channel_session, failure):
    session, win, _, _, _, scene = channel_session
    if failure == 'missing':
        scene.open_recipient = False
    else:
        scene.dialog_title = '請輸入交易金額'
    expect_skipped(session, [(ChatMessage(1, 'whisper', 'achenxi', '在嗎'), '有收到~')], win, match='密語對象')
    assert scene.typed_channels == []


def test_repeated_public_menu_reuses_identical_ocr_crops(channel_session):
    session, win, _, _, _, scene = channel_session
    session._ensure_public_channel(win, force_select=True)
    count = len(scene.calls)
    scene.channel = 'whisper'  # another whisper before restoring public again
    session._ensure_public_channel(win, force_select=True)
    assert scene.channel == 'public'
    assert len(scene.calls) == count


@pytest.mark.parametrize('stage', ['menu', 'button'])
@pytest.mark.parametrize('partial', [False, True], ids=['empty', 'partial'])
def test_channel_switch_waits_for_first_unreadable_frame_without_reclicking(channel_session, stage, partial):
    session, win, backend, _, _, scene = channel_session
    recognize = scene.recognize
    missed = False

    def slow_redraw(image):
        nonlocal missed
        boxes = recognize(image)
        if not missed and (scene.menu if stage == 'menu' else scene.channel == 'public'):
            missed = True
            return ([replace(boxes[0], text='對所')] if partial else [])
        return boxes

    scene.recognize = slow_redraw
    session._ensure_public_channel(win, force_select=True)
    assert missed
    assert scene.channel == 'public'
    assert not scene.menu and not scene.input_focused
    assert len([call for call in backend.calls if call[0] == 'mouse_click']) == 2
    assert not scene.sent


def _button_clicks(backend):
    return [c for c in backend.calls if c[0] == 'mouse_click'
            and 100 + 15 <= c[1] < 100 + 146 and 80 + 460 <= c[2] < 80 + 500]


def test_missed_menu_button_press_is_clicked_once_more(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.ignored_button_clicks = 1
    session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    # Missed press + retry before typing, then one press for post-send cleanup.
    assert len(_button_clicks(backend)) == 3
    assert scene.channel == 'public' and not scene.menu
    assert scene.sent == [('有喔', 'public')]


def test_menu_that_never_opens_stops_after_one_extra_press(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.ignored_button_clicks = 5
    with pytest.raises(RuntimeError, match='選單'):
        session._ensure_public_channel(win, force_select=True)
    assert len(_button_clicks(backend)) == 2


def test_visible_menu_without_public_row_is_never_toggled_shut(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.missing_menu = True
    with pytest.raises(RuntimeError, match='選單'):
        session._ensure_public_channel(win, force_select=True)
    assert len(_button_clicks(backend)) == 1
    assert scene.menu


def test_pointer_rests_on_menu_button_before_press(channel_session):
    session, win, backend, _, _, scene = channel_session
    moves = []
    move = backend.mouse_move

    def mouse_move(x, y):
        moves.append((x, y, time.monotonic()))
        move(x, y)

    backend.mouse_move = mouse_move
    pressed = []
    click = backend.mouse_click

    def mouse_click(x, y, button, count):
        pressed.append((x, y, time.monotonic()))
        click(x, y, button, count)

    backend.mouse_click = mouse_click
    session._ensure_public_channel(win, force_select=True)
    bx, by, at = pressed[0]
    hovered = [t for x, y, t in moves if (x, y) == (bx, by) and t <= at]
    assert hovered and at - hovered[-1] >= .12


def test_send_failure_is_written_to_persistent_log(channel_session, caplog):
    session, win, _, _, _, scene = channel_session
    scene.has_input_bar = False
    expect_skipped(session, [(ChatMessage(1, 'whisper', '朋友', '在嗎'), '收到')], win)
    assert any('AI 回覆操作失敗' in r.message for r in caplog.records)


def test_whisper_recipient_named_public_label_still_selects_public_menu(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.label_override = '對所有人'
    session._send_replies([(ChatMessage(1, 'whisper', '對所有人', '你好'), '收到')], win)
    assert scene.channel == 'public'
    assert len([c for c in backend.calls if c[0] == 'mouse_click']) == 2


@pytest.mark.parametrize('scale', [1, 2])
def test_map_reply_selects_public_before_typing_with_window_offset_and_dpi(channel_session, scale):
    session, win, backend, _, _, scene = channel_session
    scene.scale = scale
    session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    assert scene.typed_channels == [('有喔', 'public')]
    assert backend.calls[:2] == [('key_down', 'enter'), ('key_up', 'enter')]
    assert [c[0] for c in backend.calls[2:] if c[0] != 'mouse_move'][:2] == ['mouse_click', 'mouse_click']


def test_public_channel_does_not_toggle_menu_before_typing(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.channel = 'public'
    session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    assert scene.typed_channels == [('有喔', 'public')]
    text_index = next(i for i, call in enumerate(backend.calls) if call[0] == 'type_text')
    assert not any(c[0] == 'mouse_click' for c in backend.calls[:text_index])


def test_map_send_leaving_input_focused_exits_chat_before_resuming(channel_session):
    session, win, _, _, _, scene = channel_session
    scene.channel = 'public'
    scene.keep_focus_after_submit = True  # observed in the native game after Enter
    session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'public')]
    assert not scene.input_focused
    assert not scene.menu
    assert scene.discarded_drafts == []


@pytest.mark.parametrize('channel', ['map', 'whisper'])
@pytest.mark.parametrize('legacy_route', [(), (
    action_from_dict({'type': 'key_press', 'key': 'z'}),
    action_from_dict({'type': 'text_input', 'text': '{reply}'}),
)])
def test_runtime_owns_delivery_even_with_missing_or_wrong_legacy_routes(
        channel_session, channel, legacy_route):
    from keyboard_executor.core.chat_reply import ChatReplySession
    original, win, backend, records, stop, scene = channel_session
    config = replace(original._config, auto_map_channel=False,
                     map_actions=legacy_route, whisper_actions=legacy_route)
    session = ChatReplySession(original._platform, config, None, stop, records.append)
    scene.ignored_enters = 1  # a saved opt-out must not bypass submission checks
    try:
        session._send_replies([(ChatMessage(1, channel, '朋友', '在嗎'), '有喔')], win)
        assert scene.sent == [('有喔', 'whisper' if channel == 'whisper' else 'public')]
        assert scene.channel == 'public' and not scene.input_focused
        assert not any(c[:2] == ('key_press', 'z') for c in backend.calls)
        assert config.map_actions == legacy_route  # do not mutate the user's old data
        assert config.whisper_actions == legacy_route
        assert config.auto_map_channel is False
    finally:
        session.close()


@pytest.mark.parametrize('failure', ['missing_menu', 'fail_switch', 'has_input_bar'])
def test_unconfirmed_map_channel_never_types_reply(channel_session, failure):
    session, win, backend, _, _, scene = channel_session
    setattr(scene, failure, failure != 'has_input_bar')
    if failure == 'has_input_bar':
        expect_skipped(session, [(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win, match='框選')
    else:
        # 頻道選單壞掉時也無法用選單關聊天：才停止腳本，避免原腳本按鍵打進聊天框。
        with pytest.raises(RuntimeError, match='無法關閉聊天'):
            session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    assert scene.typed_channels == []
    if failure == 'has_input_bar':
        assert not any(c[0] == 'mouse_click' for c in backend.calls)


def test_stop_while_reading_open_menu_cancels_without_typing(channel_session):
    session, win, backend, _, stop, scene = channel_session
    scene.ocr_release = threading.Event()
    errors = []

    def send():
        try:
            session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=send)
    worker.start()
    try:
        assert scene.ocr_entered.wait(2)
        stop.set()
        worker.join(.4)
        assert not worker.is_alive()
        assert scene.typed_channels == []
        assert not errors
        assert len([c for c in backend.calls if c[0] == 'mouse_click']) == 1
    finally:
        scene.ocr_release.set()
        worker.join(3)


@pytest.mark.parametrize('change', [{'is_active': False}, {'width': 840}])
def test_window_changes_during_channel_ocr_discard_confirmation(channel_session, change):
    session, win, _, _, _, scene = channel_session
    scene.channel = 'public'
    current = [win]
    session._platform.window_manager.refresh = lambda _: current[0]
    recognize = scene.recognize

    def changed_during_ocr(image):
        result = recognize(image)
        current[0] = replace(win, **change)
        return result

    scene.recognize = changed_during_ocr
    with pytest.raises(RuntimeError, match='視窗|頻道'):
        session._send_replies([(ChatMessage(1, 'map', '路人', '在嗎'), '有喔')], win)
    assert scene.typed_channels == []


@pytest.mark.parametrize('channel', ['map', 'whisper'])
def test_reply_left_in_input_gets_guarded_enter_retries_before_cleanup(channel_session, channel):
    session, win, _, _, _, scene = channel_session
    scene.ignored_enters = 2  # user needs two more manual Enter presses
    session._send_replies([(ChatMessage(1, channel, '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'public' if channel == 'map' else 'whisper')]
    assert scene.discarded_drafts == []
    assert not scene.input_focused
    assert session._observer.history[-1].text == '有喔'


def test_never_submitted_reply_never_reports_false_success(channel_session):
    # 使用者要求：回覆失敗不停腳本，先關聊天；關不掉才停止。兩種結果都不能算成功。
    session, win, backend, records, _, scene = channel_session
    scene.ignored_enters = 100
    try:
        session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    except RuntimeError as exc:
        assert '無法關閉聊天' in str(exc)
    else:
        assert not scene.input_focused
    assert not scene.sent
    assert not session._observer.history
    assert not any('已回覆' in r['message'] for r in records)


def test_text_must_appear_before_sending_enter(channel_session):
    session, win, _, _, _, scene = channel_session
    scene.typing_latency = .15
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'whisper')]
    assert not scene.discarded_drafts


def test_existing_draft_is_not_sent_or_overwritten_by_opening_enter(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.channel = 'public'
    scene.draft = '我自己還沒打完'
    scene.input_focused, scene.input_stage = True, 'chat'
    expect_skipped(session, [(ChatMessage(1, 'map', '朋友', '在嗎'), '有喔')], win, match='輸入框')
    assert not backend.calls
    assert scene.draft == '我自己還沒打完' and not scene.sent


def test_delayed_submission_clears_without_extra_enter(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.submit_latency = .55
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'whisper')]
    text_index = backend.calls.index(('type_text', '有喔'))
    assert [c[1] for c in backend.calls[text_index:]
            if c[0] in {'key_press', 'key_down'}] == ['enter', 'esc']


# Private route injection exercises the lower-level send guards below. Saved
# routes are ignored during session construction, as tested above.
def test_guarded_submission_accepts_explicit_hold_enter(channel_session):
    session, win, _, _, _, scene = channel_session
    actions = tuple(action_from_dict({'type': 'key_press', 'key': a.params['key'], 'hold_ms': 80})
                    if str(a.type) == 'key_press' else a for a in session._config.whisper_actions)
    session._config = replace(session._config, whisper_actions=actions)
    scene.ignored_enters = 2
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'whisper')]
    assert not scene.discarded_drafts


def test_escape_before_submit_does_not_discard_draft(channel_session):
    session, win, _, _, _, scene = channel_session
    session._config = replace(session._config, whisper_actions=(
        *session._config.whisper_actions[:-1],
        action_from_dict({'type': 'key_press', 'key': 'esc'})))
    with pytest.raises(RuntimeError, match='Enter'):
        session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.draft == '有喔' and not scene.discarded_drafts
    assert not session._observer.history


@pytest.mark.parametrize('key', ['return', 'Enter', ' enter '])
def test_existing_enter_aliases_still_submit(channel_session, key):
    session, win, _, _, _, scene = channel_session
    session._config = replace(session._config, whisper_actions=(
        *session._config.whisper_actions[:-1],
        action_from_dict({'type': 'key_press', 'key': key})))
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'whisper')]


@pytest.mark.parametrize('cancel', ['stop', 'close'])
def test_cancel_during_input_inspection_never_types_reply(channel_session, cancel):
    session, win, _, _, stop, scene = channel_session
    scene.channel = 'public'
    prepare = session._prepare_chat_input
    count = 0
    def cancelled_prepare(target):
        nonlocal count
        region = prepare(target)
        count += 1
        if count == 2:
            stop.set() if cancel == 'stop' else session.close()
        return region
    session._prepare_chat_input = cancelled_prepare
    session._send_replies([(ChatMessage(1, 'map', '朋友', '在嗎'), '有喔')], win)
    assert scene.typed_channels == []
    assert not scene.sent and not session._observer.history


@pytest.mark.parametrize('cancel', ['stop', 'close'])
def test_cancel_during_typing_settle_prevents_late_submit_or_cleanup(channel_session, cancel):
    session, win, backend, _, stop, scene = channel_session
    typed = threading.Event()
    original = backend.type_text
    def type_text(text):
        original(text)
        if text == '有喔':
            typed.set()
    backend.type_text = type_text
    errors = []
    def send():
        try:
            session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=send)
    worker.start()
    try:
        assert typed.wait(8)
        stop.set() if cancel == 'stop' else session.close()
        worker.join(.4)
        assert not worker.is_alive()
        assert not scene.sent and not scene.discarded_drafts and not errors
        assert not session._observer.history
        assert backend.calls[-1] == ('type_text', '有喔')
    finally:
        stop.set()
        worker.join(3)


def test_h_prefilled_highlighted_name_is_confirmed_with_enter(channel_session):
    # 實機 14:07：帶入的名字反白，6 幀都「不確定」，被誤判成沒有名字而略過。
    session, win, _, records, _, scene = channel_session
    scene.recipient_highlighted = True
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert scene.sent == [('有喔', 'whisper')]
    assert not any('沒有名字' in r['message'] for r in records)


def test_missed_h_is_pressed_once_more_then_whisper_is_sent(channel_session):
    # 實機 22:40：按 H 後 0.9 秒內沒看到密語視窗就停掉腳本。
    session, win, backend, records, _, scene = channel_session
    scene.ignored_h = 1
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert [c[1] for c in backend.calls if c[0] in ('key_press', 'key_down')].count('h') == 2
    assert scene.sent == [('有喔', 'whisper')]
    assert any('補按 H' in r['message'] for r in records)


def test_h_is_retried_only_once(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.open_recipient = False
    expect_skipped(session, [(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win, match='未找到密語對象視窗')
    assert [c[1] for c in backend.calls if c[0] in ('key_press', 'key_down')].count('h') == 2
    assert scene.typed_channels == []


def _h_presses(backend):
    return [c[1] for c in backend.calls if c[0] in ('key_press', 'key_down')].count('h')


def test_open_but_unrecognized_whisper_dialog_is_not_given_an_extra_h(channel_session):
    # 實機 2026-10-27 20:03：視窗已開但被游標擋住認不出 → 補按 H 把名字換成「h」。
    session, win, backend, records, _, scene = channel_session
    scene.recipient_highlighted = True
    scene.header_obscured = True
    move = backend.mouse_move

    def move_away(x, y):
        move(x, y)
        scene.header_obscured = False   # 游標移開後看得到藍色標題

    backend.mouse_move = move_away
    session._send_replies([(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win)
    assert _h_presses(backend) == 1
    assert scene.sent == [('有喔', 'whisper')]
    assert not any('補按 H' in r['message'] for r in records)


def test_dialog_that_stays_unrecognized_is_skipped_without_typing_h(channel_session):
    session, win, backend, _, _, scene = channel_session
    scene.recipient_highlighted = True
    scene.header_obscured = True
    expect_skipped(session, [(ChatMessage(1, 'whisper', '朋友', '在嗎'), '有喔')], win,
                   match='無法確認')
    assert _h_presses(backend) == 1
    assert 'h' not in [t for t, _ in scene.typed_channels]
    assert scene.sent == []


def test_channel_button_hidden_by_pointer_is_found_after_moving_pointer_away(channel_session):
    # 實機 23:09：只看一張就「找不到聊天頻道按鈕」停掉腳本。
    session, win, backend, _, _, scene = channel_session
    scene.has_input_bar = False
    move = backend.mouse_move

    def move_away(x, y):
        move(x, y)
        scene.has_input_bar = True     # 游標移開後按鈕重新出現

    backend.mouse_move = move_away
    scene.channel = 'public'
    session._ensure_public_channel(win, force_select=True)
    assert scene.channel == 'public' and not scene.menu
