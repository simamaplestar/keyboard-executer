import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent

from keyboard_executor.app.script_editor import (
    ActionForm,
    LoopActionForm,
    ScriptEditorDialog,
    _chip_spec,
    _connector_points,
    _KeyCaptureEdit,
    _qt_key_to_name,
    even_layout,
    order_from_positions,
    wrap_rows,
)


def _kp(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    return QKeyEvent(QEvent.Type.KeyPress, key, mods, text)


def _kr(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    return QKeyEvent(QEvent.Type.KeyRelease, key, mods, text)


from keyboard_executor.app.script_editor_model import ScriptEditorModel
from keyboard_executor.core.models import script_from_dict, ScriptValidationError
from keyboard_executor.storage.scripts import ScriptStorage


def make_dialog(tmp_path, lister=None):
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"},
                    {"type": "delay", "ms": 100}]})
    model = ScriptEditorModel(script)
    return ScriptEditorDialog(model, ScriptStorage(tmp_path), window_lister=lister), model


def test_dialog_constructs_with_chips_and_add_action(qapp, tmp_path):
    dialog, model = make_dialog(tmp_path)
    assert dialog.chip_count() == 2
    assert model.rows()[0]["label"] == "按鍵 a"
    dialog.add_action("text_input", {"text": "哈囉"})
    assert len(model) == 3
    assert dialog.chip_count() == 3


def test_arrows_connect_consecutive_chips(qapp, tmp_path):
    dialog, _ = make_dialog(tmp_path)            # 2 個動作 → 1 個箭頭
    assert dialog.chip_count() == 2
    assert dialog.arrow_count() == 1
    dialog.add_action("text_input", {"text": "x"})   # 3 個動作 → 2 個箭頭
    assert dialog.chip_count() == 3
    assert dialog.arrow_count() == 2


