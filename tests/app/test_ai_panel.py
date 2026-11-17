"""AiPanel 聊天流：未設定引導、送出/串流/停止/清除、隱私 ack。"""
import threading

import pytest

from keyboard_executor.app.settings import Settings
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.provider import (
    AiAborted,
    AiProviderError,
    ChatProvider,
    ChatResult,
)
from keyboard_executor.storage.scripts import ScriptStorage
from keyboard_executor.storage.rules import RuleStorage


class SyncWorker(Worker):
    """start() 直接同步 run()（Worker.run 支援同步呼叫）。"""
    def start(self):
        self.run()


class ManualWorker(Worker):
    """start() 不自動執行 run()：測試手動控制時機，模擬「清除對話／再次送出」
    與背景執行緒 finished/failed 送達之間的競態（I-2、M-9）。"""
    def start(self):
        pass


class FakeProvider(ChatProvider):
    def __init__(self, result=None, deltas=(), error=None):
        self.result = result or ChatResult(text="回答")
        self.deltas = deltas
        self.error = error
        self.calls = []

    def stream_chat(self, messages, *, system, tools, on_delta, should_abort):
        self.calls.append({"messages": list(messages), "system": system,
                           "tools": tools})
        for d in self.deltas:
            on_delta(d)
        if self.error:
            raise self.error
        return self.result


AI_ON = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=True)


def _panel(tmp_path, provider, settings=AI_ON, acks=None, confirm=True):
    from keyboard_executor.app.ai_panel import AiPanel

    acks = acks if acks is not None else []
    return AiPanel(get_settings=lambda: settings,
                   ack_privacy=lambda: acks.append(True),
                   storage=ScriptStorage(tmp_path),
                   rule_storage=RuleStorage(tmp_path),
                   get_selected_script=lambda: None,
                   worker_factory=SyncWorker,
                   provider_factory=lambda *a: provider,
                   confirm_privacy=lambda: confirm)


def _bubble_texts(panel):
    lay = panel.bubbles_layout
    out = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None and w.objectName().startswith("aiBubble"):
            out.append((w.objectName(), w.text()))
    return out


def test_unconfigured_shows_setup_page(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider(), settings=Settings())
    assert panel.setup_button.isVisible() or not panel.input_edit.isEnabled()


def test_send_adds_user_and_assistant_bubbles(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(text="你好！"), deltas=["你好", "！"])
    panel = _panel(tmp_path, provider)
    panel.send_message("怎麼錄製腳本？")
    texts = _bubble_texts(panel)
    assert ("aiBubbleUser", "怎麼錄製腳本？") in texts
    assert ("aiBubbleAssistant", "你好！") in texts
    # 對話歷史累積（下一輪帶上下文）
    assert panel._messages == [{"role": "user", "content": "怎麼錄製腳本？"},
                               {"role": "assistant", "content": "你好！"}]


def test_upload_image_then_send_passes_attachment_and_clears_tray(qapp, tmp_path):
    from PySide6.QtGui import QImage

    source = tmp_path / "畫面.png"
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(0xFF225588)
    assert image.save(str(source), "PNG")
    provider = FakeProvider(result=ChatResult(text="看到了"))
    panel = _panel(tmp_path, provider)
    panel.add_image_paths([str(source)])
    assert len(panel._pending_images) == 1
    panel.input_edit.setText("看到按鈕後幫我建立規則和腳本")
    panel._on_send()
    sent = provider.calls[0]["messages"][0]
    assert sent["content"].startswith("看到按鈕")
    assert sent["images"][0]["name"] == "畫面.png"
    assert panel._pending_images == [] and not panel._attachment_frame.isVisible()


def test_cleared_attachment_does_not_retain_panel_until_deferred_child_deletion(qapp, tmp_path):
    """A child callback retaining its parent can re-enter destruction on DeferredDelete."""
    import weakref
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QImage

    source = tmp_path / "畫面.png"
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0xFF225588)
    assert image.save(str(source), "PNG")
    panel = _panel(tmp_path, FakeProvider())
    panel.add_image_paths([str(source)])
    panel._on_send()
    ref = weakref.ref(panel)
    del panel
    try:
        assert ref() is None, "已清空的附件不應透過回呼保留整個面板"
    finally:
        # Keep a failing implementation alive while draining, so the regression
        # reports an assertion instead of aborting the entire Windows process.
        guard = ref()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if guard is not None:
            guard.shutdown()


