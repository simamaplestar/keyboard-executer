from keyboard_executor.app.rule_editor import RuleEditorDialog
from keyboard_executor.app.rule_editor_model import RuleEditorModel
from keyboard_executor.storage.rules import RuleStorage
from keyboard_executor.storage.templates import TemplateStore


def test_dialog_constructs_prefilled_from_model(qapp, tmp_path):
    model = RuleEditorModel()
    model.name = "監看甲"
    model.title_pattern = "遊戲"
    model.pattern = "連線中斷"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path))
    assert dialog.name_edit.text() == "監看甲"
    assert dialog.pattern_edit.text() == "連線中斷"


def test_rule_editor_is_scrollable_on_small_screens(qapp, tmp_path):
    from PySide6.QtWidgets import QScrollArea

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    assert isinstance(dialog._scroll, QScrollArea)
    assert dialog._scroll.widgetResizable()
    assert dialog.minimumHeight() <= 320
    dialog.resize(420, 320)
    dialog.show()
    qapp.processEvents()
    assert dialog._scroll.verticalScrollBar().maximum() > 0
    dialog.close()


def test_save_button_persists_rule_via_storage(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    model = RuleEditorModel()
    dialog = RuleEditorDialog(model, storage)
    dialog.name_edit.setText("存我")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("斷線了")
    dialog.save_button.click()
    assert "已儲存" in dialog.status_label.text()
    rule = storage.load("存我")
    assert rule.condition.pattern == "連線中斷"
    assert rule.trigger.message == "斷線了"


def test_rule_window_picker_fills_fields(qapp, tmp_path):
    from types import SimpleNamespace
    wins = [SimpleNamespace(title="記事本", app_name="notepad.exe")]
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              window_lister=lambda: wins)
    assert dialog.window_combo.count() == 1
    dialog.window_combo.setCurrentIndex(0)
    dialog._use_selected_window()
    assert dialog.title_edit.text() == "記事本"
    assert dialog.app_edit.text() == "notepad.exe"


def test_rule_script_name_is_dropdown_of_scripts(qapp, tmp_path):
    from PySide6.QtWidgets import QComboBox
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              script_names=lambda: ["甲", "乙"])
    assert isinstance(dialog.script_edit, QComboBox)
    items = [dialog.script_edit.itemText(i) for i in range(dialog.script_edit.count())]
    assert "甲" in items and "乙" in items


def test_rule_save_with_selected_script_name(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage, script_names=lambda: ["甲"])
    dialog.name_edit.setText("r")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")     # text 條件需非空 pattern
    dialog.notify_check.setChecked(False)
    dialog.run_script_check.setChecked(True)
    dialog.script_edit.setCurrentIndex(dialog.script_edit.findText("甲"))
    dialog.save_button.click()
    assert "已儲存" in dialog.status_label.text()
    assert storage.load("r").trigger.script_name == "甲"


def test_rule_loads_existing_script_name_even_if_not_listed(qapp, tmp_path):
    model = RuleEditorModel()
    model.script_name = "舊腳本"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path), script_names=lambda: ["甲"])
    assert dialog.script_edit.currentText() == "舊腳本"   # 既有值不遺失


def test_pick_region_overlay_parented_to_dialog(qapp, tmp_path):
    # 規則編輯器是 modal（.exec()）；框選覆蓋層若無 parent 會被 modal 擋住輸入，
    # 導致「有遮罩但不能框選、卡在全螢幕」。覆蓋層必須以對話框為 parent。
    from types import SimpleNamespace

    activated = []

    class FakeWM:
        def find_windows(self, title_pattern=None, app_name=None):
            return [SimpleNamespace(x=0, y=0)]

        def activate(self, window):
            activated.append(window)
            return True

    class FakePlatform:
        window_manager = FakeWM()

    class FakeCapture:
        def capture(self, rect):
            import numpy as np
            return np.zeros((rect.height, rect.width, 3), dtype=np.uint8)

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              get_platform=lambda **k: FakePlatform(),
                              capture_factory=FakeCapture)
    dialog.title_edit.setText("記事本")
    dialog._on_pick_region()
    assert activated, "開框選層前應先把指定視窗切到最上層"
    assert dialog._overlay is not None
    assert dialog._overlay.parent() is dialog
    dialog._overlay.close()