def test_single_chip_has_no_arrow(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("單一")
    model.insert(0, {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage)
    assert dialog.chip_count() == 1
    assert dialog.arrow_count() == 0


def test_order_from_positions_left_to_right():
    assert order_from_positions([(0, 0), (100, 0), (200, 0)], band=80) == [0, 1, 2]
    assert order_from_positions([(200, 0), (0, 0), (100, 0)], band=80) == [1, 2, 0]


def test_order_from_positions_top_row_before_bottom():
    # 兩列：上列(y=0) 整列先於下列(y=200)，列內由左到右
    assert order_from_positions([(0, 200), (0, 0)], band=80) == [1, 0]
    assert order_from_positions([(300, 0), (0, 0), (50, 200)], band=80) == [1, 0, 2]


def test_model_reorder_applies_permutation():
    model = ScriptEditorModel.new("r")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    model.reorder([2, 0, 1])
    assert [model.action_at(i)["key"] for i in range(3)] == ["c", "a", "b"]


def test_loop_group_shows_inner_actions(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    dialog = ScriptEditorDialog(model, storage)
    assert dialog.chip_count() == 1                 # 迴圈是一個外框節點
    assert dialog._nodes[0].inner_count() == 2      # 框內看得到 2 個內含動作


def test_update_loop_inner_replaces_action_keeps_count():
    model = ScriptEditorModel.new("x")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    assert model.loop_inner_at(0, 0)["key"] == "a"
    model.update_loop_inner(0, 0, {"type": "key_press", "key": "b", "hold_ms": 200})
    inner = model.action_at(0)["actions"]
    assert inner[0]["key"] == "b" and inner[0]["hold_ms"] == 200
    assert inner[1]["type"] == "delay"        # 其他內含動作不動
    assert model.action_at(0)["count"] == 3   # 重複次數保留


def _loop_model():
    model = ScriptEditorModel.new("x")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    return model


def test_add_to_loop_appends_and_revalidates():
    model = _loop_model()
    model.add_to_loop(0, {"type": "delay", "ms": 80})
    inner = model.action_at(0)["actions"]
    assert len(inner) == 3
    assert inner[2] == {"type": "delay", "ms": 80}
    assert model.action_at(0)["count"] == 3         # 次數保留


def test_add_to_loop_non_loop_noop():
    model = ScriptEditorModel.new("x")
    model.insert(0, {"type": "key_press", "key": "a"})
    model.add_to_loop(0, {"type": "delay", "ms": 80})   # index 0 非 loop
    assert model.action_at(0)["type"] == "key_press"


def test_add_to_loop_invalid_raises_and_keeps_state():
    model = _loop_model()
    with pytest.raises(ScriptValidationError):
        model.add_to_loop(0, {"type": "delay"})          # 缺 ms
    assert len(model.action_at(0)["actions"]) == 2       # 狀態不變


def test_loop_inner_double_click_emits_signal(qapp):
    # 直接建 _LoopGroup（不透過 dialog），才不會觸發會開 modal 的 _edit_loop_inner
    from keyboard_executor.app.script_editor import _InnerChip, _LoopGroup
    action = {"type": "loop", "count": 3, "actions": [
        {"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]}
    loop = _LoopGroup(0, action, 1.0)
    inners = loop.findChildren(_InnerChip)
    assert len(inners) == 2
    captured = []
    loop.innerDoubleClicked.connect(lambda li, ii: captured.append((li, ii)))
    inners[1].doubleClicked.emit(1)           # 模擬雙擊第 2 個內含動作
    assert captured == [(0, 1)]


def test_loop_group_wraps_full_chips_not_mini(qapp, tmp_path):
    from PySide6.QtWidgets import QFrame
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    dialog = ScriptEditorDialog(model, storage)
    loop = dialog._nodes[0]
    inner = [c for c in loop.findChildren(QFrame) if c.objectName() == "chip"]
    assert len(inner) == 2                          # 兩個「完整」chip（非縮小 mini）
    assert sorted(c.property("kind") for c in inner) == ["delay", "key"]


def test_loop_group_has_add_chip_emitting_index(qapp):
    from keyboard_executor.app.script_editor import _InnerAddChip, _InnerChip, _LoopGroup
    action = {"type": "loop", "count": 3, "actions": [
        {"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]}
    loop = _LoopGroup(0, action, 1.0)
    adds = loop.findChildren(_InnerAddChip)
    assert len(adds) == 1                              # 末端一個「＋新增」
    assert len(loop.findChildren(_InnerChip)) == 2     # 內含動作 chip 仍是 2（不含「＋」）
    captured = []
    loop.addClicked.connect(captured.append)
    adds[0].clicked.emit()
    assert captured == [0]                             # 帶迴圈索引


def test_loop_group_renders_all_inner_chips_when_many(qapp):
    from keyboard_executor.app.script_editor import _InnerChip, _LoopGroup
    action = {"type": "loop", "count": 2,
              "actions": [{"type": "delay", "ms": 10}] * 8}
    loop = _LoopGroup(0, action, 1.0)
    assert len(loop.findChildren(_InnerChip)) == 8     # 多動作換列不遺漏
    assert loop.inner_count() == 8


def test_even_layout_equal_gaps_single_row():
    # 依實際寬度校正距離，相鄰間隔一律等於 gap（不受不同寬度影響）
    pts = even_layout([(100, 50), (60, 50), (80, 50)], max_width=1000, gap=20, start=10)
    assert pts == [(10, 10), (130, 10), (210, 10)]


def test_even_layout_wraps_rows():
    pts = even_layout([(100, 40), (100, 40), (100, 40)], max_width=250, gap=20, start=10)
    assert pts == [(10, 10), (130, 10), (10, 70)]


def test_even_layout_vertically_centers_row():
    # 同列不同高度（如迴圈框較高）→ 垂直置中，中心 y 對齊，箭頭才不會歪
    pts = even_layout([(100, 40), (100, 80)], max_width=1000, gap=20, start=10)
    assert pts == [(10, 30), (130, 10)]                 # 矮的往下移到列中央
    assert pts[0][1] + 40 // 2 == pts[1][1] + 80 // 2   # 兩者中心 y 相同


def test_canvas_rubber_picks_intersecting_nodes(qapp, tmp_path):
    dialog, _ = make_dialog(tmp_path)          # 2 個 chip
    for n in dialog._nodes:
        n.resize(80, 50)
    dialog._nodes[0].move(0, 0)
    dialog._nodes[1].move(400, 0)
    assert dialog.canvas.nodes_in_rect(QRect(0, 0, 100, 100)) == [0]
    assert dialog.canvas.nodes_in_rect(QRect(0, 0, 500, 100)) == [0, 1]


def test_rubber_selection_sets_multi(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("R")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._on_rubber([0, 1])                  # 框選前兩個
    assert dialog._selection_indices() == [0, 1]


def test_qt_key_to_name_arrows_specials_chars(qapp):
    assert _qt_key_to_name(_kp(Qt.Key.Key_Up)) == "up"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Left)) == "left"
    assert _qt_key_to_name(_kp(Qt.Key.Key_F5)) == "f5"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Return)) == "enter"
    assert _qt_key_to_name(_kp(Qt.Key.Key_A, text="a")) == "a"


def test_key_capture_edit_records_single_key(qapp):
    w = _KeyCaptureEdit()
    w._start()
    w.keyPressEvent(_kp(Qt.Key.Key_Down))
    assert w.text() == "down"


def test_key_capture_edit_records_combo(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    w.keyPressEvent(_kp(Qt.Key.Key_S, mods, "s"))
    w.keyReleaseEvent(_kr(Qt.Key.Key_S, mods, "s"))
    assert w.text() == "ctrl+shift+s"


def test_key_capture_edit_records_multi_key_combo(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    shift = Qt.KeyboardModifier.ShiftModifier
    w.keyPressEvent(_kp(Qt.Key.Key_Shift, shift))
    w.keyPressEvent(_kp(Qt.Key.Key_A, shift, "a"))
    w.keyPressEvent(_kp(Qt.Key.Key_Right, shift))
    w.keyReleaseEvent(_kr(Qt.Key.Key_Right, shift))
    assert w.text() == ""                       # shift、a 還按著 → 尚未定案
    w.keyReleaseEvent(_kr(Qt.Key.Key_A, shift))
    assert w.text() == ""                       # shift 還按著
    w.keyReleaseEvent(_kr(Qt.Key.Key_Shift))
    assert w.text() == "shift+a+right"          # 全部放開才定案


def test_key_capture_combo_sequential_taps_while_holding_modifier(qapp):
    # 使用者按住 shift、依序「點」a 再「點」right（點＝按下即放開），最後放開 shift。
    # 舊版「放開第一個鍵就定案」會在放開 a 當下就變成 shift+a，吃不到 right。
    w = _KeyCaptureEdit(combo=True)
    w._start()
    shift = Qt.KeyboardModifier.ShiftModifier
    w.keyPressEvent(_kp(Qt.Key.Key_Shift, shift))
    w.keyPressEvent(_kp(Qt.Key.Key_A, shift, "a"))
    w.keyReleaseEvent(_kr(Qt.Key.Key_A, shift))
    w.keyPressEvent(_kp(Qt.Key.Key_Right, shift))
    w.keyReleaseEvent(_kr(Qt.Key.Key_Right, shift))
    assert w.text() == ""                       # shift 仍按著 → 未定案
    w.keyReleaseEvent(_kr(Qt.Key.Key_Shift))
    assert w.text() == "shift+a+right"


def test_key_capture_combo_ignores_autorepeat(qapp):
    w = _KeyCaptureEdit(combo=True)
    w._start()
    rep = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                    Qt.KeyboardModifier.NoModifier, "a", True)   # autoRepeat=True
    w.keyPressEvent(rep)
    w.keyReleaseEvent(_kr(Qt.Key.Key_A, text="a"))
    assert w.text() == ""                       # autorepeat 的 press 被忽略 → 不定案


def test_action_form_uses_key_capture_for_key_field(qapp):
    form = ActionForm("key_press")
    assert isinstance(form._edits["key"], _KeyCaptureEdit)
    form._edits["key"].setText("up")
    assert form.values()["key"] == "up"


# ---- 座標取點：動作存的是視窗相對座標，使用者無從目測，故必須能在畫面上選 ----

class _FakeWin:
    x, y = 100, 50


class _FakeWinMgr:
    def __init__(self, windows, can_activate=True):
        self.windows = windows
        self.activated = []
        self.can_activate = can_activate

    def find_windows(self, title_pattern=None):
        return self.windows

    def activate(self, window):
        self.activated.append(window)
        return self.can_activate

    def refresh(self, window):
        return window


class _FakePlatform:
    def __init__(self, windows):
        self.window_manager = _FakeWinMgr(windows)


def _form_with_window(atype, windows=(_FakeWin(),), title="遊戲"):
    return ActionForm(atype, get_target_window=lambda: title,
                      get_platform=lambda: _FakePlatform(list(windows)),
                      capture_factory=lambda: None)


@pytest.mark.parametrize("atype", ["mouse_click", "mouse_move", "scroll"])
def test_xy_actions_offer_coordinate_picker(qapp, atype):
    assert _form_with_window(atype).pick_button is not None


def test_pick_xy_fills_both_fields(qapp):
    """一次取點要同時填 x 與 y（使用者不必分兩次選）。"""
    form = _form_with_window("mouse_click")
    form._open_point_picker = lambda on_point: on_point(12, 34)
    form._pick_xy()
    values = form.values()
    assert values["x"] == "12" and values["y"] == "34"
    assert "12, 34" in form.pick_status.text()


def test_drag_point_fields_fill_as_pair(qapp):
    """起點/終點是 point 型別，須回填成 to_action_dict 看得懂的 "x, y" 格式。"""
    form = _form_with_window("mouse_drag")
    form._open_point_picker = lambda on_point: on_point(12, 34)
    form._pick_point("from")
    assert form.values()["from"] == "12, 34"


def test_pick_without_target_window_explains_instead_of_opening(qapp):
    form = ActionForm("mouse_click", get_target_window=lambda: "",
                      get_platform=lambda: _FakePlatform([]),
                      capture_factory=lambda: None)
    form._pick_xy()
    assert "視窗標題" in form.pick_status.text()
    assert form._overlay is None       # 沒有目標視窗就不該開覆蓋層


def test_pick_with_unmatched_window_reports_not_found(qapp):
    form = _form_with_window("mouse_click", windows=())
    form._pick_xy()
    assert "找不到符合" in form.pick_status.text()
    assert form._overlay is None


def test_resolve_window_returns_first_match(qapp):
    form = _form_with_window("mouse_click")
    assert form._resolve_window().x == 100


def test_snapshot_restore_roundtrip():
    model = ScriptEditorModel.new("s")
    model.insert(0, {"type": "key_press", "key": "a"})
    snap = model.snapshot()
    model.insert(1, {"type": "delay", "ms": 50})
    assert len(model) == 2
    model.restore(snap)
    assert len(model) == 1 and model.action_at(0)["key"] == "a"


def test_undo_redo_add_action(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("u")
    model.insert(0, {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage)
    dialog.add_action("key_press", {"key": "b", "hold_ms": "0"})
    assert len(dialog._model) == 2
    dialog._undo()
    assert len(dialog._model) == 1 and dialog._model.action_at(0)["key"] == "a"
    dialog._redo()
    assert len(dialog._model) == 2 and dialog._model.action_at(1)["key"] == "b"


def test_undo_restores_removed_actions(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("u2")
    for k in "ab":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._on_rubber([0])
    dialog._delete()
    assert [dialog._model.action_at(i)["key"] for i in range(len(dialog._model))] == ["b"]
    dialog._undo()
    assert [dialog._model.action_at(i)["key"] for i in range(len(dialog._model))] == ["a", "b"]


def test_copy_paste_appends_selected_actions(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("cp")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._on_rubber([0, 1])          # 框選前兩個
    dialog._copy()
    dialog._paste()
    keys = [dialog._model.action_at(i)["key"] for i in range(len(dialog._model))]
    assert keys == ["a", "b", "c", "a", "b"]


def test_cut_then_paste_moves_actions(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("cut")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._on_rubber([0])
    dialog._cut()
    assert [dialog._model.action_at(i)["key"] for i in range(len(dialog._model))] == ["b", "c"]
    dialog._paste()
    assert [dialog._model.action_at(i)["key"] for i in range(len(dialog._model))] == ["b", "c", "a"]


def test_paste_without_copy_is_noop(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("np")
    model.insert(0, {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage)
    dialog._paste()
    assert len(dialog._model) == 1


def test_layout_persists_across_reopen(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("持久")
    for k in "ab":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog.title_edit.setText(".*記事本.*")
    dialog._positions = [QPoint(50, 60), QPoint(200, 60)]
    dialog._zoom = 0.8
    dialog._on_save()
    # 重開：版面應原樣還原，不再自動改變樣子
    reopened = ScriptEditorDialog(ScriptEditorModel(storage.load("持久")), storage)
    assert [(p.x(), p.y()) for p in reopened._positions] == [(50, 60), (200, 60)]
    assert reopened._zoom == 0.8


def test_connector_forward_is_straight_two_points():
    a = QRect(0, 0, 100, 50)
    b = QRect(200, 0, 100, 50)              # 同列往右
    assert len(_connector_points(a, b)) == 2


def test_connector_wraps_through_gap_for_backward_lower_row():
    a = QRect(600, 0, 100, 50)              # 上列最右
    b = QRect(0, 120, 100, 50)              # 下列最左（往左又往下＝換行）
    pts = _connector_points(a, b)
    assert len(pts) == 6                    # 右連接點→下→沿空隙左→下→左連接點
    gap_y = pts[2].y()
    assert a.bottom() < gap_y < b.top()     # 水平段落在兩列之間的空隙
    assert pts[2].y() == pts[3].y()
    assert pts[0] == QPoint(700, 25) and pts[-1] == QPoint(0, 145)


def test_wrap_connector_horizontal_clears_taller_sibling_in_source_row():
    # 來源列有較高節點（迴圈框，底 214）；末端小節點 a 垂直置中（底 150）在其上方，
    # 下一列 b 在迴圈框下方。繞回橫線 y 須落在迴圈框底以下，否則會被迴圈框蓋住。
    a = QRect(600, 100, 100, 50)            # a.bottom()=150（小節點，高於迴圈框底）
    b = QRect(0, 242, 100, 50)              # b.top()=242（下一列，在迴圈框底 214 之下）
    loop_bottom = 214
    pts = _connector_points(a, b)
    gap_y = pts[2].y()
    assert gap_y >= loop_bottom             # 橫線在迴圈框下方 → 不被蓋住
    assert pts[2].y() == pts[3].y()


def test_connector_starts_and_ends_on_ports_for_different_heights():
    # 實機截圖：迴圈框（高）→ delay（矮），線從邊框中間偏掉、沒接在連接點上。
    loop = QRect(30, 30, 532, 270)
    delay = QRect(589, 72, 126, 76)
    pts = _connector_points(loop, delay)
    assert pts[0] == QPoint(562, 165) and pts[-1] == QPoint(589, 110)
    assert all(p.x() == q.x() or p.y() == q.y() for p, q in zip(pts, pts[1:]))


def test_group_drag_moves_all_selected(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("g")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._nodes[0].move(0, 0)
    dialog._nodes[1].move(100, 0)
    dialog._nodes[2].move(200, 0)
    dialog._on_rubber([0, 1])                       # 框選 0、1
    dialog._on_node_moved_by(0, QPoint(10, 20))     # 拖 0 → 1 應一起移動
    assert (dialog._nodes[1].x(), dialog._nodes[1].y()) == (110, 20)
    assert (dialog._nodes[2].x(), dialog._nodes[2].y()) == (200, 0)   # 未選取的不動


def test_dropping_chip_reorders_by_position(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("D")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    dialog._nodes[2].move(0, 0)         # 把 'c' 拖到最左上 → 應變第一個
    dialog._nodes[0].move(300, 0)
    dialog._nodes[1].move(600, 0)
    dialog._commit_positions()          # 讀 live 位置→依位置重排
    assert [model.action_at(i)["key"] for i in range(3)] == ["c", "a", "b"]


def test_remove_button_click_reaches_model(qapp, tmp_path):
    dialog, model = make_dialog(tmp_path)
    dialog.select_index(0)
    dialog.remove_button.click()
    assert len(model) == 1
    assert dialog.chip_count() == 1
    assert model.rows()[0]["type"] == "delay"


def test_chip_spec_shows_hold_and_kind():
    assert _chip_spec({"type": "key_press", "key": "f1"}) == ("F1", "按一下", "key")
    assert _chip_spec({"type": "key_press", "key": "c", "hold_ms": 200}) == ("C", "按住 200ms", "key")
    assert _chip_spec({"type": "mouse_click", "button": "right"}) == ("Right", "點一下", "click")
    assert _chip_spec({"type": "mouse_click", "button": "left", "count": 3}) == ("Left", "連點 ×3", "click")
    assert _chip_spec({"type": "delay", "ms": 50}) == ("延遲", "50 毫秒", "delay")
    assert _chip_spec({"type": "delay", "ms": 7000}) == ("延遲", "7.0 秒", "delay")
    assert _chip_spec({"type": "loop", "count": 3,
                       "actions": [{"type": "key_press", "key": "a"}]}) == ("迴圈", "×3・1 個動作", "loop")
    assert _chip_spec({"type": "key_combo", "keys": ["ctrl", "s"]}) == (
        "CTRL+S", "組合鍵", "key")
    assert _chip_spec({"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 2000}) == (
        "CTRL+S", "組合鍵，按住 2000ms", "key")


def test_group_and_ungroup_loop():
    model = ScriptEditorModel.new("g")
    for a in [{"type": "key_press", "key": "a"},
              {"type": "delay", "ms": 50},
              {"type": "key_press", "key": "b"}]:
        model.insert(len(model), a)
    idx = model.group_into_loop(0, 1, 3)          # 把前兩個組成迴圈 ×3
    assert idx == 0 and len(model) == 2 and model.is_loop(0)
    assert model.rows()[0]["type"] == "loop"
    model.ungroup_loop(0)                          # 拆回
    assert len(model) == 3 and not model.is_loop(0)
    assert [r["type"] for r in model.rows()] == ["key_press", "delay", "key_press"]


def test_move_to_reorders():
    model = ScriptEditorModel.new("m")
    for k in "abc":
        model.insert(len(model), {"type": "key_press", "key": k})
    model.move_to(0, 3)                            # 把第 0 個移到最後
    assert [model.action_at(i)["key"] for i in range(3)] == ["b", "c", "a"]


def test_save_persists_target_window_and_loop(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("手動腳本")
    model.insert(0, {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage)
    dialog.title_edit.setText(".*記事本.*")
    dialog.loop_check.setChecked(True)
    dialog._on_save()
    assert "已儲存" in dialog.status_label.text()
    saved = storage.load("手動腳本")
    assert saved.target_window.title_pattern == ".*記事本.*"
    assert saved.settings.repeat == -1        # 循環執行直到停止


def test_new_empty_script_rejects_save_without_target(qapp, tmp_path):
    model = ScriptEditorModel.new()
    model.insert(0, {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, ScriptStorage(tmp_path))
    dialog._on_save()   # 未填目標視窗
    assert "儲存失敗" in dialog.status_label.text()


def test_window_picker_fills_fields(qapp, tmp_path):
    from types import SimpleNamespace
    wins = [SimpleNamespace(title="記事本", app_name="notepad.exe")]
    dialog, _ = make_dialog(tmp_path, lister=lambda: wins)
    assert dialog.window_combo.count() == 1
    dialog.window_combo.setCurrentIndex(0)
    dialog._use_selected_window()
    assert dialog.title_edit.text() == "記事本"
    assert dialog.app_edit.text() == "notepad.exe"


def test_window_picker_escapes_regex_specials(qapp, tmp_path):
    # 同 rule_editor：含 regex 特殊字元的視窗標題須 escape 後才能被 re.search 配到。
    import re
    from types import SimpleNamespace
    wins = [SimpleNamespace(title="遊戲視窗(測試)", app_name="game.exe")]
    dialog, _ = make_dialog(tmp_path, lister=lambda: wins)
    dialog.window_combo.setCurrentIndex(0)
    dialog._use_selected_window()
    pattern = dialog.title_edit.text()
    assert re.search(pattern, "遊戲視窗(測試)") is not None


def test_editing_script_and_renaming_replaces_not_duplicates(qapp, tmp_path):
    # 編輯既有腳本、改名後儲存 → 同一條改名，舊名那條（含版面 sidecar）要消失。
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    storage.save_layout("甲", {"positions": [[0, 0]], "zoom": 1.0})
    dialog = ScriptEditorDialog(ScriptEditorModel(storage.load("甲")), storage)
    dialog.name_edit.setText("乙")
    dialog._on_save()
    assert "已儲存" in dialog.status_label.text()
    assert storage.list_names() == ["乙"]          # 只剩「乙」
    assert storage.load_layout("甲") is None        # 舊版面 sidecar 也清掉


def test_editing_script_without_rename_keeps_single(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))
    dialog = ScriptEditorDialog(ScriptEditorModel(storage.load("甲")), storage)
    dialog._on_save()                               # 未改名
    assert storage.list_names() == ["甲"]


def test_script_editor_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog, _ = make_dialog(tmp_path)          # 甲：有目標視窗＋動作 → 有效
    dialog._on_save()
    assert dialog.result() == QDialog.DialogCode.Accepted        # 成功 → 關閉


def test_script_editor_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog, _ = make_dialog(tmp_path)
    dialog.name_edit.setText("")                                 # 空名稱 → 驗證失敗
    dialog._on_save()
    assert dialog.result() != QDialog.DialogCode.Accepted        # 失敗 → 不關
    assert "儲存失敗" in dialog.status_label.text()


def test_input_mode_combo_defaults_to_game_and_saves_scan_pulse(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("遊戲腳本")
    model.insert(len(model), {"type": "key_press", "key": "a"})
    dialog = ScriptEditorDialog(model, storage, platform_name="win32")
    assert dialog.input_mode_combo.currentData() == "game"  # 新腳本預設遊戲模式
    assert [dialog.input_mode_combo.itemData(i) for i in range(4)] == [
        "normal", "game", "window_message", "scan_pulse"]
    dialog.name_edit.setText("遊戲腳本")
    dialog.title_edit.setText("記事本")
    dialog.input_mode_combo.setCurrentIndex(
        dialog.input_mode_combo.findData("scan_pulse"))
    dialog._on_save()
    saved = storage.load("遊戲腳本").settings
    assert saved.game_input_mode is False
    assert saved.window_message_mode is False
    assert saved.scan_pulse_mode is True


def test_editor_has_hotkey_field_reflecting_model(qapp, tmp_path):
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "settings": {"hotkey": "ctrl+f5"},
        "actions": [{"type": "key_press", "key": "a"}]})
    dialog = ScriptEditorDialog(ScriptEditorModel(script), ScriptStorage(tmp_path))
    assert dialog.hotkey_edit.text() == "ctrl+f5"


def test_editor_saves_hotkey(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]})
    dialog = ScriptEditorDialog(ScriptEditorModel(script), storage)
    dialog.hotkey_edit.setText("shift+a+right")
    dialog._on_save()
    assert storage.load("甲").settings.hotkey == "shift+a+right"


def test_add_to_loop_action_appends_and_refreshes(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    dialog = ScriptEditorDialog(model, storage)
    dialog.add_to_loop_action(0, "delay", {"ms": "80"})
    inner = model.action_at(0)["actions"]
    assert len(inner) == 3 and inner[2] == {"type": "delay", "ms": 80}
    assert dialog._nodes[0].inner_count() == 3        # refresh 後畫面反映


def test_inner_add_chip_only_left_click_emits(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    from keyboard_executor.app.script_editor import _InnerAddChip
    chip = _InnerAddChip(1.0)
    fired = []
    chip.clicked.connect(lambda: fired.append(1))
    def press(button):
        chip.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(1, 1), button, button,
            _Qt.KeyboardModifier.NoModifier))
    press(_Qt.MouseButton.RightButton)
    assert fired == []                 # 右鍵不觸發
    press(_Qt.MouseButton.LeftButton)
    assert fired == [1]                # 左鍵觸發


def test_add_to_loop_action_invalid_does_not_orphan_undo(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    for a in [{"type": "key_press", "key": "a"}, {"type": "delay", "ms": 50}]:
        model.insert(len(model), a)
    model.group_into_loop(0, 1, 3)
    dialog = ScriptEditorDialog(model, storage)
    depth = len(dialog._undo_stack)
    with pytest.raises(ScriptValidationError):
        dialog.add_to_loop_action(0, "loop", {"count": "2", "actions": ""})  # 迴圈缺 actions
    assert len(dialog._undo_stack) == depth        # 沒有孤兒快照
    assert len(model.action_at(0)["actions"]) == 2 # 迴圈內容不變


def test_wrap_rows_breaks_by_width():
    assert wrap_rows([100, 100, 100], 250, 10) == [[0, 1], [2]]


def test_wrap_rows_single_row_when_fits():
    assert wrap_rows([50, 50, 50], 500, 10) == [[0, 1, 2]]


def test_wrap_rows_wide_item_self_row():
    assert wrap_rows([300, 100], 250, 10) == [[0], [1]]


def test_wrap_rows_empty():
    assert wrap_rows([], 250, 10) == []


def test_qt_key_to_name_numpad_is_distinct_from_main_row(qapp):
    """手動編輯欄位要與錄製端一致：numpad 7 存 num7，主鍵盤 7 存 7。

    Qt 對兩者回報同一個 Key_7，只有 KeypadModifier 分得出來（錄製端則靠 vk）。
    兩邊不一致的話，手打的動作與錄到的動作會指向不同實體鍵。
    """
    kp = Qt.KeyboardModifier.KeypadModifier
    assert _qt_key_to_name(_kp(Qt.Key.Key_7, mods=kp, text="7")) == "num7"
    assert _qt_key_to_name(_kp(Qt.Key.Key_7, text="7")) == "7"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Plus, mods=kp, text="+")) == "num+"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Slash, mods=kp, text="/")) == "num/"


def test_qt_key_to_name_numlock_off_numpad_stays_navigation(qapp):
    """NumLock 關閉時 numpad 7 就是 Home，Qt 仍帶 KeypadModifier——要回 home 而非 num7。"""
    kp = Qt.KeyboardModifier.KeypadModifier
    assert _qt_key_to_name(_kp(Qt.Key.Key_Home, mods=kp)) == "home"


def test_qt_key_to_name_newly_supported_specials(qapp):
    assert _qt_key_to_name(_kp(Qt.Key.Key_Insert)) == "insert"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Menu)) == "menu"
    assert _qt_key_to_name(_kp(Qt.Key.Key_Pause)) == "pause"


def test_every_captured_name_is_an_authoritative_key_name(qapp):
    """擷取欄位吐出的名稱必須全在權威名單內，否則存檔時載入驗證會擋下來。"""
    from keyboard_executor.core.keynames import is_valid_key
    kp = Qt.KeyboardModifier.KeypadModifier
    samples = [
        _kp(Qt.Key.Key_Insert), _kp(Qt.Key.Key_Menu), _kp(Qt.Key.Key_Pause),
        _kp(Qt.Key.Key_CapsLock), _kp(Qt.Key.Key_NumLock),
        _kp(Qt.Key.Key_ScrollLock), _kp(Qt.Key.Key_Print),
        _kp(Qt.Key.Key_7, mods=kp, text="7"), _kp(Qt.Key.Key_Plus, mods=kp, text="+"),
        _kp(Qt.Key.Key_Asterisk, mods=kp, text="*"),
        _kp(Qt.Key.Key_Period, mods=kp, text="."),
    ]
    for event in samples:
        name = _qt_key_to_name(event)
        assert name is not None
        assert is_valid_key(name), name


class _DotCapture:
    def __init__(self):
        self.rects = []

    def scale_factor(self):
        return 1.0

    def capture(self, rect):
        import cv2
        import numpy as np
        self.rects.append(rect)
        image = np.zeros((rect.height, rect.width, 3), dtype=np.uint8)
        cv2.circle(image, (40, 25), 5, (0, 230, 255), -1)
        return image


def test_minimap_move_fills_target_from_current_dot(qapp):
    capture = _DotCapture()
    form = ActionForm("minimap_move", get_target_window=lambda: "遊戲",
                      get_platform=lambda: _FakePlatform([_FakeWin()]),
                      capture_factory=lambda: capture)
    form._edits["region"].setText("25, 165, 320, 390")
    form._fill_target_from_dot()
    assert form.values()["target"] == "65, 190"
    assert capture.rects[0].x == 100 + 25
    from keyboard_executor.app.action_fields import to_action_dict
    from keyboard_executor.core.models import action_from_dict
    action = action_from_dict(to_action_dict("minimap_move", form.values()))
    assert action.params["target"] == [65, 190] and action.params["method"] == "walk"


def test_minimap_move_without_region_explains(qapp):
    form = _form_with_window("minimap_move")
    form._fill_target_from_dot()
    assert "框選小地圖" in form.pick_status.text()


def test_minimap_move_name_field_round_trips(qapp):
    from keyboard_executor.app.action_fields import to_action_dict
    from keyboard_executor.core.models import action_from_dict, action_label
    form = ActionForm("minimap_move", initial={
        "type": "minimap_move", "name": "第一層", "region": [25, 165, 320, 390],
        "target": [165, 247]})
    assert form.values()["name"] == "第一層"
    form._edits["name"].setText("一樓定點")
    action = action_from_dict(to_action_dict("minimap_move", form.values()))
    assert action_label(action) == "一樓定點：走到小地圖 (165, 247)"


def test_chip_spec_shows_minimap_station_name():
    named = {"type": "minimap_move", "name": "第一層定點", "region": [25, 165, 320, 390],
             "target": [165, 247], "tolerance": 7, "path_key": "x"}
    assert _chip_spec(named) == ("第一層定點", "走到 (165, 247) ±7・沿路 X", "other")
    unnamed = {"type": "minimap_move", "region": [0, 0, 50, 50], "target": [10, 20],
               "method": "down_jump", "tolerance": 2, "name": None}
    assert _chip_spec(unnamed) == ("下跳到小地圖", "下跳到 (10, 20) ±2", "other")


def test_chip_spec_named_key_shows_name_then_key():
    assert _chip_spec({"type": "key_press", "key": "n", "hold_ms": 0, "name": "回城"}) == (
        "回城", "按鍵 N・按一下", "key")
    assert _chip_spec({"type": "delay", "ms": 300, "name": "收招"}) == (
        "收招", "延遲・300 毫秒", "delay")


def test_loop_form_keeps_name(qapp):
    form = LoopActionForm(initial={"name": "主循環", "count": 3,
                                   "actions": [{"type": "delay", "ms": 5}]})
    assert form.name_edit.text() == "主循環"
    from keyboard_executor.app.action_fields import to_action_dict
    from keyboard_executor.core.models import action_from_dict
    action = action_from_dict(to_action_dict("loop", form.values()))
    assert action.params["name"] == "主循環" and action.params["count"] == 3


def test_added_action_goes_after_last_and_does_not_reorder_on_next_drop(qapp, tmp_path):
    # 實機：自由擺位後新增動作，格線位置落在既有動作中間，之後一拖動連線就跑掉。
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("D")
    for k in "abcd":
        model.insert(len(model), {"type": "key_press", "key": k})
    dialog = ScriptEditorDialog(model, storage)
    for node, (x, y) in zip(dialog._nodes, [(400, 14), (600, 14), (14, 200), (250, 200)]):
        node.move(x, y)
    dialog._commit_positions()
    assert [model.action_at(i)["key"] for i in range(4)] == ["a", "b", "c", "d"]
    dialog.add_action("key_press", {"key": "e", "hold_ms": "0"})
    new = dialog._positions[-1]
    assert new.y() >= dialog._positions[3].y()
    dialog._commit_positions()          # 下一次拖放：順序不可改變
    assert [model.action_at(i)["key"] for i in range(5)] == ["a", "b", "c", "d", "e"]


def test_same_row_a_few_pixels_apart_is_one_row_even_across_old_grid_line():
    # 舊規則 y // 70：y=68 和 y=72 被切成兩列，右邊那個反而排到前面。
    assert order_from_positions([(400, 68), (100, 72), (250, 69)], band=70) == [1, 2, 0]
    assert order_from_positions([(400, 68), (100, 72), (50, 160)], band=70) == [1, 0, 2]


def test_taller_loop_box_centered_on_row_keeps_its_row_order(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("D")
    model.insert(0, {"type": "key_press", "key": "a"})
    model.insert(1, {"type": "loop", "count": 2, "actions": [
        {"type": "key_press", "key": "b"}, {"type": "key_press", "key": "c"},
        {"type": "key_press", "key": "d"}]})
    model.insert(2, {"type": "key_press", "key": "e"})
    dialog = ScriptEditorDialog(model, storage)
    dialog.auto_arrange()               # 同列垂直置中：迴圈框左上角比旁邊高
    dialog._commit_positions()
    assert [model.action_at(i)["type"] for i in range(3)] == ["key_press", "loop", "key_press"]
    assert model.action_at(2)["key"] == "e"


def _keys_dialog(tmp_path, keys="abcd"):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("連線")
    for k in keys:
        model.insert(len(model), {"type": "key_press", "key": k})
    return ScriptEditorDialog(model, storage), model, storage


def _order(model):
    return "".join(model.action_at(i)["key"] for i in range(len(model)))


def test_link_drag_from_out_port_onto_another_chip_connects(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    dialog, model, _ = _keys_dialog(tmp_path)
    src, dst = dialog._nodes[1], dialog._nodes[3]
    def event(kind, point, buttons):
        return QMouseEvent(kind, QPointF(point), Qt.MouseButton.LeftButton, buttons,
                           Qt.KeyboardModifier.NoModifier)
    port = src.out_port()
    src.mousePressEvent(event(QEvent.Type.MouseButtonPress, port, Qt.MouseButton.LeftButton))
    over = src.mapFromParent(dst.geometry().center())
    src.mouseMoveEvent(event(QEvent.Type.MouseMove, over, Qt.MouseButton.LeftButton))
    assert dialog.canvas._link is not None
    src.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, over, Qt.MouseButton.NoButton))
    assert dialog.canvas._link is None
    assert _order(model) == "abdc"


def test_reordering_keeps_goto_pointing_at_the_same_action():
    model = ScriptEditorModel.new("G")
    model.insert(0, {"type": "key_press", "key": "a"})
    model.insert(1, {"type": "minimap_goto", "region": [0, 0, 10, 10],
                     "branches": [{"area": [0, 0, 5, 5], "goto_index": 0}],
                     "otherwise": "goto", "otherwise_index": 2})
    model.insert(2, {"type": "key_press", "key": "c"})
    model.move_to(0, 3)                            # a 移到最後：順序 goto, c, a
    goto = model.action_at(0)
    assert goto["branches"][0]["goto_index"] == 2  # 仍指向 a
    assert goto["otherwise_index"] == 1            # 仍指向 c


def _minimap_goto(branches, otherwise_index=1):
    return {"type": "minimap_goto", "region": [25, 165, 320, 390], "branches": branches,
            "otherwise": "goto", "otherwise_index": otherwise_index}


def test_chips_show_index_matching_goto_numbers(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel
    dialog, _, _ = _keys_dialog(tmp_path, "ab")
    badges = [n.findChild(QLabel, "chipIndex").text() for n in dialog._nodes]
    assert badges == ["#0", "#1"]


def test_branches_are_edited_as_rows_with_action_dropdown(qapp):
    from keyboard_executor.app.action_fields import to_action_dict
    from keyboard_executor.app.script_editor import ActionForm
    initial = _minimap_goto([{"area": [138, 244, 62, 7], "goto_index": 2}])
    initial.pop("type")
    form = ActionForm("minimap_goto", initial=initial,
                      goto_choices=["第一層", "第二層", "傳點"])
    branches = form._edits["branches"]
    assert branches._rows[0][1].text() == "138, 244, 62, 7"
    assert branches._rows[0][2].currentText().startswith("#2")
    branches.add_row([90, 520, 192, 7], 0)
    form._edits["otherwise_index"].setCurrentIndex(form._edits["otherwise_index"].findData("1"))
    action = to_action_dict("minimap_goto", form.values())
    assert action["branches"] == [{"area": [138, 244, 62, 7], "goto_index": 2},
                                  {"area": [90, 520, 192, 7], "goto_index": 0}]
    assert action["otherwise_index"] == 1
    action_from_dict = __import__("keyboard_executor.core.models", fromlist=["x"]).action_from_dict
    action_from_dict(action)


def test_goto_index_is_a_dropdown_of_same_level_actions(qapp):
    from keyboard_executor.app.script_editor import ActionForm
    form = ActionForm("wait_image", initial={"template": "t", "on_timeout": "goto", "goto_index": 1},
                      goto_choices=["回城", "第一層定點"])
    box = form._edits["goto_index"]
    assert box.currentText() == "#1　第一層定點"
    assert form.values()["goto_index"] == "1"


def test_loop_inner_forms_use_inner_action_numbers(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    model = ScriptEditorModel.new("L")
    model.insert(0, {"type": "key_press", "key": "z"})
    model.insert(1, {"type": "loop", "count": 2, "actions": [
        {"type": "key_press", "key": "a", "name": "內層甲"}, {"type": "delay", "ms": 5}]})
    dialog = ScriptEditorDialog(model, storage)
    assert dialog._loop_choices(1)[0].startswith("內層甲")
    assert len(dialog._top_choices()) == 2


def test_every_pick_brings_target_window_to_front_first(qapp):
    platform = _FakePlatform([_FakeWin()])
    form = ActionForm("minimap_goto", get_target_window=lambda: "遊戲",
                      get_platform=lambda: platform, capture_factory=lambda: None,
                      goto_choices=["甲"])
    opened = []
    import keyboard_executor.app.region_picker as rp
    original = rp.RegionPickerOverlay
    class _Overlay:
        def __init__(self, *a, **k):
            self.region_selected = type("S", (), {"connect": lambda *_: None})()
        def open_fullscreen(self):
            opened.append(list(platform.window_manager.activated))
    rp.RegionPickerOverlay = _Overlay
    try:
        from PySide6.QtWidgets import QPushButton
        form._edits["branches"]._rows[0][0].findChildren(QPushButton)[0].click()   # 區域「框選」
        form._pick_region("region")
    finally:
        rp.RegionPickerOverlay = original
    assert len(opened) == 2 and all(opened)      # 每次開框選前都已切到前景


def test_pick_stops_when_target_window_cannot_come_to_front(qapp):
    platform = _FakePlatform([_FakeWin()])
    platform.window_manager.can_activate = False
    form = ActionForm("mouse_click", get_target_window=lambda: "遊戲",
                      get_platform=lambda: platform, capture_factory=lambda: None)
    form._pick_xy()
    assert "最上層" in form.pick_status.text()
    assert form._overlay is None


def _spread(dialog, xs):
    for node, x in zip(dialog._nodes, xs):
        node.move(x, 14)


def test_manual_link_keeps_only_that_pair_fixed_rest_follow_position(qapp, tmp_path):
    dialog, model, _ = _keys_dialog(tmp_path)
    dialog.connect_actions(0, 3)                  # a → d（手動）
    assert _order(model) == "adbc" and dialog._links == {0}
    _spread(dialog, (600, 30, 400, 200))          # a 放最右；d 放最左（d 跟著 a）
    dialog._commit_positions()
    assert _order(model) == "cbad"                # b、c 依位置；a→d 仍相連
    assert dialog._links == {2}


def test_cancel_one_link_returns_that_pair_to_position_order(qapp, tmp_path):
    dialog, model, _ = _keys_dialog(tmp_path)
    dialog.connect_actions(0, 3)
    _spread(dialog, (600, 30, 400, 200))
    dialog.cancel_link(0)
    assert dialog._links == set()
    assert _order(model) == "dcba"                # 全部回到依位置（d 在最左）
    assert "取消" in dialog.status_label.text()


def test_cancel_all_links_and_undo_restores_link(qapp, tmp_path):
    dialog, model, _ = _keys_dialog(tmp_path)
    dialog.connect_actions(0, 3)
    dialog.connect_actions(1, 2)                  # a→d→b
    assert _order(model) == "adbc" and dialog._links == {0, 1}
    dialog.cancel_all_links()
    assert dialog._links == set()
    dialog._undo()
    assert dialog._links == {0, 1}


def test_manual_links_persist_across_reopen(qapp, tmp_path):
    dialog, model, storage = _keys_dialog(tmp_path)
    dialog.title_edit.setText(".*記事本.*")
    dialog.connect_actions(0, 2)
    dialog._on_save()
    reopened = ScriptEditorDialog(ScriptEditorModel(storage.load("連線")), storage)
    assert reopened._links == {0}
    assert reopened.canvas.manual_links == {0}


def test_deleting_linked_action_drops_its_link(qapp, tmp_path):
    dialog, model, _ = _keys_dialog(tmp_path)
    dialog.connect_actions(1, 2)
    dialog.select_index(2)
    dialog._on_remove()
    assert dialog._links == set()



def test_goto_action_form_is_dropdown_and_chip_shows_target(qapp, tmp_path):
    from keyboard_executor.app.action_fields import to_action_dict
    from keyboard_executor.app.script_editor import ActionForm, _chip_spec
    form = ActionForm("goto", initial={"goto_index": 1}, goto_choices=["判斷樓層", "第一層"])
    assert form._edits["goto_index"].currentText() == "#1　第一層"
    assert to_action_dict("goto", form.values()) == {"type": "goto", "name": "", "goto_index": 1} \
        or to_action_dict("goto", form.values())["goto_index"] == 1
    main, sub, _ = _chip_spec({"type": "goto", "goto_index": 0, "name": "回到判斷樓層"})
    assert main == "回到判斷樓層" and "#0" in sub


def test_moving_actions_keeps_plain_goto_target():
    model = ScriptEditorModel.new("G")
    for d in ({"type": "delay", "ms": 1}, {"type": "goto", "goto_index": 0},
              {"type": "delay", "ms": 2}):
        model.insert(len(model), d)
    model.move_to(0, 3)                            # 順序：goto, delay2, delay1
    assert model.action_at(0)["goto_index"] == 2


def test_ports_sit_on_node_borders_half_outside(qapp, tmp_path):
    dialog, _, _ = _keys_dialog(tmp_path, "ab")
    node = dialog._nodes[0]
    geo = node.geometry()
    assert node.mapToParent(node.in_port()) == QPoint(geo.left(), geo.center().y())
    assert node.mapToParent(node.out_port()).x() == geo.left() + geo.width()


def test_drag_from_outer_half_of_port_on_canvas_connects(qapp, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    dialog, model, _ = _keys_dialog(tmp_path, "abcd")
    src, dst = dialog._nodes[0], dialog._nodes[2]
    outer = src.mapToParent(src.out_port()) + QPoint(3, 0)     # 圓點在節點外的那一半
    def ev(kind, p, buttons):
        return QMouseEvent(kind, QPointF(p), Qt.MouseButton.LeftButton, buttons,
                           Qt.KeyboardModifier.NoModifier)
    dialog.canvas.mousePressEvent(ev(QEvent.Type.MouseButtonPress, outer, Qt.MouseButton.LeftButton))
    over = dst.geometry().center()
    dialog.canvas.mouseMoveEvent(ev(QEvent.Type.MouseMove, over, Qt.MouseButton.LeftButton))
    assert dialog.canvas._link is not None
    dialog.canvas.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, over, Qt.MouseButton.NoButton))
    assert _order(model) == "acbd"


# --- 繞一圈學路線 ---

def _learned_loop():
    from keyboard_executor.core.models import action_from_dict
    return [action_from_dict({"type": "loop", "count": 5, "actions": [
        {"type": "minimap_move", "region": [20, 160, 300, 260], "target": [100, 200]}]})]


def test_learn_route_passes_script_settings_and_appends(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from keyboard_executor.core.models import TimedKey
    script = script_from_dict({
        "name": "甲", "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"},
                    {"type": "loop", "count": 2, "actions": [
                        {"type": "minimap_goto", "region": [25, 165, 320, 270],
                         "branches": [{"area": [0, 0, 5, 5], "goto_index": 0}]}]}]})
    model = ScriptEditorModel(script)
    dialog = ScriptEditorDialog(model, ScriptStorage(tmp_path))
    seen = {}

    class FakePanel:
        def __init__(self, **kw):
            seen.update(kw)
            self.learned_actions = _learned_loop()
            self.learned_timed = (TimedKey("1", 120.0),)

        def exec(self):
            return QDialog.DialogCode.Accepted

    dialog.route_panel_factory = FakePanel
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)    # 未選＝加在最後面
    dialog._on_learn_route()
    assert seen["route_only"] and seen["preset_region"] == [25, 165, 320, 270]
    assert seen["preset_title"] == "記事本"
    assert len(model) == 3 and model.action_at(2)["type"] == "loop"
    assert dialog.timed_keys_edit.text() == "1:120"
    assert "加入學到的路線" in dialog.status_label.text()


def test_apply_learned_route_can_replace_and_undo(qapp, tmp_path):
    from keyboard_executor.core.models import action_to_dict
    dialog, model = make_dialog(tmp_path)
    dialog.apply_learned_route([action_to_dict(a) for a in _learned_loop()], replace=True)
    assert len(model) == 1 and model.action_at(0)["type"] == "loop"
    dialog._undo()
    assert len(model) == 2


def test_recorder_panel_route_only_returns_actions_instead_of_saving(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    from keyboard_executor.app.recorder_panel import RecorderPanel
    from keyboard_executor.core.models import TimedKey
    from keyboard_executor.platforms.base import WindowInfo
    from tests.fakes import FakeInputHook, FakeWindowManager
    wins = [WindowInfo(handle=object(), title="其他", app_name="x", x=0, y=0, width=1,
                       height=1, is_active=False),
            WindowInfo(handle=object(), title="MapleStory Worlds-楓星", app_name="msw.exe",
                       x=0, y=0, width=1, height=1, is_active=True)]
    panel = RecorderPanel(FakeWindowManager(wins), None, hook_factory=FakeInputHook,
                          route_only=True, preset_region=[1, 2, 30, 40],
                          preset_timed="1:120", preset_title=r"MapleStory\ Worlds")
    assert panel.window_combo.currentIndex() == 1
    assert panel.region_edit.text() == "1, 2, 30, 40" and panel.timed_edit.text() == "1:120"
    assert panel.route_check.isChecked() and panel.save_button.text() == "套用到腳本"
    panel._actions, panel._timed = _learned_loop(), (TimedKey("1", 120.0),)
    panel._on_save_clicked()
    assert panel.result() == QDialog.DialogCode.Accepted
    assert panel.learned_actions and panel.learned_timed[0].key == "1"