def test_remove_attachment_button_keeps_the_other_image(qapp, tmp_path):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QPushButton

    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0xFF225588)
    paths = [tmp_path / "第一張.png", tmp_path / "第二張.png"]
    for path in paths:
        assert image.save(str(path), "PNG")
    panel = _panel(tmp_path, FakeProvider())
    panel.add_image_paths([str(path) for path in paths])
    second = panel._attachment_layout.itemAt(1).widget()
    second.findChild(QPushButton).click()
    assert [a["name"] for a in panel._pending_images] == ["第一張.png"]
    panel._attachment_layout.itemAt(0).widget().findChild(QPushButton).click()
    assert panel._pending_images == []


def test_system_prompt_and_anthropic_tools_passed(qapp, tmp_path):
    provider = FakeProvider()
    panel = _panel(tmp_path, provider)
    panel.send_message("hi")
    call = provider.calls[0]
    assert "行為界線" in call["system"]
    assert call["tools"][0].get("input_schema") is not None   # anthropic 格式


@pytest.mark.parametrize("provider_name", ["openai", "openrouter"])
def test_openai_compatible_settings_use_openai_tool_format(qapp, tmp_path, provider_name):
    provider = FakeProvider()
    s = Settings(ai_provider=provider_name, ai_model="m", ai_api_key="k",
                 ai_privacy_ack=True)
    panel = _panel(tmp_path, provider, settings=s)
    panel.send_message("hi")
    assert provider.calls[0]["tools"][0]["type"] == "function"


def test_subscription_settings_resolve_profile_and_factory(qapp, tmp_path):
    from keyboard_executor.app.ai_panel import AiPanel
    from keyboard_executor.core.ai.auth.models import AuthProfile

    settings = Settings(ai_provider="openai", ai_auth_mode="subscription",
                        ai_auth_profile="codex", ai_model="gpt-test",
                        ai_privacy_ack=True)
    provider = FakeProvider()
    calls = []

    class Auth:
        def resolve_profile(self, value):
            assert value is settings
            return AuthProfile("openai", "codex", "", source="codex_app_server")

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return provider

    panel = AiPanel(get_settings=lambda: settings, ack_privacy=lambda: None,
                    storage=ScriptStorage(tmp_path), get_selected_script=lambda: None,
                    worker_factory=SyncWorker, provider_factory=factory,
                    auth_service=Auth(), confirm_privacy=lambda: True)
    panel.send_message("hi")
    assert calls[0][1]["auth_mode"] == "subscription"
    assert calls[0][1]["auth_profile"].profile_id == "codex"


def test_privacy_ack_asked_once_then_persisted(qapp, tmp_path):
    acks = []
    s = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=False)
    panel = _panel(tmp_path, FakeProvider(), settings=s, acks=acks)
    panel.send_message("hi")
    assert acks == [True]           # 確認後呼叫 ack_privacy


def test_privacy_declined_blocks_send(qapp, tmp_path):
    provider = FakeProvider()
    s = Settings(ai_provider="anthropic", ai_model="m", ai_api_key="k",
                 ai_privacy_ack=False)
    panel = _panel(tmp_path, provider, settings=s, confirm=False)
    panel.send_message("hi")
    assert provider.calls == []     # 未送出


def test_provider_error_shows_error_bubble(qapp, tmp_path):
    provider = FakeProvider(error=AiProviderError("連線失敗：x"))
    panel = _panel(tmp_path, provider)
    panel.send_message("hi")
    assert any("連線失敗" in t for _, t in _bubble_texts(panel))


