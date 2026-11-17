"""Best-effort text-only notification, called on the watcher's notice worker."""
import logging
import threading
from keyboard_executor.core.discord_notify import post_discord

logger = logging.getLogger(__name__)


def make_sequence_notifier(webhook_url, stop_event, on_progress=None, *, sender=None):
    sender = sender or post_discord
    state_lock, transport_lock = threading.Lock(), threading.Lock()
    last_round = 0

    def report(message):
        logger.info('%s', message)
        if on_progress:
            try:
                on_progress(dict(kind='notify', message=message))
            except Exception:
                logger.warning('Discord 狀態回呼失敗')

    def notify(round_id):
        nonlocal last_round
        with state_lock:
            if stop_event.is_set() or round_id <= last_round:
                return
            last_round = round_id
        if not webhook_url:
            report('尚未設定 Discord Webhook，略過面板通知')
            return
        if not transport_lock.acquire(blocking=False):
            report('Discord 前次通知仍在傳送，略過本次通知')
            return
        try:
            if stop_event.is_set():
                return
            try:
                sender(webhook_url, f'Keyboard Executor：偵測到圖片順序輸入提示，開始辨識（回合 {round_id}）。',
                       timeout=5.0)
            except Exception:
                # Exception messages may contain the secret webhook URL.
                report('Discord 面板通知傳送失敗；辨識繼續，不重試')
            else:
                report('Discord 面板通知已傳送')
        finally:
            transport_lock.release()
    return notify


def make_sequence_outcome_notifier(webhook_url, on_progress=None, *, sender=None):
    """每回合結束（成功或失敗）各通知一次；失敗時腳本已停止，不看 stop_event。"""
    sender = sender or post_discord
    lock = threading.Lock()
    done = set()

    def outcome(round_id, ok, message):
        with lock:
            if round_id in done:
                return
            done.add(round_id)
        if not webhook_url:
            return
        status = '成功' if ok else '失敗，腳本已停止，請手動處理'
        try:
            sender(webhook_url, f'Keyboard Executor：圖片順序輸入{status}（回合 {round_id}）：{message}',
                   timeout=5.0)
        except Exception:
            # Exception messages may contain the secret webhook URL.
            logger.info('Discord 結果通知傳送失敗')
            if on_progress:
                try:
                    on_progress(dict(kind='notify', message='Discord 結果通知傳送失敗'))
                except Exception:
                    pass
        else:
            logger.info('Discord 結果通知已傳送')
    return outcome