def test_pick_region_uses_injected_get_platform(qapp, tmp_path):
    class FakeWM:
        def find_windows(self, title_pattern=None, app_name=None):
            return []

    class FakePlatform:
        window_manager = FakeWM()

    calls = []

    def fake_get_platform(**kwargs):
        calls.append(kwargs)
        return FakePlatform()

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              get_platform=fake_get_platform)
    dialog.title_edit.setText("記事本")
    dialog._on_pick_region()
    assert calls, "應使用注入的 get_platform，而非真實平台（M4 待辦 #8）"
    assert "找不到符合" in dialog.status_label.text()


def test_pick_region_does_not_open_overlay_when_activation_fails(qapp, tmp_path):
    from types import SimpleNamespace

    class FakeWM:
        def find_windows(self, title_pattern=None, app_name=None):
            return [SimpleNamespace(x=0, y=0)]

        def activate(self, window):
            return False

    class FakePlatform:
        window_manager = FakeWM()

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              get_platform=lambda **k: FakePlatform())
    dialog.title_edit.setText("記事本")
    dialog._on_pick_region()
    assert dialog._overlay is None
    assert "切到最上層" in dialog.status_label.text()


def test_capture_template_activates_configured_target_first(qapp, tmp_path):
    from types import SimpleNamespace

    calls = []

    class FakeWM:
        def find_windows(self, title_pattern=None, app_name=None):
            calls.append(("find", title_pattern, app_name))
            return [SimpleNamespace(x=0, y=0)]

        def activate(self, window):
            calls.append(("activate", window))
            return True

    class FakePlatform:
        window_manager = FakeWM()

    class FakeCapture:
        def capture(self, rect):
            import numpy as np
            return np.zeros((rect.height, rect.width, 3), dtype=np.uint8)

    dialog = RuleEditorDialog(
        RuleEditorModel(), RuleStorage(tmp_path), template_store=TemplateStore(tmp_path),
        get_platform=lambda **k: FakePlatform(), capture_factory=FakeCapture)
    dialog.title_edit.setText("記事本")
    dialog.app_edit.setText("notepad.exe")
    dialog._on_capture_template()
    assert calls[0] == ("find", "記事本", "notepad.exe")
    assert calls[1][0] == "activate"
    assert dialog._overlay is not None
    dialog._overlay.close()


def test_capture_template_uses_injected_capture_factory(qapp, tmp_path):
    import numpy as np

    captures = []

    class FakeCapture:
        def scale_factor(self):
            return 1.0

        def capture(self, rect):
            captures.append(rect)
            image = np.empty((rect.height, rect.width, 3), dtype=np.uint8)
            image[:] = (9, 17, 25)
            return image

    store = TemplateStore(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              template_store=store, capture_factory=FakeCapture)
    dialog._ask_template_name = lambda: "鈕"     # thin seam：跳過 QInputDialog
    dialog._on_capture_template()
    dialog._overlay._begin(10, 10)
    dialog._overlay._finish(30, 40)              # normalize → Rect(10, 10, 20, 30)
    assert store.list_names() == ["鈕"]
    saved = store.load_template("鈕")
    assert len(captures) == 1, "應裁切遮罩顯示前的快照，不可在選完後重新截圖"
    assert np.all(saved == (9, 17, 25))
    assert dialog.template_edit.text() == "鈕"
    assert "已儲存模板" in dialog.status_label.text()


def test_condition_combo_includes_color(qapp, tmp_path):
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    labels = [dialog.condition_combo.itemText(i)
              for i in range(dialog.condition_combo.count())]
    assert "顏色" in labels


