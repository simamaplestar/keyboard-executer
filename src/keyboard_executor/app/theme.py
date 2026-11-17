"""深色主題（固定）：整個 app 的 Qt Stylesheet。

於 build_app 對 QApplication 套用，主視窗與所有對話框一致。
色彩語意（與主視窗重設計一致）：
  accent #4c9aff（選取/焦點/品牌）・run #3fb950（執行）・
  watch #d9a441（監看）・stop/danger #f0554b（停止/刪除）。
按鈕樣式以動態屬性 variant 區分（run/watch/stop/danger/ghost），
於 widget 端 setProperty("variant", ...) 指定。
"""
from __future__ import annotations

DARK_QSS = """
* {
    font-family: "Microsoft JhengHei", "Microsoft JhengHei UI", "PingFang TC", "Noto Sans TC", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog, QWidget { background: #0d1117; color: #e6edf3; }
QToolTip { background: #1b232d; color: #e6edf3; border: 1px solid #37434f; padding: 4px 7px; }

QLabel { background: transparent; color: #e6edf3; }
QLabel#wordmark { color: #93a1b0; font-weight: 600; letter-spacing: 2px; }
QLabel#wordmark[accentWord="true"] { color: #e6edf3; }
QLabel#keycap { background: #2f6bff; color: white; border-radius: 8px;
    font-weight: 700; font-size: 15px; }
QLabel#ver { color: #6b7987; border: 1px solid #28323e; border-radius: 6px; padding: 1px 6px;
    font-size: 11px; }
QLabel#estop { color: #f0554b; background: #3a1a18; border: 1px solid #7a2a25;
    border-radius: 999px; padding: 4px 12px; font-weight: 600; }
QLabel#moduleTitle { font-size: 15px; font-weight: 600; }
QLabel#moduleSub { color: #6b7987; font-size: 12px; }
QLabel#sectionLabel { color: #6b7987; font-size: 11px; font-weight: 600; }
QLabel#detail { color: #93a1b0; background: #10161d; border-radius: 8px; padding: 9px 12px; }
QLabel#modIcon { background: #16273e; color: #4c9aff; border-radius: 8px; }
QLabel#modIcon[kind="rules"] { background: #33290f; color: #d9a441; }

QFrame#titlebar { background: #161c24; border: none; border-bottom: 1px solid #28323e; }
QFrame#banner { background: #33290f; border: none; border-bottom: 1px solid #6b5316; }
QLabel#bannerText { color: #d9a441; background: transparent; }
QFrame#module, QFrame#console { background: #161c24; border: 1px solid #28323e; border-radius: 12px; }
QFrame#divider { background: #28323e; max-height: 1px; border: none; }

QPushButton {
    background: #1b232d; color: #e6edf3; border: 1px solid #28323e;
    border-radius: 8px; padding: 7px 13px; font-weight: 500;
}
QPushButton:hover { background: #222c37; border-color: #37434f; }
QPushButton:pressed { background: #12181f; }
QPushButton:focus { border-color: #4c9aff; }
QPushButton:disabled { color: #4a5765; background: #141a21; border-color: #222c37; }

QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: #93a1b0; }
QPushButton[variant="ghost"]:hover { background: #1b232d; color: #e6edf3; }

QPushButton[variant="danger"] { color: #f0554b; }
QPushButton[variant="danger"]:hover { background: #3a1a18; border-color: #7a2a25; }

QPushButton[variant="primary"] {
    background: #2f6bff; color: white; border: none; font-weight: 600; padding: 8px 18px;
}
QPushButton[variant="primary"]:hover { background: #4c8dff; }
QPushButton[variant="primary"]:pressed { background: #2559d8; }
QPushButton[variant="primary"]:disabled { background: #1e2f52; color: #6a7fa8; }

QPushButton[variant="run"] {
    background: #2ea043; color: white; border: none; font-weight: 600; padding: 8px 18px;
}
QPushButton[variant="run"]:hover { background: #3fb950; }
QPushButton[variant="run"]:pressed { background: #268139; }
QPushButton[variant="run"]:disabled { background: #1c3325; color: #5f8069; }

QPushButton[variant="watch"] {
    background: #b7791f; color: white; border: none; font-weight: 600; padding: 8px 18px;
}
QPushButton[variant="watch"]:hover { background: #d9a441; }
QPushButton[variant="watch"]:pressed { background: #9c6716; }
QPushButton[variant="watch"]:disabled { background: #33290f; color: #7a6a3f; }

QListWidget {
    background: #10161d; border: 1px solid #28323e; border-radius: 8px;
    padding: 4px; outline: none;
}
QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #e6edf3; margin: 1px 0; }
QListWidget::item:hover { background: #1b232d; }
QListWidget::item:selected { background: #17324e; color: #ffffff; }

QPlainTextEdit#logView {
    background: #0b0f14; color: #cdd7e1; border: 1px solid #28323e; border-radius: 8px;
    font-size: 12px; padding: 8px; selection-background-color: #17324e;
}

/* 腳本編輯器：按鍵串（keycap chips，可拖曳/縮放/多選組迴圈） */
QScrollArea#flowScroll { background: #0b0f14; border: 1px solid #28323e; border-radius: 10px; }
QWidget#flowInner { background: transparent; }

/* chip 一律 2px 邊框：選取時只換顏色、盒子大小不變（避免拖曳/選取後原地變大） */
QFrame#chip { border-radius: 10px; }
QFrame#chip[kind="key"], QFrame#chip[kind="click"] {
    background: #4a0f1a; border: 2px solid #7a1f2c;
}
QFrame#chip[kind="key"]:hover, QFrame#chip[kind="click"]:hover { border-color: #b0303f; }
QFrame#chip[kind="delay"] { background: #10171f; border: 2px dashed #45525f; }
QFrame#chip[kind="delay"]:hover { border-color: #5a6b7a; }
QFrame#chip[kind="other"] { background: #1b232d; border: 2px solid #37434f; }
QFrame#chip[kind="other"]:hover { border-color: #55636f; }
QFrame#chip[kind="loop"] { background: #16233a; border: 2px solid #2f5488; }
QFrame#chip[kind="loop"]:hover { border-color: #4c7fc0; }
QFrame#chip[selected="true"] { border: 2px solid #4c9aff; }

QFrame#loopAddChip { background: transparent; border: 2px dashed #37434f; border-radius: 10px; }
QFrame#loopAddChip:hover { border-color: #4c9aff; }
QFrame#loopAddChip QLabel#chipMain, QFrame#loopAddChip QLabel#chipSub { color: #6b7987; }

/* 迴圈外框：藍框包住「完整 chip」，抬頭寫重複次數（chip 之間 → 連接） */
QLabel#loopHeader { background: transparent; color: #9cc2ff; letter-spacing: 1px; }
QLabel#chipArrow { background: transparent; color: #6b7f9c; }

QLabel#chipMain { background: transparent; color: #f3d6da; }
QLabel#chipIndex { background: transparent; color: #7f8c99; }
QFrame#chip[kind="delay"] QLabel#chipMain,
QFrame#chip[kind="other"] QLabel#chipMain { color: #e6edf3; }
QFrame#chip[kind="loop"] QLabel#chipMain { color: #cfe0ff; }
QLabel#chipSub { background: transparent; color: #c39aa0; }
QFrame#chip[kind="delay"] QLabel#chipSub,
QFrame#chip[kind="other"] QLabel#chipSub,
QFrame#chip[kind="loop"] QLabel#chipSub { color: #93a1b0; }

QPushButton#chipAdd {
    background: transparent; color: #6b7987; border: 1px dashed #37434f;
    border-radius: 10px; padding: 12px 18px; font-size: 16px; font-weight: 700;
}
QPushButton#chipAdd:hover { color: #4c9aff; border-color: #4c9aff; }

QPushButton#zoomBtn {
    background: #1b232d; color: #e6edf3; border: 1px solid #37434f;
    border-radius: 6px; padding: 2px 10px; font-weight: 700; min-width: 18px;
}
QPushButton#zoomBtn:hover { background: #222c37; border-color: #55636f; }
QLabel#zoomLabel { color: #93a1b0; min-width: 42px; }

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {
    background: #10161d; color: #e6edf3; border: 1px solid #28323e;
    border-radius: 6px; padding: 5px 8px; selection-background-color: #17324e;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #4c9aff;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #161c24; color: #e6edf3; border: 1px solid #37434f;
    selection-background-color: #17324e; outline: none;
}
QCheckBox, QRadioButton { color: #e6edf3; spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #10161d; border: 1px solid #37434f; border-radius: 4px; }
QCheckBox::indicator:checked { background: #2f6bff; border: 1px solid #2f6bff; border-radius: 4px; }

QTableWidget, QTableView, QTreeWidget {
    background: #10161d; color: #e6edf3; border: 1px solid #28323e; border-radius: 8px;
    gridline-color: #28323e; outline: none;
}
QHeaderView::section {
    background: #1b232d; color: #93a1b0; border: none; border-bottom: 1px solid #28323e;
    padding: 6px 8px;
}
QTableWidget::item:selected, QTableView::item:selected { background: #17324e; color: #ffffff; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #28323e; border-radius: 5px; min-height: 26px; }
QScrollBar::handle:vertical:hover { background: #37434f; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: #28323e; border-radius: 5px; min-width: 26px; }
QScrollBar::handle:horizontal:hover { background: #37434f; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu { background: #161c24; color: #e6edf3; border: 1px solid #37434f; }
QMenu::item:selected { background: #17324e; }

QLabel#aiBubbleUser {
    background: #17324e; color: #e6edf3; border-radius: 10px; padding: 8px 10px;
}
QLabel#aiBubbleAssistant {
    background: #1b232d; color: #e6edf3; border-radius: 10px; padding: 8px 10px;
}
QFrame#aiAttachmentTray, QFrame#aiSentImages {
    background: #10161d; border: 1px solid #28323e; border-radius: 9px;
}
QFrame#aiAttachmentChip {
    background: #161c24; border: 1px solid #37434f; border-radius: 8px;
}
QLabel#aiAttachmentPreview { background: transparent; min-width: 64px; min-height: 64px; }
QLabel#aiAttachmentName { color: #93a1b0; background: transparent; font-size: 10px; }
QPushButton#aiUploadButton { padding: 7px 10px; }
QFrame#aiProposalCard {
    background: #161c24; border: 1px solid #37434f; border-radius: 10px;
}
QLabel#aiCardTitle { color: #4c9aff; font-weight: 600; }
QLabel#aiCardError { color: #ff6b6b; }

/* AI 助手 dock：自訂標題列取代原生標題（原生的浮動/關閉鈕無法跟著深色主題走，
   會顯示成突兀的淺色系統控件），故此處不再需要 QDockWidget::title 規則。 */
QFrame#aiTitleBar { background: #161c24; border: none; border-bottom: 1px solid #28323e; }
QLabel#aiTitleWord { color: #e6edf3; font-weight: 600; letter-spacing: 1px; }
QPushButton#aiTitleClose {
    background: transparent; border: none; color: #6b7987;
    border-radius: 6px; padding: 0; font-size: 14px; font-weight: 700;
}
QPushButton#aiTitleClose:hover { background: #2a333f; color: #e6edf3; }

/* AI 助手：無對話時的空狀態引導 */
QLabel#aiEmptyMark { color: #4c9aff; font-size: 26px; }
QLabel#aiEmptyText { color: #93a1b0; }
QPushButton#aiExampleChip {
    background: transparent; color: #9cc2ff; border: 1px dashed #37434f;
    border-radius: 999px; padding: 7px 14px;
}
QPushButton#aiExampleChip:hover { border-color: #4c9aff; background: #16273e; }
"""
