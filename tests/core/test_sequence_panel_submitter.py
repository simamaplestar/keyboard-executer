from dataclasses import replace
import pytest
from keyboard_executor.core.sequence_panel import PanelTarget
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from tests.core.test_sequence_submitter import build


def install_target(submitter, now, **changes):
    target = replace(PanelTarget(1, (0, 0, 500, 500), (150, 200), (320, 200), 1.0, 8), **changes)
    from keyboard_executor.core.sequence_submitter import SequenceSubmitter
    return SequenceSubmitter(submitter._platform,
        sequence_config_from_dict(dict(enabled=True, mode='panel', panel_region=[0, 0, 400, 300])),
        submitter._watcher, submitter._stop, clock=lambda: now[0], target_provider=lambda rid: target)


def test_panel_points_replace_manual_config():
    old, watcher, platform, win, stop, now = build()
    submitter = install_target(old, now)
    assert submitter.run(win)
    assert [c[1:3] for c in platform.input_backend.calls if c[0] == 'mouse_click'] == [(150, 200), (320, 200)]


@pytest.mark.parametrize('changes', [dict(round_id=2), dict(captured_at=-2),
    dict(captured_at=5), dict(window_geometry=(10, 0, 500, 500)), dict(input_point=(501, 20))])
def test_invalid_target_never_clicks(changes):
    old, watcher, platform, win, stop, now = build()
    submitter = install_target(old, now, **changes)
    assert not submitter.run(win)
    assert not any(c[0] == 'mouse_click' for c in platform.input_backend.calls)


@pytest.mark.parametrize('phase', ['FAILED', 'STOPPED', 'VERIFYING'])
def test_round_change_during_native_window_query_blocks_input(phase):
    old, watcher, platform, win, stop, now = build()
    submitter = install_target(old, now)
    watcher.phase = 'SUBMITTING'
    def refresh(window):
        watcher.phase = phase
        return win
    platform.window_manager.refresh = refresh
    with pytest.raises(RuntimeError):
        submitter._check(win, 1, (0, 0, 500, 500))
    assert not platform.input_backend.calls


def test_target_expires_during_native_settle():
    old, watcher, platform, win, stop, now = build()
    submitter = install_target(old, now)
    def delayed(x, y, button, clicks, *, check, before_click=None):
        now[0] = 4
        check()
        pytest.fail('expired target was allowed to click')
    platform.input_backend.mouse_click_checked = delayed
    assert not submitter.run(win)
    assert not any(c[0] == 'mouse_click' for c in platform.input_backend.calls)