def test_color_pick_updates_swatch_and_state(qapp, tmp_path):
    import numpy as np

    class FakeCap:
        def capture(self, rect):
            img = np.full((10, 10, 3), 128, dtype=np.uint8)
            img[5, 5] = (0, 0, 255)              # BGR 紅
            return img

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              capture_factory=lambda: FakeCap())
    dialog._on_pick_color()
    dialog._overlay._pick(5, 5)
    assert dialog._picked_hsv[0] == 0 and dialog._picked_hsv[1] == 255
    assert "H=0" in dialog.color_value_label.text()


def test_color_condition_saves_via_storage(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage,
                              capture_factory=lambda: None)
    dialog.name_edit.setText("紅點")
    dialog.title_edit.setText("遊戲")
    dialog.condition_combo.setCurrentIndex(
        dialog.condition_combo.findData("color"))
    dialog._on_color_picked(0, 255, 255)         # 經滴管取色（標記已取樣）
    dialog.min_pixels_edit.setText("3")
    dialog.detect_combo.setCurrentIndex(dialog.detect_combo.findData(False))
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("有紅點")
    dialog.save_button.click()
    assert "已儲存" in dialog.status_label.text()
    rule = storage.load("紅點")
    assert rule.condition.type == "color"
    assert rule.condition.hue == 0 and rule.condition.min_pixels == 3


def test_color_rule_requires_sampling_before_save(qapp, tmp_path):
    # 選了「顏色」卻沒用滴管取色就存 → 擋下並提示，不寫入（避免預設 (0,0,0) 廣泛誤命中）
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage, capture_factory=lambda: None)
    dialog.name_edit.setText("紅點")
    dialog.title_edit.setText("遊戲")
    dialog.condition_combo.setCurrentIndex(dialog.condition_combo.findData("color"))
    dialog.save_button.click()
    assert "請先用滴管取色" in dialog.status_label.text()
    assert storage.list_names() == []


def test_rule_window_picker_escapes_regex_specials(qapp, tmp_path):
    # 視窗標題含 regex 特殊字元（括號）時，「用此視窗」須填 escape 後的 pattern；
    # 否則 re.search 把 () 當群組，永遠配不到自己的視窗。
    # 回歸：MapleStory Worlds-楓星(聯盟) 框選時「找不到符合…的視窗」。
    import re
    from types import SimpleNamespace
    wins = [SimpleNamespace(title="MapleStory Worlds-楓星(聯盟)", app_name="msw.exe")]
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              window_lister=lambda: wins)
    dialog.window_combo.setCurrentIndex(0)
    dialog._use_selected_window()
    pattern = dialog.title_edit.text()
    assert re.search(pattern, "MapleStory Worlds-楓星(聯盟)") is not None


def test_condition_inputs_toggle_with_condition_type(qapp, tmp_path):
    # 選條件類型時，只顯示該類型的輸入欄位（文字/圖像/顏色互斥），其餘隱藏。
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))

    def sel(ctype):
        dialog.condition_combo.setCurrentIndex(dialog.condition_combo.findData(ctype))

    sel("text")
    assert not dialog.pattern_edit.isHidden() and not dialog.mode_combo.isHidden()
    assert dialog.template_edit.isHidden() and dialog.threshold_edit.isHidden()
    assert dialog.capture_template_button.isHidden()
    assert dialog._color_container.isHidden() and dialog.hue_tol_edit.isHidden()
    assert dialog.min_pixels_edit.isHidden()
    assert not dialog.detect_combo.isHidden()   # 偵測（出現時/消失時）三種條件都顯示

    sel("image")
    assert dialog.pattern_edit.isHidden() and dialog.mode_combo.isHidden()
    assert not dialog.template_edit.isHidden() and not dialog.threshold_edit.isHidden()
    assert not dialog.capture_template_button.isHidden()
    assert dialog._color_container.isHidden()
    assert not dialog.detect_combo.isHidden()

    sel("color")
    assert dialog.pattern_edit.isHidden() and dialog.template_edit.isHidden()
    assert dialog.capture_template_button.isHidden()
    assert not dialog._color_container.isHidden() and not dialog.hue_tol_edit.isHidden()
    assert not dialog.min_pixels_edit.isHidden() and not dialog.detect_combo.isHidden()


