"""The game paints its pointer into captures of an otherwise valid name field."""
from dataclasses import replace
from pathlib import Path

import cv2
import pytest

from keyboard_executor.core.chat_channel import chat_input_has_text
from tests.core.test_chat_reply import make_session


@pytest.mark.parametrize('placement', ['on_name', 'on_blank'])
@pytest.mark.parametrize('removable', [True, False])
def test_uncertain_recipient_field_is_recaptured_after_moving_pointer(placement, removable):
    session, _, win, backend, _, _, _ = make_session()
    win = replace(win, x=1702, y=80, width=1927, height=1240)
    session._platform.window_manager.windows = [win]
    region = (741, 629, 445, 30)
    root = Path(__file__).parents[1] / 'fixtures/chat'
    obscured = cv2.imread(str(root / f'recipient_pointer_{placement}.png'))
    clear = cv2.imread(str(root / 'recipient_pointer_clear.png'))
    assert chat_input_has_text(obscured) is None
    assert chat_input_has_text(clear) is True
    pointer = [win.x + 766, win.y + 644]
    frames = []

    def capture(rect):
        assert (rect.x, rect.y, rect.width, rect.height) == (2443, 709, 445, 30)
        overlaps = (rect.x - 40 <= pointer[0] <= rect.x + rect.width + 40
                    and rect.y - 40 <= pointer[1] <= rect.y + rect.height + 40)
        image = obscured if overlaps or not removable else clear
        frames.append(image)
        return image.copy()

    move = backend.mouse_move

    def mouse_move(x, y):
        assert win.x <= x < win.x + win.width
        assert win.y <= y < win.y + win.height
        pointer[:] = [x, y]
        move(x, y)

    session._platform.screen_capture.capture = capture
    backend.mouse_move = mouse_move
    try:
        appeared, state, _ = session._wait_input_state(win, region, True)
        assert appeared is removable
        assert state is (True if removable else None)
        assert frames[0] is obscured
        if removable:
            assert all(frame is clear for frame in frames[-2:])
        # A changed pointer alone never proves text appeared. One move is enough;
        # persistent obstruction must time out without confirming or sending.
        assert len(backend.calls) == 1 and backend.calls[0][0] == 'mouse_move'
    finally:
        session.close()