def test_clear_conversation_resets(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    panel.send_message("hi")
    panel.clear_conversation()
    assert panel._messages == [] and _bubble_texts(panel) == []


# 空狀態切換：offscreen 下頂層 widget 未 show()，isVisible() 恆為 False，
# 故一律用 isHidden()（只反映明確的 setVisible(False)）判斷。

def test_empty_state_shown_when_no_conversation(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    assert not panel._empty_state.isHidden()
    assert panel._scroll.isHidden()
    assert panel._head.isHidden()   # 沒東西可清 → 不露出空的清除列


def test_conversation_replaces_empty_state(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    panel.send_message("hi")
    assert panel._empty_state.isHidden()
    assert not panel._scroll.isHidden()
    assert not panel._head.isHidden()


def test_clear_conversation_restores_empty_state(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    panel.send_message("hi")
    panel.clear_conversation()
    assert not panel._empty_state.isHidden()
    assert panel._scroll.isHidden()
    assert panel._head.isHidden()


def test_example_button_fills_input(qapp, tmp_path):
    from keyboard_executor.app.ai_panel import EXAMPLE_PROMPT

    panel = _panel(tmp_path, FakeProvider())
    panel.example_button.click()
    assert panel.input_edit.text() == EXAMPLE_PROMPT


from keyboard_executor.core.ai.provider import ToolCall
from keyboard_executor.core.models import script_from_dict


def _script_dict(name="既有"):
    return {"name": name, "target_window": {"title_pattern": "app"},
            "actions": [{"type": "key_press", "key": "a"}]}


def _cards(panel):
    from PySide6.QtWidgets import QFrame

    lay = panel.bubbles_layout
    return [lay.itemAt(i).widget() for i in range(lay.count())
            if lay.itemAt(i).widget() is not None
            and lay.itemAt(i).widget().objectName() == "aiProposalCard"]


def test_new_script_proposal_shows_card_and_applies(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "AI腳本", "target_title_regex": "遊戲",
            "actions": [{"type": "key_press", "key": "a"},
                        {"type": "delay", "ms": 100}]})))
    panel = _panel(tmp_path, provider)
    fired = []
    panel.scripts_changed.connect(lambda: fired.append(1))
    panel.send_message("做一個腳本")
    (card,) = _cards(panel)
    assert "AI腳本" in card.title_label.text()
    assert "按鍵 a" in card.body_label.text()      # 用 action_label 摘要
    card.apply_button.click()
    storage = ScriptStorage(tmp_path)
    assert "AI腳本" in storage.list_names() and fired == [1]


def test_new_rule_proposal_shows_card_and_applies(qapp, tmp_path):
    from keyboard_executor.core.ai.provider import ToolCall

    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_rule", args={"rule": {
            "name": "確認通知", "target_window": {"title_pattern": "遊戲"},
            "region": [10, 20, 300, 80],
            "condition": {"type": "text", "pattern": "確認", "mode": "contains"},
            "triggers": [{"type": "notify", "message": "看到了"}],
        }})))
    panel = _panel(tmp_path, provider)
    fired = []
    panel.rules_changed.connect(lambda: fired.append(1))
    panel.send_message("看圖建立規則")
    (card,) = _cards(panel)
    assert "確認通知" in card.title_label.text() and "文字「確認」" in card.body_label.text()
    card.apply_button.click()
    assert RuleStorage(tmp_path).list_names() == ["確認通知"] and fired == [1]


def test_bundle_applies_script_and_rule_and_updates_renamed_reference(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("自動按")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_automation_bundle", args={
            "scripts": [{
                "name": "自動按", "target_window": {"title_pattern": "遊戲"},
                "actions": [{"type": "key_press", "key": "enter"}],
            }],
            "rules": [{
                "name": "看到確認", "target_window": {"title_pattern": "遊戲"},
                "condition": {"type": "text", "pattern": "確認", "mode": "contains"},
                "triggers": [{"type": "run_script", "script_name": "自動按"}],
            }],
        })))
    from keyboard_executor.app.ai_panel import AiPanel

    panel = AiPanel(get_settings=lambda: AI_ON, ack_privacy=lambda: None,
                    storage=storage, rule_storage=RuleStorage(tmp_path),
                    get_selected_script=lambda: None, worker_factory=SyncWorker,
                    provider_factory=lambda *a: provider,
                    confirm_privacy=lambda: True)
    fired = []
    panel.scripts_changed.connect(lambda: fired.append("script"))
    panel.rules_changed.connect(lambda: fired.append("rule"))
    panel.send_message("建立整套")
    (card,) = _cards(panel)
    assert "1 腳本／1 規則" in card.title_label.text()
    card.apply_button.click()
    assert "自動按 2" in storage.list_names()
    saved_rule = RuleStorage(tmp_path).load("看到確認")
    assert saved_rule.trigger.script_name == "自動按 2"
    assert fired == ["script", "rule"]