def test_new_rule_defaults_to_text_inputs_only(qapp, tmp_path):
    # 新規則預設條件類型為文字 → 只顯示文字欄位。
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    assert not dialog.pattern_edit.isHidden()
    assert dialog.template_edit.isHidden() and dialog._color_container.isHidden()


def test_editing_rule_and_renaming_replaces_not_duplicates(qapp, tmp_path):
    # 編輯既有規則、改名後儲存 → 應為「同一條改名」，舊名那條要消失（不是多一條）。
    from keyboard_executor.core.models import rule_from_dict
    storage = RuleStorage(tmp_path)
    storage.save(rule_from_dict({
        "name": "甲", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "notify", "message": "y"}}))
    dialog = RuleEditorDialog(RuleEditorModel.from_rule(storage.load("甲")), storage)
    dialog.name_edit.setText("乙")
    dialog.save_button.click()
    assert "已儲存" in dialog.status_label.text()
    assert storage.list_names() == ["乙"]              # 只剩「乙」，「甲」不見


def test_editing_rule_without_rename_keeps_single(qapp, tmp_path):
    from keyboard_executor.core.models import rule_from_dict
    storage = RuleStorage(tmp_path)
    storage.save(rule_from_dict({
        "name": "甲", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "notify", "message": "y"}}))
    dialog = RuleEditorDialog(RuleEditorModel.from_rule(storage.load("甲")), storage)
    dialog.message_edit.setText("z")                   # 只改內容、不改名
    dialog.save_button.click()
    assert storage.list_names() == ["甲"]              # 仍只有「甲」


def test_new_rule_save_does_not_delete_existing(qapp, tmp_path):
    from keyboard_executor.core.models import rule_from_dict
    storage = RuleStorage(tmp_path)
    storage.save(rule_from_dict({
        "name": "甲", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "trigger": {"type": "notify", "message": "y"}}))
    dialog = RuleEditorDialog(RuleEditorModel(), storage)   # 新規則（無 original_name）
    dialog.name_edit.setText("乙")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("y")
    dialog.save_button.click()
    assert set(storage.list_names()) == {"甲", "乙"}       # 新增不刪既有


def test_rule_editor_closes_on_successful_save(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("r")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("y")
    dialog.save_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted        # 成功 → 關閉
    assert storage.load("r").condition.pattern == "連線中斷"      # 確實有存


def test_rule_editor_stays_open_on_validation_failure(qapp, tmp_path):
    from PySide6.QtWidgets import QDialog
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    dialog.name_edit.setText("")                                 # 空名稱 → 驗證失敗
    dialog.save_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted        # 失敗 → 不關
    assert "儲存失敗" in dialog.status_label.text()


def test_rule_editor_saves_multiple_trigger_actions(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("多")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("有事")
    dialog.stop_all_check.setChecked(True)
    dialog.save_button.click()
    rule = storage.load("多")
    assert [t.type for t in rule.triggers] == ["notify", "stop_all"]


def test_rule_editor_loads_existing_multi_trigger_checked(qapp, tmp_path):
    from keyboard_executor.core.models import rule_from_dict
    storage = RuleStorage(tmp_path)
    storage.save(rule_from_dict({
        "name": "多", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "連線中斷"},
        "triggers": [{"type": "notify", "message": "m"}, {"type": "stop_all"}]}))
    dialog = RuleEditorDialog(RuleEditorModel.from_rule(storage.load("多")), storage)
    assert dialog.notify_check.isChecked() and dialog.stop_all_check.isChecked()
    assert not dialog.run_script_check.isChecked()


def test_attach_screenshot_checkbox_saves(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), storage)
    dialog.name_edit.setText("附圖規則")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("斷線了")
    dialog.attach_screenshot_check.setChecked(True)
    dialog.save_button.click()
    assert storage.load("附圖規則").attach_screenshot is True


def test_attach_screenshot_checkbox_reflects_loaded_rule(qapp, tmp_path):
    model = RuleEditorModel()
    model.attach_screenshot = True
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path))
    assert dialog.attach_screenshot_check.isChecked() is True


