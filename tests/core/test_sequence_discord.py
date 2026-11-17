import threading
import pytest


def notifier(url='https://discord.com/api/webhooks/test/token', sender=None, progress=None, stop=None):
    from keyboard_executor.core.sequence_discord import make_sequence_notifier
    return make_sequence_notifier(url, stop or threading.Event(), progress, sender=sender)


def test_once_per_round_text_only():
    calls = []
    send = notifier(sender=lambda *args, **kw: calls.append((args, kw)))
    send(1); send(1); send(2); send(1)
    assert len(calls) == 2
    assert '圖片順序輸入' in calls[0][0][1]
    assert calls[0][1] == {'timeout': 5.0}


def test_no_webhook_or_cancel_no_network():
    calls = []
    stop = threading.Event(); stop.set()
    notifier(url='', sender=lambda *a, **kw: calls.append(a))(1)
    notifier(stop=stop, sender=lambda *a, **kw: calls.append(a))(1)
    assert calls == []


def test_failure_isolated_and_secret_not_logged(caplog):
    messages = []
    def fail(*a, **kw): raise RuntimeError('super-secret-webhook-url')
    send = notifier(sender=fail, progress=messages.append)
    send(1); send(1)
    assert 'super-secret' not in caplog.text
    assert len(messages) == 1
    assert '失敗' in messages[0]['message']


def test_only_one_transport_in_flight():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(*a, **kw):
        calls.append(a); entered.set(); release.wait(2)
    send = notifier(sender=slow)
    worker = threading.Thread(target=lambda: send(1)); worker.start()
    try:
        assert entered.wait(1)
        send(2)
        assert len(calls) == 1
    finally: release.set(); worker.join(2)


def test_outcome_is_sent_once_per_round_even_after_stop():
    from keyboard_executor.core.sequence_discord import make_sequence_outcome_notifier
    calls = []
    outcome = make_sequence_outcome_notifier('https://discord.com/api/webhooks/test/token',
                                             sender=lambda *a, **kw: calls.append(a[1]))
    outcome(1, False, '未能在 18 秒內完成辨識與安全定位，已停止')
    outcome(1, False, '重複')
    outcome(2, True, '已輸入 ABC，提示已消失（9 秒）')
    assert len(calls) == 2
    assert '失敗' in calls[0] and '18 秒' in calls[0] and '回合 1' in calls[0]
    assert '成功' in calls[1] and 'ABC' in calls[1]


def test_outcome_without_webhook_or_with_transport_error_never_raises(caplog):
    from keyboard_executor.core.sequence_discord import make_sequence_outcome_notifier
    make_sequence_outcome_notifier('')(1, True, 'x')
    def fail(*a, **kw): raise RuntimeError('super-secret-webhook-url')
    messages = []
    make_sequence_outcome_notifier('https://x', messages.append, sender=fail)(1, False, 'y')
    assert 'super-secret' not in caplog.text
    assert messages and '失敗' in messages[0]['message']
