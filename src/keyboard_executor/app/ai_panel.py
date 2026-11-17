"""AI 助手聊天面板（QDockWidget 內容）。

依賴全部由建構子注入（get_settings/ack_privacy/storage/get_selected_script/
worker_factory/provider_factory/confirm_privacy），面板不碰 SettingsStore 與
MainWindow —— 可 offscreen 測試。串流走 Worker（背景 QThread），delta 經
progress signal 回 UI 執行緒即時追加。"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.naming import numbered_name
from keyboard_executor.app.ai_worker import build_chat_job
from keyboard_executor.app.ai_images import (
    MAX_IMAGE_COUNT,
    MAX_TOTAL_IMAGE_BYTES,
    ImageAttachmentError,
    attachment_pixmap,
    load_image_attachment,
)
from keyboard_executor.app.worker import Worker
from keyboard_executor.core.ai.factory import make_provider
from keyboard_executor.core.ai.manual import build_system_prompt
from keyboard_executor.core.ai.script_gen import (
    actions_for_edit,
    automation_bundle_from_proposal,
    rule_from_proposal,
    script_from_proposal,
)
from keyboard_executor.core.ai.tools import (
    TOOL_BUNDLE,
    TOOL_EDIT,
    TOOL_NEW,
    TOOL_RULE_NEW,
    as_anthropic,
    as_openai,
)
from keyboard_executor.core.models import (
    Rule,
    Script,
    ScriptValidationError,
    action_label,
    rule_from_dict,
    rule_to_dict,
    script_to_dict,
)


EXAMPLE_PROMPT = "偵測到畫面出現怪物時，自動連續攻擊，血量低時補血"


def _confirm_privacy_dialog(parent) -> bool:
    """首次送出的隱私告知（繁中自建按鈕，比照 confirm.py 慣例）。"""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("傳送資料給 AI 供應商")
    box.setText("你的訊息、附加圖片與目前選中腳本的內容，會傳送給你在設定頁選擇的\n"
                "AI 供應商（Anthropic、OpenAI 或 OpenRouter）處理。是否繼續？")
    ok = box.addButton("繼續", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is ok


class _ProposalCard(QFrame):
    """提案/錯誤卡片。按鈕由 AiPanel 接線；不存在的按鈕為 None。"""

    def __init__(self, title: str, body: str, *, apply_=False, discard=False,
                 retry=False, parent=None):
        super().__init__(parent)
        self.setObjectName("aiProposalCard")
        lay = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("aiCardTitle")
        self.body_label = QLabel(body)
        self.body_label.setObjectName("aiCardError" if retry else "aiCardBody")
        self.body_label.setWordWrap(True)
        lay.addWidget(self.title_label)
        lay.addWidget(self.body_label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.apply_button = self.discard_button = None
        self.retry_button = self.undo_button = None
        if apply_:
            self.apply_button = QPushButton("套用")
            self.apply_button.setProperty("variant", "primary")
            row.addWidget(self.apply_button)
        if discard:
            self.discard_button = QPushButton("捨棄")
            self.discard_button.setProperty("variant", "ghost")
            row.addWidget(self.discard_button)
        if retry:
            self.retry_button = QPushButton("請 AI 修正")
            row.addWidget(self.retry_button)
        lay.addLayout(row)
        self._button_row = row

    def mark_applied(self, undoable: bool) -> None:
        self.title_label.setText(self.title_label.text() + "　已套用 ✓")
        for b in (self.apply_button, self.discard_button):
            if b is not None:
                b.setEnabled(False)
        if undoable:
            self.undo_button = QPushButton("復原")
            self.undo_button.setProperty("variant", "ghost")
            self._button_row.addWidget(self.undo_button)


_numbered_name = numbered_name


def _rule_summary(rule: Rule) -> str:
    condition = rule.condition
    if condition.type == "text":
        target = f"文字「{condition.pattern}」"
    elif condition.type == "image":
        target = f"圖像模板「{condition.template}」"
    else:
        target = f"顏色 HSV({condition.hue}, {condition.sat}, {condition.val})"
    triggers = []
    for trigger in rule.triggers:
        if trigger.type == "run_script":
            triggers.append(f"執行腳本「{trigger.script_name}」")
        elif trigger.type == "notify":
            triggers.append(f"通知「{trigger.message}」")
        else:
            triggers.append("停止全部回放")
    region = f"；區域 {rule.region}" if rule.region else "；全視窗"
    return f"偵測 {target}{region} → " + "、".join(triggers)


class AiPanel(QWidget):
    open_settings_requested = Signal()
    scripts_changed = Signal()
    rules_changed = Signal()
    demo_requested = Signal()

    def __init__(self, get_settings, ack_privacy, storage, get_selected_script,
                 rule_storage=None,
                 worker_factory=Worker, provider_factory=make_provider,
                 confirm_privacy=None, auth_service=None, demo_controller=None,
                 parent=None):
        super().__init__(parent)
        self._demo = demo_controller
        self._demo_progress_card = None
        self._demo_reset_card = None
        self._demo_summary_card = None
        self.demo_status_label = None
        self.demo_stop_button = None
        self._get_settings = get_settings
        self._ack_privacy = ack_privacy
        self._storage = storage
        self._rule_storage = rule_storage
        self._get_selected_script = get_selected_script
        self._worker_factory = worker_factory
        self._provider_factory = provider_factory
        self._auth_service = auth_service
        self._confirm_privacy = confirm_privacy or (
            lambda: _confirm_privacy_dialog(self))
        self._messages: list[dict] = []
        self._pending_images: list[dict] = []
        self._image_cache = tempfile.TemporaryDirectory(
            prefix="keyboard-executor-ai-")
        self._worker = None
        self._abort = threading.Event()
        self._streaming_bubble: QLabel | None = None
        self._edit_target: str | None = None   # 送出當下選中的腳本（edit 提案用）
        self._map_images_sent: set[str] = set()   # 已附過小地圖截圖的腳本
        # 世代計數器（I-2）：clear_conversation 遞增；每次 send_message 記下當時的世代，
        # _on_finished/_on_failed 送達時若世代已變（中途被清除），整批捨棄——避免遲到的
        # assistant 回覆補進剛清空的歷史，造成 assistant-first（Anthropic 拒收）。
        self._turn = 0
        self._active_turn = 0
        self._build_ui()
        if self._demo is not None:
            self._demo.progress.connect(self._on_demo_progress)
            self._demo.finished.connect(self._on_demo_finished)
            self._demo.reset_needed.connect(self._on_demo_reset_needed)
            self._demo.active_changed.connect(self._on_demo_active)
        self.refresh_state()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self._stack = QStackedLayout(self)
        # 頁 0：未設定引導
        setup = QWidget()
        s_lay = QVBoxLayout(setup)
        hint = QLabel("尚未設定 AI 供應商。\n請到「設定」選擇供應商並填入 model 與 API 金鑰。")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setup_button = QPushButton("開啟設定")
        self.setup_button.setProperty("variant", "primary")
        self.setup_button.clicked.connect(self.open_settings_requested.emit)
        s_lay.addStretch(1)
        s_lay.addWidget(hint)
        s_lay.addWidget(self.setup_button, alignment=Qt.AlignmentFlag.AlignCenter)
        s_lay.addStretch(1)
        self._stack.addWidget(setup)
        # 頁 1：聊天
        chat = QWidget()
        c_lay = QVBoxLayout(chat)
        # 標題列由 dock 的自訂 title bar 負責（見 main_window._build_ai_titlebar）；
        # 這裡只放「清除對話」，且僅在對話有內容時整列顯示——空對話時沒東西可清，
        # 露出一條空頭列只會和 dock 標題疊成重複的雙標題。
        self._head = QWidget()
        head = QHBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 0)
        head.addStretch(1)
        self.clear_button = QPushButton("清除對話")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.clicked.connect(self.clear_conversation)
        head.addWidget(self.clear_button)
        c_lay.addWidget(self._head)
        self._empty_state = self._build_empty_state()
        c_lay.addWidget(self._empty_state, stretch=1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        bubbles_host = QWidget()
        self.bubbles_layout = QVBoxLayout(bubbles_host)
        self.bubbles_layout.addStretch(1)
        self._scroll.setWidget(bubbles_host)
        c_lay.addWidget(self._scroll, stretch=1)
        self._attachment_frame = QFrame()
        self._attachment_frame.setObjectName("aiAttachmentTray")
        self._attachment_layout = QHBoxLayout(self._attachment_frame)
        self._attachment_layout.setContentsMargins(6, 6, 6, 6)
        self._attachment_layout.setSpacing(6)
        self._attachment_layout.addStretch(1)
        self._attachment_frame.hide()
        c_lay.addWidget(self._attachment_frame)
        # 輸入區分兩行：dock 很窄，輸入框和三顆按鈕擠同一行會把輸入框壓到只剩幾個字。
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("描述想自動化的動作，或 Ctrl+V 貼上截圖…")
        self.input_edit.returnPressed.connect(self._on_send)
        self.input_edit.installEventFilter(self)
        c_lay.addWidget(self.input_edit)
        row = QHBoxLayout()
        self.upload_button = QPushButton("＋ 圖片")
        self.upload_button.setObjectName("aiUploadButton")
        self.upload_button.setToolTip("加入圖片（最多 4 張；PNG/JPEG/GIF/WebP），也可在輸入框按 Ctrl+V 貼上")
        self.upload_button.clicked.connect(self._choose_images)
        self.send_button = QPushButton("送出")
        self.send_button.setProperty("variant", "primary")
        self.send_button.clicked.connect(self._on_send)
        self.stop_button = QPushButton("停止")
        self.stop_button.setProperty("variant", "ghost")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_streaming)
        self.demo_button = QPushButton("示範錄製")
        self.demo_button.setObjectName("aiDemoButton")
        self.demo_button.setToolTip("手動示範一圈練功，AI 看按鍵和畫面產生腳本，並自動試跑修正")
        self.demo_button.clicked.connect(self._on_demo_clicked)
        self.demo_button.setVisible(self._demo is not None)
        row.addWidget(self.upload_button)
        row.addWidget(self.demo_button)
        row.addStretch(1)
        row.addWidget(self.stop_button)
        row.addWidget(self.send_button)
        c_lay.addLayout(row)
        self._stack.addWidget(chat)
        self._sync_conversation_chrome()

    def _build_empty_state(self) -> QWidget:
        """無對話時的引導區：說明這個面板能做什麼，並給一個可直接套用的範例。"""
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)
        mark = QLabel("✦")
        mark.setObjectName("aiEmptyMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("嗨，我可以幫你：\n· 依你的描述產生腳本／規則\n· 看遊戲截圖給自動化建議")
        text.setObjectName("aiEmptyText")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.example_button = QPushButton("試試：偵測到怪物時自動攻擊")
        self.example_button.setObjectName("aiExampleChip")
        self.example_button.clicked.connect(self._use_example)
        lay.addStretch(1)
        lay.addWidget(mark)
        lay.addWidget(text)
        lay.addWidget(self.example_button, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(2)
        return host

    def _use_example(self) -> None:
        self.input_edit.setText(EXAMPLE_PROMPT)
        self.input_edit.setFocus()

    def _has_conversation(self) -> bool:
        """尾端固定有一個 stretch，count() > 1 代表有泡泡/卡片。"""
        return self.bubbles_layout.count() > 1

    def _sync_conversation_chrome(self) -> None:
        """依「有無對話」切換空狀態與捲動區，並收合空的清除列。"""
        has = self._has_conversation()
        self._empty_state.setVisible(not has)
        self._scroll.setVisible(has)
        self._head.setVisible(has)

    def refresh_state(self) -> None:
        s = self._get_settings()
        credential_ready = (bool(s.ai_auth_profile)
                            if s.ai_auth_mode == "subscription"
                            else bool(s.ai_api_key))
        model_ready = bool(s.ai_model) or s.ai_auth_mode == "subscription"
        configured = bool(s.ai_provider and model_ready and credential_ready)
        self._stack.setCurrentIndex(1 if configured else 0)
        # offscreen 測試中頂層 widget 未 show()，isVisible() 恆為 False；
        # 用 enabled 狀態同步反映「未設定」，測試與實際使用皆可靠判斷。
        self.input_edit.setEnabled(configured)
        self.send_button.setEnabled(configured)
        self._configured = configured
        demo_active = self._demo is not None and self._demo.active
        self.demo_button.setEnabled(configured and self._demo is not None and not demo_active)

    def _add_bubble(self, object_name: str, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # 插在尾端 stretch 之前
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, label)
        self._sync_conversation_chrome()
        return label

    def _choose_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "加入圖片", "",
            "圖片 (*.png *.jpg *.jpeg *.gif *.webp);;所有檔案 (*)")
        if paths:
            self.add_image_paths(paths)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # 輸入框 Ctrl+V：剪貼簿是圖片（截圖）或圖片檔就加成附件，文字照常貼上。
        if (watched is self.input_edit and event.type() == QEvent.Type.KeyPress
                and event.matches(QKeySequence.StandardKey.Paste)):
            mime = QGuiApplication.clipboard().mimeData()
            if mime is not None and self.paste_images(mime):
                return True
        return super().eventFilter(watched, event)

    def paste_images(self, mime: QMimeData) -> bool:
        """把剪貼簿內容加成待送圖片；沒有圖片回 False（交回一般文字貼上）。"""
        files = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        files = [path for path in files
                 if Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")]
        if files:
            self.add_image_paths(files)
            return True
        if not mime.hasImage():
            return False
        image = QImage(mime.imageData())
        if image.isNull():
            return False
        folder = Path(self._image_cache.name) / "clipboard"
        folder.mkdir(parents=True, exist_ok=True)
        self._pasted_count = getattr(self, "_pasted_count", 0) + 1
        path = folder / f"貼上的圖片{self._pasted_count}.png"
        if not image.save(str(path), "PNG"):
            self._add_bubble("aiBubbleAssistant", "無法讀取剪貼簿圖片")
            return True
        self.add_image_paths([str(path)])
        return True

    def add_image_paths(self, paths: list[str]) -> None:
        """加入待送圖片；公開 seam 供測試與拖放等未來 UI 共用。"""
        for path in paths:
            if len(self._pending_images) >= MAX_IMAGE_COUNT:
                self._add_bubble(
                    "aiBubbleAssistant",
                    f"每則訊息最多附加 {MAX_IMAGE_COUNT} 張圖片")
                break
            try:
                attachment = load_image_attachment(path, self._image_cache.name)
            except (ImageAttachmentError, OSError) as exc:
                self._add_bubble("aiBubbleAssistant", str(exc))
                continue
            used = sum(
                image.get("size_bytes", 0)
                for message in self._messages
                for image in message.get("images", []))
            used += sum(image.get("size_bytes", 0)
                        for image in self._pending_images)
            if used + attachment.get("size_bytes", 0) > MAX_TOTAL_IMAGE_BYTES:
                self._add_bubble(
                    "aiBubbleAssistant",
                    "本次對話的圖片總量已達 16MB；請清除對話後再加入圖片")
                continue
            self._pending_images.append(attachment)
        self._rebuild_attachment_tray()

    def _rebuild_attachment_tray(self) -> None:
        while self._attachment_layout.count() > 1:
            item = self._attachment_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, attachment in enumerate(self._pending_images):
            chip = QFrame()
            chip.setObjectName("aiAttachmentChip")
            lay = QVBoxLayout(chip)
            lay.setContentsMargins(4, 4, 4, 4)
            preview = QLabel()
            preview.setObjectName("aiAttachmentPreview")
            preview.setPixmap(attachment_pixmap(attachment, 64))
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(attachment["name"])
            name.setObjectName("aiAttachmentName")
            name.setToolTip(attachment["name"])
            name.setMaximumWidth(88)
            remove = QPushButton("移除")
            remove.setProperty("variant", "ghost")
            remove.setProperty("attachment_index", index)
            # 用 bound slot，避免待 deleteLater 的子按鈕透過 lambda 保留 self；
            # 子物件釋放最後一個父物件參照會造成重入析構（Windows Qt 崩潰）。
            remove.clicked.connect(self._on_remove_image_clicked)
            lay.addWidget(preview)
            lay.addWidget(name)
            lay.addWidget(remove)
            self._attachment_layout.insertWidget(
                self._attachment_layout.count() - 1, chip)
        self._attachment_frame.setVisible(bool(self._pending_images))

    def _on_remove_image_clicked(self) -> None:
        button = self.sender()
        if button is not None:
            self._remove_image(int(button.property("attachment_index")))

    def _remove_image(self, index: int) -> None:
        if 0 <= index < len(self._pending_images):
            self._pending_images.pop(index)
            self._rebuild_attachment_tray()

    def _add_sent_images(self, images: list[dict]) -> None:
        if not images:
            return
        frame = QFrame()
        frame.setObjectName("aiSentImages")
        row = QHBoxLayout(frame)
        row.setContentsMargins(6, 4, 6, 4)
        for image in images:
            preview = QLabel()
            preview.setPixmap(attachment_pixmap(image, 72))
            preview.setToolTip(image["name"])
            row.addWidget(preview)
        row.addStretch(1)
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, frame)
        self._sync_conversation_chrome()

    # ---------- 聊天流 ----------

    def _on_send(self) -> None:
        if self._worker is not None:
            return   # 串流中：保留輸入框文字，避免 send_message 重入早退把打的字弄丟
        text = self.input_edit.text().strip()
        images = list(self._pending_images)
        if text or images:
            self.input_edit.clear()
            if self.send_message(text, images=images):
                self._pending_images = []
                self._rebuild_attachment_tray()

    def send_message(self, text: str, *, images: list[dict] | None = None) -> bool:
        if self._worker is not None:
            return False   # 串流中不重入
        images = list(images or [])
        text = text.strip() or "請分析附加圖片，並依我的畫面協助建立適合的規則或腳本。"
        s = self._get_settings()
        if s.ai_auth_mode == "subscription":
            if self._auth_service is None:
                self._add_bubble("aiBubbleAssistant", "訂閱登入服務尚未初始化")
                return False
            try:
                auth_profile = self._auth_service.resolve_profile(s)
            except Exception as exc:
                self._add_bubble("aiBubbleAssistant", f"無法讀取訂閱登入：{exc}")
                return False
            if auth_profile is None:
                self._add_bubble("aiBubbleAssistant", "訂閱登入已失效，請到設定重新連結")
                self.open_settings_requested.emit()
                return False
            provider = self._provider_factory(
                s.ai_provider, "", s.ai_model, auth_mode="subscription",
                auth_profile=auth_profile)
        else:
            provider = self._provider_factory(s.ai_provider, s.ai_api_key, s.ai_model)
        if provider is None:
            self.refresh_state()
            return False
        if not s.ai_privacy_ack:
            if not self._confirm_privacy():
                return False
            self._ack_privacy()
        self._add_sent_images(images)
        self._add_bubble("aiBubbleUser", text)
        user_message = {"role": "user", "content": text}
        if images:
            user_message["images"] = images
        self._messages.append(user_message)
        self._edit_target = self._get_selected_script()
        script_json = None
        if self._edit_target:
            try:
                script_json = json.dumps(
                    script_to_dict(self._storage.load(self._edit_target)),
                    ensure_ascii=False, indent=2)
            except ScriptValidationError:
                script_json = None
        system = build_system_prompt(script_json, self._map_analysis(self._edit_target,
                                                                     user_message))
        tools = as_anthropic() if s.ai_provider == "anthropic" else as_openai()
        self._abort = threading.Event()
        self._active_turn = self._turn
        self._streaming_bubble = self._add_bubble("aiBubbleAssistant", "")
        job = build_chat_job(provider, list(self._messages), system=system,
                             tools=tools, abort_event=self._abort)
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        worker = self._worker_factory(job)
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.start()
        return True

    def _on_progress(self, payload: dict) -> None:
        if payload.get("kind") == "delta" and self._streaming_bubble is not None:
            self._streaming_bubble.setText(
                self._streaming_bubble.text() + payload["text"])
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_finished(self, result) -> None:
        self._teardown_worker()
        bubble = self._streaming_bubble
        self._streaming_bubble = None
        if self._active_turn != self._turn:
            return   # 對話已在串流中被清除（I-2）：捨棄這次遲到的回覆
        if result is None:   # 使用者中止
            if bubble is not None:
                bubble.setText(bubble.text() + "（已停止）")
            return
        if bubble is not None:
            bubble.setText(result.text)
            if not result.text:
                bubble.setText("（已提出腳本提案）")
        # 空 assistant content 兩家 API 都可能拒收，補占位文字
        self._messages.append({"role": "assistant",
                               "content": result.text or "（已提出腳本提案）"})
        if result.tool_call is not None:
            self._handle_tool_call(result.tool_call)

    def _on_failed(self, message: str) -> None:
        self._teardown_worker()
        bubble = self._streaming_bubble
        self._streaming_bubble = None
        if self._active_turn != self._turn:
            return   # 對話已在串流中被清除（I-2）：捨棄這次遲到的失敗回報
        if bubble is not None and not bubble.text():
            bubble.setText(message)
        elif bubble is not None:
            # 已收到部分文字才中斷（M-1，spec §11）：保留已收文字＋標尾端中斷，
            # 錯誤訊息另開一則泡泡，不覆蓋掉已經串出來的內容。
            bubble.setText(bubble.text() + "（回應中斷）")
            self._add_bubble("aiBubbleAssistant", message)
        else:
            self._add_bubble("aiBubbleAssistant", message)

    def _teardown_worker(self) -> None:
        self._worker = None
        self.send_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def stop_streaming(self) -> None:
        self._abort.set()

    def shutdown(self) -> None:
        """I-1：關窗前的收尾。中止進行中的串流並等背景執行緒真正結束，避免
        「QThread: Destroyed while thread is still running」；比照 MainWindow
        對回放/監看 worker 的收尾模式（見 main_window._cleanup_worker）。"""
        self._abort.set()
        if self._worker is not None:
            self._worker.wait()
        self._image_cache.cleanup()

    def _map_analysis(self, target, user_message) -> str | None:
        """選中的腳本有小地圖分析時放進提示；小地圖截圖每段對話只附一次。"""
        loader = getattr(self._storage, "load_route_map", None)
        if not target or loader is None:
            return None
        try:
            data = loader(target)
        except ScriptValidationError:
            return None
        if not data or not data.get("analysis"):
            return None
        image = self._storage.route_map_image(target)
        if image is not None and target not in self._map_images_sent:
            try:
                attachment = load_image_attachment(str(image), self._image_cache.name)
            except (ImageAttachmentError, OSError):
                attachment = None
            if attachment is not None:
                user_message.setdefault("images", []).append(attachment)
                self._map_images_sent.add(target)
        return data["analysis"]

    def clear_conversation(self) -> None:
        self._map_images_sent = set()
        self._turn += 1   # I-2：讓仍在途的串流結果送達時發現世代已變而自我捨棄
        self._messages = []
        self._pending_images = []
        self._rebuild_attachment_tray()
        self._streaming_bubble = None
        while self.bubbles_layout.count() > 1:   # 留住尾端 stretch
            item = self.bubbles_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sync_conversation_chrome()   # 清空後回到空狀態引導

    # ---------- 提案卡片（Task 9 實作）----------

    def _add_card(self, card: "_ProposalCard") -> "_ProposalCard":
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, card)
        self._sync_conversation_chrome()
        return card

    def _handle_tool_call(self, tool_call) -> None:
        if tool_call.name == TOOL_NEW:
            self._card_for_new(tool_call.args)
        elif tool_call.name == TOOL_EDIT:
            self._card_for_edit(tool_call.args)
        elif tool_call.name == TOOL_RULE_NEW:
            self._card_for_rule(tool_call.args)
        elif tool_call.name == TOOL_BUNDLE:
            self._card_for_bundle(tool_call.args)
        else:
            self._error_card(f"不認識的工具：{tool_call.name}")

    def _card_for_new(self, args: dict) -> None:
        try:
            script = script_from_proposal(args.get("name", ""),
                                          args.get("target_title_regex", ""),
                                          args.get("actions") or [])
        except ScriptValidationError as e:
            self._error_card(f"AI 產出無效：{e}")
            return
        body = "\n".join(f"{i + 1}. {action_label(a)}"
                         for i, a in enumerate(script.actions))
        card = self._add_card(_ProposalCard(f"新腳本提案：{script.name}", body,
                                            apply_=True, discard=True))
        card.apply_button.clicked.connect(
            lambda: self._apply_new(card, script))
        card.discard_button.clicked.connect(
            lambda: self._discard_card(card))

    def _card_for_edit(self, args: dict) -> None:
        target = self._edit_target
        if not target:
            self._error_card("AI 想修改腳本，但目前沒有選中的腳本。"
                             "請先在清單選取腳本後再試。")
            return
        try:
            current = self._storage.load(target)
        except ScriptValidationError as e:
            self._error_card(f"無法讀取腳本「{target}」：{e}")
            return
        try:
            edited = actions_for_edit(current, args.get("actions") or [])
        except ScriptValidationError as e:
            self._error_card(f"AI 產出無效：{e}")
            return
        body = "\n".join(f"{i + 1}. {action_label(a)}"
                         for i, a in enumerate(edited.actions))
        card = self._add_card(_ProposalCard(f"修改腳本提案：{target}", body,
                                            apply_=True, discard=True))
        card.apply_button.clicked.connect(
            lambda: self._apply_edit(card, previous=current, edited=edited))
        card.discard_button.clicked.connect(
            lambda: self._discard_card(card))

    def _card_for_rule(self, args: dict) -> None:
        if self._rule_storage is None:
            self._error_card("規則儲存服務尚未初始化")
            return
        try:
            rule = rule_from_proposal(args.get("rule") or {})
            self._validate_rule_script_refs([rule], set())
        except ScriptValidationError as exc:
            self._error_card(f"AI 產出無效：{exc}")
            return
        card = self._add_card(_ProposalCard(
            f"新規則提案：{rule.name}", _rule_summary(rule),
            apply_=True, discard=True))
        card.apply_button.clicked.connect(lambda: self._apply_new_rule(card, rule))
        card.discard_button.clicked.connect(lambda: self._discard_card(card))

    def _card_for_bundle(self, args: dict) -> None:
        if self._rule_storage is None:
            self._error_card("規則儲存服務尚未初始化")
            return
        try:
            scripts, rules = automation_bundle_from_proposal(
                args.get("scripts"), args.get("rules"))
            self._validate_rule_script_refs(rules, {script.name for script in scripts})
        except ScriptValidationError as exc:
            self._error_card(f"AI 產出無效：{exc}")
            return
        lines = []
        if scripts:
            lines.append("腳本：")
            for script in scripts:
                lines.append(f"• {script.name}（{len(script.actions)} 個動作）")
                lines.extend(f"  {i + 1}. {action_label(action)}"
                             for i, action in enumerate(script.actions))
        if rules:
            lines.append("規則：")
            lines.extend(f"• {rule.name}：{_rule_summary(rule)}" for rule in rules)
        card = self._add_card(_ProposalCard(
            f"自動化套組提案（{len(scripts)} 腳本／{len(rules)} 規則）",
            "\n".join(lines), apply_=True, discard=True))
        card.apply_button.clicked.connect(
            lambda: self._apply_bundle(card, scripts, rules))
        card.discard_button.clicked.connect(lambda: self._discard_card(card))

    def _validate_rule_script_refs(self, rules: list[Rule], proposed: set[str]) -> None:
        available = set(self._storage.list_names()) | proposed
        for rule in rules:
            for trigger in rule.triggers:
                if (trigger.type == "run_script"
                        and trigger.script_name not in available):
                    raise ScriptValidationError(
                        f"規則「{rule.name}」引用不存在的腳本「{trigger.script_name}」")

    def _error_card(self, message: str) -> None:
        card = self._add_card(_ProposalCard("提案有問題", message, retry=True))
        card.retry_button.clicked.connect(
            lambda: self.send_message(message))

    def _apply_new(self, card, script: Script) -> None:
        final_name = _numbered_name(script.name, self._storage.list_names())
        if final_name != script.name:
            script = dataclasses.replace(script, name=final_name)
        try:
            self._storage.save(script)
        except ScriptValidationError as e:
            card.body_label.setText(f"套用失敗：{e}")
            return
        card.title_label.setText(f"新腳本提案：{final_name}")
        card.mark_applied(undoable=False)
        self.scripts_changed.emit()

    def _apply_new_rule(self, card, rule: Rule) -> None:
        final_name = _numbered_name(rule.name, self._rule_storage.list_names())
        if final_name != rule.name:
            rule = dataclasses.replace(rule, name=final_name)
        try:
            self._rule_storage.save(rule)
        except ScriptValidationError as exc:
            card.body_label.setText(f"套用失敗：{exc}")
            return
        card.title_label.setText(f"新規則提案：{final_name}")
        card.mark_applied(undoable=False)
        self.rules_changed.emit()

    def _apply_bundle(self, card, scripts: list[Script], rules: list[Rule]) -> None:
        existing_scripts = set(self._storage.list_names())
        renamed_scripts = []
        script_names = {}
        for script in scripts:
            final_name = _numbered_name(script.name, existing_scripts)
            existing_scripts.add(final_name)
            script_names[script.name] = final_name
            renamed_scripts.append(dataclasses.replace(script, name=final_name))

        existing_rules = set(self._rule_storage.list_names())
        renamed_rules = []
        for rule in rules:
            data = rule_to_dict(rule)
            for trigger in data["triggers"]:
                if trigger.get("type") == "run_script":
                    trigger["script_name"] = script_names.get(
                        trigger.get("script_name"), trigger.get("script_name"))
            final_name = _numbered_name(rule.name, existing_rules)
            existing_rules.add(final_name)
            data["name"] = final_name
            renamed_rules.append(rule_from_dict(data))

        saved_scripts = []
        saved_rules = []
        try:
            for script in renamed_scripts:
                self._storage.save(script)
                saved_scripts.append(script.name)
            for rule in renamed_rules:
                self._rule_storage.save(rule)
                saved_rules.append(rule.name)
        except ScriptValidationError as exc:
            for name in reversed(saved_rules):
                try:
                    self._rule_storage.delete(name)
                except ScriptValidationError:
                    pass
            for name in reversed(saved_scripts):
                try:
                    self._storage.delete(name)
                except ScriptValidationError:
                    pass
            card.body_label.setText(f"套用失敗，已撤回本次變更：{exc}")
            return
        card.mark_applied(undoable=False)
        if renamed_scripts:
            self.scripts_changed.emit()
        if renamed_rules:
            self.rules_changed.emit()

    def _apply_edit(self, card, *, previous: Script, edited: Script) -> None:
        try:
            self._storage.save(edited)
        except ScriptValidationError as e:
            card.body_label.setText(f"套用失敗：{e}")
            return
        card.mark_applied(undoable=True)
        card.undo_button.clicked.connect(
            lambda: self._undo_edit(card, previous))
        self.scripts_changed.emit()

    def _undo_edit(self, card, previous: Script) -> None:
        try:
            self._storage.save(previous)
        except ScriptValidationError as e:
            card.body_label.setText(f"復原失敗：{e}")
            return
        card.undo_button.setEnabled(False)
        card.title_label.setText(card.title_label.text() + "（已復原）")
        self.scripts_changed.emit()

    def _discard_card(self, card) -> None:
        for b in (card.apply_button, card.discard_button):
            if b is not None:
                b.setEnabled(False)
        card.title_label.setText(card.title_label.text() + "　已捨棄")

    # ---------- AI 示範錄製 ----------

    _DEMO_STAGES = {
        "ai_initial": "AI 正在看你的示範、產生腳本…",
        "ai_retry": "AI 的提案格式不對，請它重新產生…",
        "return": "第 {round} 輪：回到示範起點…",
        "return_fix": "第 {round} 輪：沒回到起點，AI 正在修正回起點腳本…",
        "wait_reset": "等你把角色帶回起點…",
        "wait_rule": "監看規則正在處理（例如測謊），處理完再繼續試跑…",
        "running": "第 {round} 輪：試跑中（{stop} 可緊急停止）",
        "ai_fix": "第 {round} 輪：AI 正在比對示範與試跑結果…",
        "done": "試跑結束",
    }
    _DEMO_STATUS = {
        "success": "成功", "max_rounds": "跑滿輪數仍需修正", "stopped": "已停止",
        "interrupted": "被中斷", "user_ended": "已結束", "ai_failed": "AI 失敗",
    }

    def _on_demo_clicked(self) -> None:
        if self._demo is None or self._demo.active:
            return
        s = self._get_settings()
        if not s.ai_privacy_ack:
            if not self._confirm_privacy():
                return
            self._ack_privacy()
        self.demo_requested.emit()

    def _on_demo_active(self, active: bool) -> None:
        self.refresh_state()
        if not active:
            if self.demo_stop_button is not None:
                self.demo_stop_button.setEnabled(False)
            return
        card = _ProposalCard("AI 示範試跑", "準備中…")
        self.demo_status_label = card.body_label
        self.demo_stop_button = QPushButton("停止試跑")
        self.demo_stop_button.setProperty("variant", "ghost")
        self.demo_stop_button.clicked.connect(self._demo.stop)
        card._button_row.addWidget(self.demo_stop_button)
        self._demo_progress_card = self._add_card(card)

    def _on_demo_progress(self, event: dict) -> None:
        if self.demo_status_label is None:
            return
        template = self._DEMO_STAGES.get(event.get("stage"))
        if template:
            stop_key = getattr(self._get_settings(), "stop_key", "f10").upper()
            self.demo_status_label.setText(
                template.format(round=event.get("round", 0), stop=stop_key))

    def _on_demo_reset_needed(self, message: str) -> None:
        card = _ProposalCard("需要你協助", message)
        card.continue_button = QPushButton("已帶回起點，繼續")
        card.continue_button.setProperty("variant", "primary")
        card.end_button = QPushButton("結束")
        card.end_button.setProperty("variant", "ghost")

        def answer(proceed: bool) -> None:
            card.continue_button.setEnabled(False)
            card.end_button.setEnabled(False)
            self._demo.resume_after_reset(proceed)

        card.continue_button.clicked.connect(lambda: answer(True))
        card.end_button.clicked.connect(lambda: answer(False))
        card._button_row.addWidget(card.continue_button)
        card._button_row.addWidget(card.end_button)
        self._demo_reset_card = self._add_card(card)

    def _on_demo_finished(self, result) -> None:
        if self._demo_reset_card is not None:
            for b in (self._demo_reset_card.continue_button, self._demo_reset_card.end_button):
                b.setEnabled(False)
        status = self._DEMO_STATUS.get(result.status, result.status)
        lines = []
        if result.goal:
            lines.append(f"目的：{result.goal}")
        lines.append(result.message)
        for r in result.rounds:
            verdict = {"success": "一致", "needs_fix": "需修正"}.get(r.verdict, r.verdict or "")
            line = f"第 {r.round} 輪（第 {r.version} 版）：{verdict}"
            if r.changes:
                line += f"，{r.changes}"
            lines.append(line)
        card = _ProposalCard(f"示範試跑結果：{status}", "\n".join(lines))
        card.version_buttons = []
        session = getattr(self._demo, "session", None)
        last = max([result.library_version or 0, result.untested_version or 0,
                    *[r.version for r in result.rounds]])
        for version in range(1, last + 1):
            if version == result.untested_version:
                label = f"套用第 {version} 版（未試跑）"
            elif version == result.library_version:
                label = f"第 {version} 版（目前）"
            else:
                label = f"退回第 {version} 版"
            button = QPushButton(label)
            button.setProperty("variant", "ghost")
            button.clicked.connect(
                lambda _=False, v=version: self._apply_demo_version(card, session, v))
            card._button_row.addWidget(button)
            card.version_buttons.append(button)
        self._demo_summary_card = self._add_card(card)

    def _apply_demo_version(self, card, session, version: int) -> None:
        try:
            name = self._demo.apply_version(session, version)
        except Exception as exc:
            card.body_label.setText(card.body_label.text() + f"\n套用失敗：{exc}")
            return
        card.body_label.setText(card.body_label.text() + f"\n已將「{name}」改為第 {version} 版")
        self.scripts_changed.emit()
