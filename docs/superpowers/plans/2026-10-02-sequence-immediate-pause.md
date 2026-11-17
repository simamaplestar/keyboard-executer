# Sequence Immediate Pause Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax for tracking.

**Goal:** OCR detection immediately cooperatively pauses script input; AI waits for release acknowledgement; successful handling resumes remaining work; ship a verified exe.

**Architecture:** One Player input owner. A sequence-only pause coordinator preserves timed waits and held-key state. Watcher AI scheduling is gated by a round-specific acknowledgement in production; capture/OCR and Discord remain background-only. Checked platform mouse operations prevent input after pause during settle.

**Tech Stack:** Python, threading, pytest, existing Win32/pynput backends, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-02-sequence-immediate-pause-design.md`

## Global Constraints
- Work on existing main, no worktrees/branches/commits; preserve existing .git/index.lock and unrelated edits.
- OCR first; no panel startup AI; Discord once per detected round, nonblocking.
- 20ms cooperative waits, no claim of hard real-time native cancellation.
- No background native input; no clearing stop_event; no replay of completed side effects.
- Absolute 25/30s watcher deadlines never pause. Foreground/geometry checks remain mandatory.
- Back up old exe before replacing packaging/dist/KeyboardExecutor.exe.

## Review Focus
- Stop during key release/restore must prevent re-press (Task 2).
- Multi-round stale acknowledgement cannot unlock recognition (Task 1).
- A short tap interrupted during hold cannot be replayed (Task 2).
- Mouse settle invalidates pending coordinates; interrupted drag must release then stop (Task 3).
- Native matching returning after pause cannot reuse its old visual result (Task 2).

## Task 1: Runtime handshake and startup INFO
**Files:** core/sequence_panel_watcher.py, core/sequence_watcher.py, core/visual_intervention.py, app/sequence_input_service.py; tests/core/test_sequence_pause_handshake.py.
**Interfaces:** watchers `require_input_release()` and `acknowledge_pause(round_id) -> bool`; VisualIntervention `sequence_pending() -> bool` and `pause_for_sequence(script, win) -> bool`. The real runtime installs the gate before start. Standalone watcher callers retain historical scheduling unless they install the gate.
- [ ] Write regression: gate scheduling, acknowledge wrong/current round, idle AI zero, start INFO once and not on cancelled/closed start. Assert `calls == []` before acknowledgement, then one request after acknowledgement.
- [ ] Run focused tests and observe RED.
- [ ] Add opt-in gate to both watchers, acknowledge only live COLLECTING/READY rounds with input owner present. Runtime enables gate at construction and acknowledges before submitter.run. Keep fake/third-party boundary-only callbacks compatible.
- [ ] Start logging on actual start including panel region and boolean Discord configuration, never webhook URL. Separate reliable Python INFO from lossy progress callbacks.
- [ ] Run watcher/runtime/service tests GREEN; record evidence (no commit).

## Task 2: Player resumable sequence checkpoint
**Files:** new core/sequence_pause.py; core/player.py; new tests/core/test_player_sequence_pause.py.
**Interfaces:** `SequencePause(runtime, stop, clock, sleep)` provides `pending`, `checkpoint(script,win) -> bool`, `wait(seconds,script,win)`, `hold(keys,seconds,script,win,backend,repeat=False,restore=True)` and `paused_seconds`. Throws a dedicated pause failure on failed handling; Player converts it to its existing abort result. No input on worker threads.
- [ ] Write timed regression with fake clock: trigger at 3s of 10s, handler spends 5s; assert key-up precedes handler, next key-down follows handler, wall time ~15s, hold budget remains 10s.
- [ ] Cover delay, repeated pause, F10 inside handler, failed release, short tap (no second key-down), key repeat, nested script position, character progress, unchanged non-sequence sleep.
- [ ] Run RED; implement helper and enabled-only Player paths. Current action context is stack-scoped. Include sequence checks before input and after native reads; pause generation invalidates visual matching results.
- [ ] Poll timeout uses logical action time (monotonic minus pause duration); watcher remains on original absolute clock.
- [ ] Run Player/sequence/chat boundary tests GREEN.

## Task 3: Checked mouse continuation
**Files:** platforms/base.py, platforms/common/input_pynput.py, platforms/win32/input.py; Player integration; tests/platforms/test_sequence_checked_mouse.py and Player tests.
**Interfaces:** `mouse_drag_checked(..., *, check, before_press=None)` and `scroll_checked(..., *, check)`. `check` may raise an internal interruption; drag always releases in finally. Default unsupported checked operations fail closed, not silently use unsafe legacy methods.
- [ ] Write tests injecting request during settle; verify no wheel/click after interruption and held mouse release.
- [ ] Run RED; implement checked primitives with <=20ms settle checks on supported native backends; preserve ordinary methods.
- [ ] Player retries only operations whose effect has not begun after a handled pause, refreshes coordinates, and stops after handling if drag already started. For clicks, use one guarded click per iteration so completed clicks are never replayed.
- [ ] Run mouse and Player integration tests GREEN.

## Task 4: Verification, review, documentation, packaging
**Files:** README.md, docs/sequence-input-implementation-report.md, docs/sequence-input-manual-checklist.md; packaging outputs.
- [ ] Run focused Linux suite; Windows full `python -m pytest -q` with existing build venv and offscreen Qt.
- [ ] Review changed files against external pre-edit backup (not dirty HEAD). Test every Important finding RED→GREEN and rerun regressions/full Windows suite.
- [ ] Document actual guarantees and native-call/drag limitations; mark real service/game acceptance outstanding.
- [ ] Hash build inputs, clean build using existing spec into isolated dist/build subdirectories; verify unchanged sources, embedded modules/models, --help, and isolated-data GUI responsive startup/normal close.
- [ ] Back up current published exe; copy new exe; verify SHA256 equality. Report final path and fresh test results.
