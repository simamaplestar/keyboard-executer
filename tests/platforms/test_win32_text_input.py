import ctypes

import pytest


def test_literal_text_sends_utf16_packets_including_ascii_and_surrogate_pair():
    from keyboard_executor.platforms.win32.text_input import send_unicode_text
    batches = []
    def send(count, events, size):
        batches.append((size, [(e.type, e.ki.wVk, e.ki.wScan, e.ki.dwFlags) for e in events]))
        return count
    send_unicode_text('A-測🙂', send_input=send)
    assert len(batches) == 1
    size, events = batches[0]
    assert size == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    assert events == [
        (1, 0, 65, 4), (1, 0, 65, 6),
        (1, 0, 45, 4), (1, 0, 45, 6),
        (1, 0, 0x6e2c, 4), (1, 0, 0x6e2c, 6),
        (1, 0, 0xd83d, 4), (1, 0, 0xd83d, 6),
        (1, 0, 0xde42, 4), (1, 0, 0xde42, 6),
    ]


@pytest.mark.parametrize('sent', [0, 1])
def test_partial_or_blocked_unicode_input_stops_without_retyping(sent):
    from keyboard_executor.platforms.win32.text_input import send_unicode_text
    calls = []
    def send(count, events, size):
        calls.append(count)
        return sent
    with pytest.raises(RuntimeError, match='文字輸入未完成'):
        send_unicode_text('A', send_input=send)
    assert calls == [2]


def test_empty_literal_text_does_not_call_native_input():
    from keyboard_executor.platforms.win32.text_input import send_unicode_text
    calls = []
    send_unicode_text('', send_input=lambda *args: calls.append(args))
    assert calls == []


def test_literal_input_does_not_change_shared_sendinput_signature(monkeypatch):
    from types import SimpleNamespace
    from keyboard_executor.platforms.win32.text_input import send_unicode_text
    class Sender:
        argtypes = ['existing keyboard backend signature']
        restype = 'existing result type'
        def __call__(self, count, events, size):
            return count
    shared, isolated = Sender(), Sender()
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(SendInput=shared)), raising=False)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: SimpleNamespace(SendInput=isolated), raising=False)
    send_unicode_text('A')
    assert shared.argtypes == ['existing keyboard backend signature']
    assert shared.restype == 'existing result type'