def test_new_script_name_conflict_gets_numbered(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("AI腳本")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "AI腳本", "target_title_regex": "t",
            "actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("再做一個")
    _cards(panel)[0].apply_button.click()
    assert "AI腳本 2" in storage.list_names()


def test_edit_proposal_applies_and_undoes(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("目標")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current", args={
            "actions": [{"type": "delay", "ms": 999}]})))
    from keyboard_executor.app.ai_panel import AiPanel

    panel = AiPanel(get_settings=lambda: AI_ON, ack_privacy=lambda: None,
                    storage=storage, get_selected_script=lambda: "目標",
                    worker_factory=SyncWorker,
                    provider_factory=lambda *a: provider,
                    confirm_privacy=lambda: True)
    panel.send_message("把動作改成等待 999ms")
    (card,) = _cards(panel)
    card.apply_button.click()
    assert str(storage.load("目標").actions[0].type) == "delay"
    card.undo_button.click()                       # 套用後卡片出現復原
    assert str(storage.load("目標").actions[0].type) == "key_press"


def test_edit_proposal_without_selection_shows_error(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current",
                                    args={"actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)   # get_selected_script → None
    panel.send_message("改腳本")
    (card,) = _cards(panel)
    assert "沒有選中" in card.body_label.text()


def test_invalid_proposal_shows_error_card_with_retry(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "x", "target_title_regex": "t",
            "actions": [{"type": "hack"}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("做腳本")
    (card,) = _cards(panel)
    assert "無效" in card.body_label.text()
    assert card.retry_button is not None
    # 按「請 AI 修正」→ 以錯誤訊息當一則 user 訊息重送
    provider.result = ChatResult(text="修好了")
    card.retry_button.click()
    assert provider.calls[-1]["messages"][-1]["role"] == "user"
    assert "無效" in provider.calls[-1]["messages"][-1]["content"]


def test_discard_removes_card(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_new_script", args={
            "name": "n", "target_title_regex": "t",
            "actions": [{"type": "delay", "ms": 1}]})))
    panel = _panel(tmp_path, provider)
    panel.send_message("做腳本")
    (card,) = _cards(panel)
    card.discard_button.click()
    assert card.apply_button is None or not card.apply_button.isEnabled()


def _manual_panel(tmp_path, provider, *, storage=None, selected=None,
                  worker_factory=ManualWorker):
    """建 panel 用 ManualWorker（預設）：start() 不自動 run()，讓測試手動控制
    串流完成的時機，用來重現「清除對話／再次送出」與背景結果送達之間的競態。"""
    from keyboard_executor.app.ai_panel import AiPanel

    return AiPanel(get_settings=lambda: AI_ON, ack_privacy=lambda: None,
                   storage=storage or ScriptStorage(tmp_path),
                   get_selected_script=lambda: selected,
                   worker_factory=worker_factory,
                   provider_factory=lambda *a: provider,
                   confirm_privacy=lambda: True)


# ---------- I-1：關閉時停 AI worker ----------

def test_shutdown_noop_after_normal_finish(qapp, tmp_path):
    panel = _panel(tmp_path, FakeProvider())
    panel.send_message("hi")          # SyncWorker：已同步跑完並收尾，_worker 已是 None
    panel.shutdown()                  # 不得拋例外
    assert panel._worker is None


def test_shutdown_aborts_and_waits_running_worker(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(text="回覆"))
    panel = _manual_panel(tmp_path, provider)
    panel.send_message("hi")
    worker = panel._worker
    assert worker is not None
    waited = []
    worker.wait = lambda *a, **kw: waited.append(True) or True
    panel.shutdown()
    assert panel._abort.is_set() and waited == [True]


# ---------- I-2：清除對話丟棄在途回應（世代計數器） ----------

def test_clear_conversation_mid_stream_discards_late_finish(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(text="遲到的回覆"))
    panel = _manual_panel(tmp_path, provider)
    panel.send_message("hi")
    worker = panel._worker
    assert worker is not None
    panel.clear_conversation()
    worker.run()               # 模擬背景執行緒此時才送達 finished
    assert panel._messages == []
    assert _cards(panel) == []
    assert _bubble_texts(panel) == []


def test_clear_conversation_mid_stream_discards_late_failure(qapp, tmp_path):
    provider = FakeProvider(error=AiProviderError("連線中斷：x"))
    panel = _manual_panel(tmp_path, provider)
    panel.send_message("hi")
    worker = panel._worker
    panel.clear_conversation()
    worker.run()               # 模擬背景執行緒此時才送達 failed
    assert panel._messages == []
    assert _bubble_texts(panel) == []


# ---------- M-1：SSE 中途斷線保留已收文字＋標「（回應中斷）」 ----------

def test_mid_stream_failure_marks_bubble_interrupted_and_adds_error_bubble(qapp, tmp_path):
    provider = FakeProvider(deltas=["部分回覆"], error=AiProviderError("連線中斷：reset"))
    panel = _panel(tmp_path, provider)
    panel.send_message("hi")
    texts = _bubble_texts(panel)
    assert ("aiBubbleAssistant", "部分回覆（回應中斷）") in texts
    assert any("連線中斷" in t for _, t in texts if t != "部分回覆（回應中斷）")


# ---------- M-3：edit 提案 load 失敗 vs actions_for_edit 失敗分開標示 ----------

def test_edit_proposal_load_failure_shows_read_error(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current",
                                    args={"actions": [{"type": "delay", "ms": 1}]})))
    panel = _manual_panel(tmp_path, provider, selected="不存在",
                          worker_factory=SyncWorker)
    panel.send_message("改腳本")
    (card,) = _cards(panel)
    assert "無法讀取腳本「不存在」" in card.body_label.text()


