"""Chat now uses the same OCR contract as every other consumer."""
import pytest

from tests.core.test_chat_reply import close_sessions, make_session


@pytest.mark.parametrize('recognize', [False, True])
def test_chat_scan_uses_unified_recognize_only_when_needed(recognize):
    session, _, win, _, _, _, _ = make_session()
    engine = session._platform.ocr_engine
    # An obsolete optional method must not divert chat to a different backend.
    engine.recognize_chat = lambda _: pytest.fail('obsolete OCR profile selected')
    before = len(engine.calls)
    session._read_frame(win, recognize=recognize)
    assert len(engine.calls) - before == int(recognize)