def test_detect_combo_visible_for_text_condition(qapp, tmp_path):
    model = RuleEditorModel()
    model.condition_type = "text"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path))
    assert dialog.detect_combo.isVisibleTo(dialog)   # 文字條件也顯示「偵測」


def test_detect_combo_saves_absent_for_text_rule(qapp, tmp_path):
    storage = RuleStorage(tmp_path)
    model = RuleEditorModel()
    model.condition_type = "text"
    dialog = RuleEditorDialog(model, storage)
    dialog.name_edit.setText("文字消失規則")
    dialog.title_edit.setText("遊戲")
    dialog.pattern_edit.setText("連線中斷")
    dialog.notify_check.setChecked(True)
    dialog.message_edit.setText("沒斷線")
    di = dialog.detect_combo.findData(True)          # 選「消失時」
    dialog.detect_combo.setCurrentIndex(di)
    dialog.save_button.click()
    assert storage.load("文字消失規則").condition.absent is True


# --- 圖像模板預覽 ---

def _store_with(tmp_path, **images):
    import numpy as np
    store = TemplateStore(tmp_path)
    for name, image in images.items():
        store.save_template(name, np.full((*image, 3), 128, dtype=np.uint8))
    return store


def test_template_preview_shows_the_named_image(qapp, tmp_path):
    store = _store_with(tmp_path, 加倍圖示=(20, 30))
    model = RuleEditorModel()
    model.condition_type = "image"
    model.template = "加倍圖示"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path), template_store=store)
    assert not dialog.template_preview.pixmap().isNull()
    assert dialog.template_preview.name == "加倍圖示"


def test_template_preview_follows_typing(qapp, tmp_path):
    store = _store_with(tmp_path, 甲=(10, 10), 乙=(10, 10))
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              template_store=store)
    dialog.template_edit.setText("甲")
    assert dialog.template_preview.name == "甲"
    dialog.template_edit.setText("乙")
    assert dialog.template_preview.name == "乙"


def test_template_preview_names_a_typo(qapp, tmp_path):
    """打錯一個字當場看得到，不必等監看跑起來才發現靜默比對不到。"""
    store = _store_with(tmp_path, 測謊文字=(10, 10))
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              template_store=store)
    dialog.template_edit.setText("測謊文子")
    assert dialog.template_preview.pixmap().isNull()
    assert "找不到模板" in dialog.template_preview.text()


def test_template_preview_updates_after_capturing(qapp, tmp_path):
    """框選擷取完會 setText，預覽要跟著出現。"""
    import numpy as np

    class FakeCapture:
        def scale_factor(self):
            return 1.0

        def capture(self, rect):
            return np.zeros((rect.height, rect.width, 3), dtype=np.uint8)

    store = TemplateStore(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              template_store=store, capture_factory=FakeCapture)
    dialog._ask_template_name = lambda: "新鈕"
    dialog._on_capture_template()
    dialog._overlay._begin(10, 10)
    dialog._overlay._finish(30, 40)
    assert dialog.template_preview.name == "新鈕"
    assert not dialog.template_preview.pixmap().isNull()


def test_template_preview_only_visible_for_image_condition(qapp, tmp_path):
    store = _store_with(tmp_path, 圖=(10, 10))
    model = RuleEditorModel()
    model.condition_type = "text"
    dialog = RuleEditorDialog(model, RuleStorage(tmp_path), template_store=store)
    assert not dialog.template_preview.isVisibleTo(dialog)
    dialog.condition_combo.setCurrentIndex(
        dialog.condition_combo.findData("image"))
    assert dialog.template_preview.isVisibleTo(dialog)


def test_dialog_still_works_without_template_store(qapp, tmp_path):
    """精簡建構（無 template_store）不得因為預覽而爆掉。"""
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path))
    assert dialog.template_preview is None
    dialog.condition_combo.setCurrentIndex(
        dialog.condition_combo.findData("image"))     # 切到 image 也不能出錯