def test_edit_proposal_invalid_actions_shows_ai_invalid_error(qapp, tmp_path):
    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict(_script_dict("目標")))
    provider = FakeProvider(result=ChatResult(
        text="", tool_call=ToolCall(name="propose_edit_current",
                                    args={"actions": [{"type": "hack"}]})))
    panel = _manual_panel(tmp_path, provider, storage=storage, selected="目標",
                          worker_factory=SyncWorker)
    panel.send_message("改腳本")
    (card,) = _cards(panel)
    assert "AI 產出無效" in card.body_label.text()


# ---------- M-9：串流中按 Enter 不得清空/丟失輸入 ----------

def test_on_send_keeps_input_text_when_streaming(qapp, tmp_path):
    provider = FakeProvider(result=ChatResult(text="回覆"))
    panel = _manual_panel(tmp_path, provider)
    panel.send_message("第一則")
    assert panel._worker is not None
    panel.input_edit.setText("還在打字")
    panel._on_send()
    assert panel.input_edit.text() == "還在打字"
    assert panel._messages == [{"role": "user", "content": "第一則"}]


def _press_paste(panel):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    panel.input_edit.setFocus()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier, "v")
    QCoreApplication.sendEvent(panel.input_edit, event)


def test_ctrl_v_screenshot_in_clipboard_becomes_attachment(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication, QImage

    image = QImage(200, 120, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    QGuiApplication.clipboard().setImage(image)
    panel = _panel(tmp_path, FakeProvider())
    _press_paste(panel)
    assert len(panel._pending_images) == 1
    assert panel._pending_images[0]["name"] == "貼上的圖片1.png"
    assert (panel._pending_images[0]["width"], panel._pending_images[0]["height"]) == (200, 120)
    assert panel.input_edit.text() == ""


def test_ctrl_v_copied_image_file_becomes_attachment(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QImage

    source = tmp_path / "小地圖.png"
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(0xFF113355)
    assert image.save(str(source), "PNG")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    # 不交給剪貼簿：setMimeData 會轉移擁有權，Python 再釋放一次會造成記憶體損壞。
    panel = _panel(tmp_path, FakeProvider())
    assert panel.paste_images(mime)
    assert [i["name"] for i in panel._pending_images] == ["小地圖.png"]


def test_ctrl_v_text_still_pastes_text(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText("幫我做練功腳本")
    panel = _panel(tmp_path, FakeProvider())
    _press_paste(panel)
    assert panel._pending_images == []
    assert panel.input_edit.text() == "幫我做練功腳本"


def test_selected_script_map_analysis_and_minimap_image_reach_ai(qapp, tmp_path):
    import cv2
    import numpy as np
    from keyboard_executor.app.ai_panel import AiPanel
    from keyboard_executor.core.models import script_from_dict

    storage = ScriptStorage(tmp_path)
    storage.save(script_from_dict({"name": "巡邏", "target_window": {"app_name": "msw.exe"},
                                   "actions": [{"type": "delay", "ms": 0}]}))
    ok, png = cv2.imencode(".png", np.zeros((20, 30, 3), np.uint8))
    storage.save_route_map("巡邏", {"analysis": "- 平台 1：高度 y=200，左右 x=100～200（打怪）"},
                           png.tobytes())
    provider = FakeProvider()
    panel = AiPanel(get_settings=lambda: AI_ON, ack_privacy=lambda: None, storage=storage,
                    rule_storage=RuleStorage(tmp_path), get_selected_script=lambda: "巡邏",
                    worker_factory=SyncWorker, provider_factory=lambda *a: provider,
                    confirm_privacy=lambda: True)
    panel.send_message("每層打兩趟")
    first = provider.calls[0]
    assert "小地圖分析" in first["system"] and "平台 1：高度 y=200" in first["system"]
    assert len(first["messages"][-1]["images"]) == 1
    panel.send_message("再快一點")
    second = provider.calls[1]
    assert "平台 1" in second["system"]
    assert not second["messages"][-1].get("images")       # 截圖只附一次


def _demo_controller():
    from PySide6.QtCore import QObject, Signal

    class _C(QObject):
        progress = Signal(dict)
        finished = Signal(object)
        reset_needed = Signal(str)
        active_changed = Signal(bool)
        scripts_changed = Signal()

        def __init__(self):
            super().__init__()
            self.active = False
            self.session = "S"
            self.applied, self.resumes, self.stops = [], [], 0

        def apply_version(self, session, version):
            self.applied.append((session, version))
            return "練功"

        def resume_after_reset(self, proceed):
            self.resumes.append(proceed)

        def stop(self):
            self.stops += 1

    return _C()


def _demo_panel(tmp_path, settings=AI_ON):
    from keyboard_executor.app.ai_panel import AiPanel
    controller = _demo_controller()
    panel = AiPanel(get_settings=lambda: settings, ack_privacy=lambda: None,
                    storage=ScriptStorage(tmp_path), rule_storage=RuleStorage(tmp_path),
                    get_selected_script=lambda: None, worker_factory=SyncWorker,
                    provider_factory=lambda *a, **k: FakeProvider(),
                    confirm_privacy=lambda: True, demo_controller=controller)
    return panel, controller


def test_demo_button_disabled_without_ai(qapp, tmp_path):
    panel, _ = _demo_panel(tmp_path, settings=Settings())
    assert not panel.demo_button.isEnabled()
    panel2, _ = _demo_panel(tmp_path)
    assert panel2.demo_button.isEnabled()


def test_demo_button_emits_request(qapp, tmp_path):
    panel, _ = _demo_panel(tmp_path)
    got = []
    panel.demo_requested.connect(lambda: got.append(True))
    panel.demo_button.click()
    assert got == [True]


def test_demo_progress_and_stop(qapp, tmp_path):
    panel, controller = _demo_panel(tmp_path)
    controller.active = True
    controller.active_changed.emit(True)
    assert not panel.demo_button.isEnabled()
    controller.progress.emit({"stage": "running", "round": 2})
    assert "第 2 輪" in panel.demo_status_label.text()
    panel.demo_stop_button.click()
    assert controller.stops == 1


def test_demo_reset_card_resumes(qapp, tmp_path):
    panel, controller = _demo_panel(tmp_path)
    controller.reset_needed.emit("角色沒有回到示範起點")
    card = panel._demo_reset_card
    assert "起點" in card.body_label.text()
    card.continue_button.click()
    assert controller.resumes == [True]
    assert not card.continue_button.isEnabled()


def test_summary_card_marks_untested_version(qapp, tmp_path):
    from keyboard_executor.core.ai_demo.loop import DemoLoopResult, RoundRecord
    panel, controller = _demo_panel(tmp_path)
    result = DemoLoopResult("max_rounds", "已試跑 2 輪仍需修正", [
        RoundRecord(1, 1, "time_up", "needs_fix", "改跳躍時機"),
        RoundRecord(2, 2, "time_up", "needs_fix", "加長攻擊"),
    ], library_version=2, untested_version=3, goal="左右打怪")
    controller.finished.emit(result)
    card = panel._demo_summary_card
    text = card.body_label.text()
    assert "左右打怪" in text and "改跳躍時機" in text and "加長攻擊" in text
    labels = [b.text() for b in card.version_buttons]
    assert any("第 3 版" in t and "未試跑" in t for t in labels)
    assert any("第 1 版" in t for t in labels)
    [b3] = [b for b in card.version_buttons if "第 3 版" in b.text()]
    b3.click()
    assert controller.applied == [("S", 3)]
