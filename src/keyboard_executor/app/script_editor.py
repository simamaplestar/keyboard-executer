"""腳本步驟編輯器（spec §9）：以「自由畫布」呈現動作序列——每個動作是一張可用滑鼠
自由拖動到任意位置的 keycap，執行順序由位置決定（由上到下、由左到右），相鄰動作間以
自動繪製的箭頭連線表示先後。迴圈以「容器盒」顯示，盒內直接列出內含動作的小 keycap。

薄件：狀態與驗證在 ScriptEditorModel／action_fields；本檔只做畫布重繪、位置管理與按鈕
接線。動作類型／欄位／選項一律以繁中顯示。支援自由拖動排序、Ctrl＋滾輪或工具列縮放、
Ctrl/Shift 多選框選組成迴圈、「自動排列」一鍵把散亂的節點排整齊。
"""
from __future__ import annotations

import sys

import json
import math
import re

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keyboard_executor.app.action_fields import (
    FIELD_SPECS,
    action_type_label,
    choice_label,
    field_label,
    to_action_dict,
)
from keyboard_executor.app.key_capture import (  # noqa: F401 (re-export for tests)
    _KeyCaptureEdit,
    _qt_key_to_name,
)
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.core.models import (
    ScriptValidationError, action_from_dict, action_label, action_to_dict,
)

_BUTTON_EN = {"left": "Left", "right": "Right", "middle": "Middle"}
_ZOOM_MIN, _ZOOM_MAX = 0.6, 1.8


def _chip_spec(d: dict) -> tuple[str, str, str]:
    """action dict → (主標籤, 副標籤, 種類 key/click/delay/loop/other)。副標籤顯示
    按住時間／點擊次數／延遲長度等重點，讓每個 chip 一眼看懂在做什麼。
    有名稱時主行改顯示名稱，原本內容併到副行（如「回城」／「按鍵 N」）。"""
    main, sub, kind = _base_chip_spec(d)
    name = d.get("name")
    if not name:
        return main, sub, kind
    if d["type"] == "minimap_move":
        return name, sub, kind               # 副行已含動作與座標
    if d["type"] in ("key_press", "key_combo"):
        main = f"按鍵 {main}"
    return name, (f"{main}・{sub}" if sub else main), kind


def _base_chip_spec(d: dict) -> tuple[str, str, str]:
    t = d["type"]
    if t == "goto":
        return f"跳到 #{d.get('goto_index', '?')}", "跳到動作", "other"
    if t == "key_press":
        hold = d.get("hold_ms", 0)
        return str(d.get("key", "?")).upper(), (f"按住 {hold}ms" if hold else "按一下"), "key"
    if t == "key_combo":
        hold = d.get("hold_ms", 0)
        keys = "+".join(str(k).upper() for k in d.get("keys", []))
        return keys, (f"組合鍵，按住 {hold}ms" if hold else "組合鍵"), "key"
    if t == "text_input":
        s = d.get("text", "")
        return (f"「{s[:6]}…」" if len(s) > 6 else f"「{s}」") if s else "文字", "輸入文字", "key"
    if t == "mouse_click":
        cnt = d.get("count", 1)
        return _BUTTON_EN.get(d.get("button", "left"), "Left"), (f"連點 ×{cnt}" if cnt > 1 else "點一下"), "click"
    if t == "mouse_move":
        return "移動", f"→ ({d.get('x', 0)}, {d.get('y', 0)})", "click"
    if t == "mouse_drag":
        return "拖曳", "滑鼠拖曳", "click"
    if t == "scroll":
        return "捲動", f"dx {d.get('dx', 0)} dy {d.get('dy', 0)}", "click"
    if t == "delay":
        ms = d.get("ms", 0)
        if isinstance(ms, list):
            return "延遲", f"{ms[0]}–{ms[1]} ms", "delay"
        return "延遲", (f"{ms / 1000:.1f} 秒" if ms >= 1000 else f"{ms} 毫秒"), "delay"
    if t == "loop":
        cnt = d.get("count", 1)
        n = len(d.get("actions", []))
        return "迴圈", (f"無限・{n} 個動作" if cnt == -1 else f"×{cnt}・{n} 個動作"), "loop"
    if t == "minimap_move":
        method = d.get("method", "walk")
        verb = {"walk": "走到", "rope": "爬繩到", "down_jump": "下跳到",
                "hold": "按住衝到"}.get(method, "走到")
        x, y = (d.get("target") or [0, 0])[:2]
        sub = f"{verb} ({x}, {y}) ±{d.get('tolerance', 1)}"
        if d.get("path_key"):
            sub += f"・沿路 {str(d['path_key']).upper()}"
        return verb + "小地圖", sub, "other"
    return action_type_label(t), "", "other"


def order_from_positions(positions, band: int = 70) -> list[int]:
    """畫布位置 → 執行順序（回傳排序後的舊索引）。這是「位置決定順序」的核心規則。

    positions 為 [(x, y), ...]，y 最好是節點的垂直中心。由上往下分列：跟該列第一個
    節點中心相差不到半個 band 的算同一列；列與列由上到下、同一列內由左到右。
    不用固定格線（y // band）切列：同一列只差幾像素卻剛好跨過格線，順序就會忽前忽後。"""
    half = max(1, int(band)) / 2
    rows: list[list[int]] = []
    anchor = None
    for i in sorted(range(len(positions)), key=lambda i: (positions[i][1], positions[i][0])):
        if anchor is None or positions[i][1] - anchor > half:
            rows.append([])
            anchor = positions[i][1]
        rows[-1].append(i)
    return [i for row in rows for i in sorted(row, key=lambda i: positions[i][0])]


def even_layout(sizes, max_width: int, gap: int, start: int = 14) -> list[tuple[int, int]]:
    """把一串節點以「等間隔」由左到右排、超過寬度就換列。sizes 為 [(w, h), ...]，
    回傳每個節點左上角 (x, y)。相鄰間隔一律 = gap（依實際寬度校正）；同一列的節點
    「垂直置中」對齊到該列中線——高矮不一（如迴圈框較高）時中心 y 才一致，箭頭不歪。"""
    # 先分列，記下每個節點的 (索引, 寬, 高, x)
    rows: list[list[tuple]] = []
    row: list[tuple] = []
    x = start
    for i, (w, h) in enumerate(sizes):
        if x > start and x + w > start + max_width and row:
            rows.append(row)
            row = []
            x = start
        row.append((i, w, h, x))
        x += w + gap
    if row:
        rows.append(row)
    # 每列以列中最高者為列高，各節點垂直置中
    out: list[tuple[int, int]] = [(start, start)] * len(sizes)
    y = start
    for r in rows:
        row_h = max(h for (_i, _w, h, _x) in r)
        for i, _w, h, cx in r:
            out[i] = (cx, y + (row_h - h) // 2)
        y += row_h + gap
    return out


def wrap_rows(widths: list[int], max_width: int, gap: int) -> list[list[int]]:
    """把 widths（各元素寬度）依 max_width 切成多列，回傳每列的索引清單。
    單一元素超過 max_width 時自成一列（不硬切）。"""
    rows: list[list[int]] = []
    cur: list[int] = []
    cur_w = 0
    for i, w in enumerate(widths):
        if cur and cur_w + gap + w > max_width:
            rows.append(cur)
            cur, cur_w = [], 0
        cur_w += (gap if cur else 0) + w
        cur.append(i)
    if cur:
        rows.append(cur)
    return rows


def _edge_point(rect, toward: QPoint) -> QPoint:
    """rect 中心朝 toward 方向、落在 rect 邊界上的點（給箭頭連線接在邊緣、天然垂直置中）。"""
    c = rect.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return c
    hw, hh = rect.width() / 2.0, rect.height() / 2.0
    scale = float("inf")
    if dx:
        scale = min(scale, hw / abs(dx))
    if dy:
        scale = min(scale, hh / abs(dy))
    return QPoint(int(c.x() + dx * scale), int(c.y() + dy * scale))


def _arrow_head(painter: QPainter, p_from: QPoint, p_to: QPoint) -> None:
    """在 p_to 依 p_from→p_to 的方向畫箭頭。"""
    ang = math.atan2(p_to.y() - p_from.y(), p_to.x() - p_from.x())
    size = 9
    for da in (math.radians(150), math.radians(-150)):
        bx = p_to.x() + size * math.cos(ang + da)
        by = p_to.y() + size * math.sin(ang + da)
        painter.drawLine(p_to, QPoint(int(bx), int(by)))


def _connector_points(a, b) -> list[QPoint]:
    """兩個 chip 幾何 → 連接折線的頂點，從 a 的右連接點接到 b 的左連接點。
    同列往右：同高＝直線，不同高（例如迴圈框接小節點）＝在兩者中間轉直角。
    下一個在「左又下」（換行）則走列間空隙的直角折線，避免長對角線被 chip 蓋住。"""
    pa = QPoint(a.x() + a.width(), a.y() + a.height() // 2)    # 與節點 out_port 相同
    pb = QPoint(b.x(), b.y() + b.height() // 2)                 # 與節點 in_port 相同
    if pb.x() >= pa.x():
        if pa.y() == pb.y():
            return [pa, pb]
        mx = (pa.x() + pb.x()) // 2
        return [pa, QPoint(mx, pa.y()), QPoint(mx, pb.y()), pb]
    # 橫線走「目的列上方」的列間空隙，而非兩節點的中點——中點可能落在來源列裡較高的
    # 迴圈框帶內、使橫線被迴圈框蓋住；目的列在來源列（含迴圈框）下方，故其上方即空隙。
    gap_y = b.top() - 14
    if gap_y <= a.bottom():
        gap_y = a.bottom() + 14
    out_x, in_x = pa.x() + 12, pb.x() - 12
    return [pa, QPoint(out_x, pa.y()), QPoint(out_x, gap_y),
            QPoint(in_x, gap_y), QPoint(in_x, pb.y()), pb]


def _draw_connector(painter: QPainter, a, b) -> None:
    pts = _connector_points(a, b)
    for i in range(len(pts) - 1):
        painter.drawLine(pts[i], pts[i + 1])
    _arrow_head(painter, pts[-2], pts[-1])


_PORT_R = 5          # 連接點半徑
_PORT_INSET = 0      # 連接點中心落在節點左右邊框上（圓點被邊框切一半）
_PORT_HIT = 12       # 按到連接點的容許距離（曼哈頓距離）


class _DraggableNode(QFrame):
    """畫布上可自由拖動、單擊選取、雙擊編輯的節點基底。拖動時即時 move 自己並發 moved，
    放開後發 dropped 讓外層依位置重排。"""

    clicked = Signal(int)
    doubleClicked = Signal(int)
    movedBy = Signal(int, object)           # (index, 這次位移量 QPoint) 供整組一起拖
    dropped = Signal(int)
    menuRequested = Signal(int, object)     # (index, 全域座標) 供右鍵選單
    linkDragged = Signal(int, object)       # (index, 畫布座標) 從右側連接點拉線中
    linkDropped = Signal(int, object)       # (index, 畫布座標) 放開＝連到該處的動作

    def __init__(self, index: int, kind: str):
        super().__init__()
        self.index = index
        self.setObjectName("chip")
        self.setProperty("kind", kind)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMouseTracking(True)
        self._press = None
        self._dragging = False
        self._linking = False

    def inner_count(self) -> int:
        return 0

    def out_port(self) -> QPoint:
        """右側「連出」圓點（節點座標）。中心在右邊框上：節點內畫內半圓，畫布畫外半圓。"""
        return QPoint(self.width() - _PORT_INSET, self.height() // 2)

    def in_port(self) -> QPoint:
        return QPoint(_PORT_INSET, self.height() // 2)

    def on_out_port(self, point: QPoint) -> bool:
        return (point - self.out_port()).manhattanLength() <= _PORT_HIT

    def paintEvent(self, event):   # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#54708f"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(self.in_port(), _PORT_R, _PORT_R)
        painter.setBrush(QColor("#54708f"))
        painter.drawEllipse(self.out_port(), _PORT_R, _PORT_R)

    def mousePressEvent(self, event):   # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and self.on_out_port(event.position().toPoint())):
            self._linking = True
            self.clicked.emit(self.index)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._dragging = False
            self.raise_()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):   # noqa: N802
        point = event.position().toPoint()
        if self._linking:
            self.linkDragged.emit(self.index, self.mapToParent(point))
            return
        if not event.buttons():
            self.setCursor(Qt.CursorShape.CrossCursor if self.on_out_port(point)
                           else Qt.CursorShape.OpenHandCursor)
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self._dragging and (event.position().toPoint() - self._press).manhattanLength() < 6:
            return
        self._dragging = True
        target = self.mapToParent(event.position().toPoint()) - self._press
        target.setX(max(0, target.x()))
        target.setY(max(0, target.y()))
        delta = target - self.pos()
        if delta.isNull():
            return
        self.move(target)
        self.movedBy.emit(self.index, delta)

    def mouseReleaseEvent(self, event):   # noqa: N802
        if self._linking:
            self._linking = False
            self.linkDropped.emit(self.index, self.mapToParent(event.position().toPoint()))
            event.accept()
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        was_drag = self._dragging
        self._dragging = False
        self._press = None
        if was_drag:
            self.dropped.emit(self.index)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):   # noqa: N802
        self.doubleClicked.emit(self.index)

    def contextMenuEvent(self, event):   # noqa: N802
        self.menuRequested.emit(self.index, event.globalPos())
        event.accept()


def _fill_keycap(frame: QFrame, main: str, sub: str, zoom: float,
                 number: int | None = None) -> None:
    """在 frame 內鋪好雙行 keycap 內容（主行按鍵、副行說明）。供完整 chip 與迴圈框內
    的內含 chip 共用，確保迴圈框內是「完整 chip」而非縮小顯示。
    number＝動作序號（從 0 起算，與「跳到動作 #N」及紀錄相同），顯示在最上方。"""
    pad_h, pad_v = int(15 * zoom), int(9 * zoom)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
    lay.setSpacing(int(2 * zoom))
    if number is not None:
        badge = QLabel(f"#{number}")
        badge.setObjectName("chipIndex")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bf = badge.font()
        bf.setPointSizeF(max(6.5, 8.0 * zoom))
        badge.setFont(bf)
        lay.addWidget(badge)
    main_label = QLabel(main)
    main_label.setObjectName("chipMain")
    main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    f = main_label.font()
    f.setPointSizeF(max(8.0, 11.0 * zoom))
    f.setBold(True)
    main_label.setFont(f)
    lay.addWidget(main_label)
    if sub:
        sub_label = QLabel(sub)
        sub_label.setObjectName("chipSub")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf = sub_label.font()
        sf.setPointSizeF(max(6.5, 8.5 * zoom))
        sub_label.setFont(sf)
        lay.addWidget(sub_label)


class _InnerChip(QFrame):
    """迴圈框內的「完整」動作 chip；雙擊即可編輯該動作（免先解散迴圈）。外觀與畫布上
    的一般 chip 一致。"""

    doubleClicked = Signal(int)      # 迴圈內索引

    def __init__(self, inner_index: int, action: dict, zoom: float = 1.0):
        super().__init__()
        self._inner_index = inner_index
        self.setObjectName("chip")
        main, sub, kind = _chip_spec(action)
        self.setProperty("kind", kind)
        _fill_keycap(self, main, sub, zoom, number=inner_index)
        self.setToolTip(action_type_label(action["type"]) + "（雙擊編輯）")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):   # noqa: N802
        self.doubleClicked.emit(self._inner_index)
        event.accept()


def _arrow_label(zoom: float) -> QLabel:
    arrow = QLabel("→")
    arrow.setObjectName("chipArrow")
    arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
    af = arrow.font()
    af.setPointSizeF(max(9.0, 12.0 * zoom))
    af.setBold(True)
    arrow.setFont(af)
    return arrow


class _InnerAddChip(QFrame):
    """迴圈框內末端的「＋ 新增」方塊：單擊 → 在該迴圈末尾新增動作。"""

    clicked = Signal()

    def __init__(self, zoom: float = 1.0):
        super().__init__()
        self.setObjectName("loopAddChip")     # 與一般 chip（objectName "chip"）區隔
        _fill_keycap(self, "＋", "新增", zoom)
        self.setToolTip("在這個迴圈末尾新增動作")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):   # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class _ActionChip(_DraggableNode):
    """單一動作的雙行 keycap（主行按鍵、副行按住/點擊等說明）。"""

    def __init__(self, index: int, main: str, sub: str, kind: str, zoom: float = 1.0):
        super().__init__(index, kind)
        _fill_keycap(self, main, sub, zoom, number=index)
        self.adjustSize()


_LOOP_MAX_ROW_WIDTH = 520      # 迴圈內含動作換列的最大列寬（px，隨 zoom 縮放）


class _LoopGroup(_DraggableNode):
    """迴圈外框：把要重複的動作以「完整 chip」原樣排出來，外面包一圈藍框、抬頭寫
    「迴圈 ×N」。不縮小、不簡化；整框當一個單位拖動。雙擊框內動作可直接編輯；雙擊
    外框（抬頭/空白）則改重複次數。"""

    innerDoubleClicked = Signal(int, int)    # (迴圈索引, 迴圈內索引)
    addClicked = Signal(int)                  # 迴圈索引（末端「＋新增」被點）

    def __init__(self, index: int, action: dict, zoom: float = 1.0):
        super().__init__(index, "loop")
        self._inner = action.get("actions", [])
        count = action.get("count", 1)
        pad = int(11 * zoom)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, int(7 * zoom), pad, pad)
        outer.setSpacing(int(7 * zoom))
        title = f"{action['name']}　迴圈" if action.get("name") else "迴圈"
        header = QLabel(f"#{index}　" + title + "　"
                        + ("無限重複" if count == -1 else f"重複 ×{count}"))
        header.setObjectName("loopHeader")
        hf = header.font()
        hf.setPointSizeF(max(8.0, 10.5 * zoom))
        hf.setBold(True)
        header.setFont(hf)
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)

        # 內含動作 chip ＋ 末端「＋ 新增」chip
        chips: list[QFrame] = []
        for j, a in enumerate(self._inner):
            chip = _InnerChip(j, a, zoom)
            chip.doubleClicked.connect(
                lambda ii: self.innerDoubleClicked.emit(self.index, ii))
            chips.append(chip)
        add_chip = _InnerAddChip(zoom)
        add_chip.clicked.connect(lambda: self.addClicked.emit(self.index))
        chips.append(add_chip)

        # 依最大列寬換行；列內保留 → 箭頭、跨列不畫
        gap = int(7 * zoom)
        arrow_w = int(22 * zoom)      # 箭頭＋間距佔位，估算換列用
        widths = [c.sizeHint().width() for c in chips]
        rows = wrap_rows(widths, int(_LOOP_MAX_ROW_WIDTH * zoom), gap + arrow_w)
        rows_lay = QVBoxLayout()
        rows_lay.setSpacing(gap)
        for row_idx in rows:
            row = QHBoxLayout()
            row.setSpacing(gap)
            row.setContentsMargins(0, 0, 0, 0)
            for pos, ci in enumerate(row_idx):
                if pos > 0:
                    row.addWidget(_arrow_label(zoom))
                row.addWidget(chips[ci])
            row.addStretch(1)
            rows_lay.addLayout(row)
        outer.addLayout(rows_lay)
        self.setToolTip("迴圈：外框內為重複執行的動作（雙擊改次數、雙擊動作可編輯、＋新增動作）")
        self.adjustSize()

    def inner_count(self) -> int:
        return len(self._inner)


class _ChipCanvas(QWidget):
    """自由畫布：子節點以絕對座標擺放；paintEvent 依節點順序畫箭頭連線；Ctrl＋滾輪縮放。"""

    zoomRequested = Signal(int)       # +1 放大 / -1 縮小
    rubberSelected = Signal(list)     # 框選命中的動作索引清單
    menuRequested = Signal(object)    # 空白處右鍵：全域座標
    linkDragged = Signal(int, object)  # 從連接點外半圓拉線（節點自己收不到這一半的滑鼠）
    linkDropped = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("flowInner")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._nodes = []
        self._band_origin = None
        self._band_rect = None
        self._link = None            # (起點, 終點) 手動連線拉線中
        self.manual_links: set[int] = set()   # 畫成橘色的手動連接
        self._link_src = None        # 從畫布這側（外半圓）開始拉線的節點索引
        self.setMouseTracking(True)

    def set_link(self, start, end):
        self._link = None if start is None else (QPoint(start), QPoint(end))
        self.update()

    def node_at(self, point: QPoint, exclude: int = -1):
        """畫布座標上的節點索引；沒有則回 None。"""
        for n in reversed(self._nodes):
            if n.index != exclude and n.geometry().contains(point):
                return n.index
        return None

    def clear(self):
        for n in self._nodes:
            n.setParent(None)
            n.deleteLater()
        self._nodes = []

    def nodes_in_rect(self, rect: QRect) -> list:
        """幾何與 rect 相交的節點索引（排序）；供框選判定。"""
        return sorted(n.index for n in self._nodes if rect.intersects(n.geometry()))

    # -- 空白處左鍵拖曳＝框選（rubber band） --

    def _out_port_at(self, point: QPoint):
        for n in reversed(self._nodes):
            if (point - n.mapToParent(n.out_port())).manhattanLength() <= _PORT_HIT:
                return n.index
        return None

    def mousePressEvent(self, event):   # noqa: N802
        point = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton and self._out_port_at(point) is not None:
            self._link_src = self._out_port_at(point)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._band_origin = point
            self._band_rect = QRect(self._band_origin, QSize())
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):   # noqa: N802
        if self._link_src is not None:
            self.linkDragged.emit(self._link_src, event.position().toPoint())
            return
        if not event.buttons():
            self.setCursor(Qt.CursorShape.CrossCursor
                           if self._out_port_at(event.position().toPoint()) is not None
                           else Qt.CursorShape.ArrowCursor)
        if self._band_origin is not None:
            self._band_rect = QRect(self._band_origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):   # noqa: N802
        if self._link_src is not None:
            src, self._link_src = self._link_src, None
            self.linkDropped.emit(src, event.position().toPoint())
            return
        if self._band_origin is not None:
            rect = self._band_rect
            picked = self.nodes_in_rect(rect) if rect is not None else []
            self._band_origin = None
            self._band_rect = None
            self.update()
            self.rubberSelected.emit(picked)     # 空框＝點空白處＝取消選取
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):   # noqa: N802
        self.menuRequested.emit(event.globalPos())
        event.accept()

    def add_node(self, node):
        node.setParent(self)
        node.show()
        self._nodes.append(node)

    def set_bounds(self):
        """把畫布 minimumSize 撐到涵蓋所有節點，超出視窗時才會出現捲軸。"""
        if not self._nodes:
            self.setMinimumSize(0, 0)
            return
        maxx = max(n.x() + n.sizeHint().width() for n in self._nodes) + 24
        maxy = max(n.y() + n.sizeHint().height() for n in self._nodes) + 24
        self.setMinimumSize(maxx, maxy)

    def wheelEvent(self, event):   # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomRequested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            event.ignore()   # 交給外層 QScrollArea 捲動

    def paintEvent(self, event):   # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if len(self._nodes) >= 2:
            pen = QPen(QColor("#54708f"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QColor("#54708f"))
            manual = QPen(QColor("#e8912d"))
            manual.setWidth(3)
            for i in range(len(self._nodes) - 1):
                if i in self.manual_links:
                    painter.setPen(manual)
                    painter.setBrush(QColor("#e8912d"))
                else:
                    painter.setPen(pen)
                    painter.setBrush(QColor("#54708f"))
                _draw_connector(painter, self._nodes[i].geometry(),
                                self._nodes[i + 1].geometry())
        # 連接點外半圓（內半圓由節點自己畫在邊框內，合起來是一個被邊框切半的圓點）
        painter.setPen(QPen(QColor("#54708f"), 2))
        for n in self._nodes:
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(n.mapToParent(n.in_port()), _PORT_R, _PORT_R)
            painter.setBrush(QColor("#54708f"))
            painter.drawEllipse(n.mapToParent(n.out_port()), _PORT_R, _PORT_R)
        if self._link is not None:
            painter.setPen(QPen(QColor("#e8912d"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(*self._link)
        if self._band_rect is not None and not self._band_rect.isNull():
            painter.setPen(QPen(QColor("#4c9aff"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(76, 154, 255, 45))
            painter.drawRect(self._band_rect)


# 這些動作的 x/y 是一組座標，給一顆「一次填兩格」的取點鈕（mouse_drag 的
# from/to 是 point 型別，各自在同列右側有自己的鈕）。
_XY_PICK_TYPES = {"mouse_click", "mouse_move", "scroll"}


_GOTO_FIELDS = ("goto_index", "otherwise_index")


def goto_choices_for(actions: list[dict]) -> list[str]:
    """同一層動作清單 → 下拉選單文字（不含 #序號，由 _goto_combo 加上）。"""
    labels = []
    for d in actions:
        try:
            label = action_label(action_from_dict(d))
        except ScriptValidationError:
            label = action_type_label(d.get("type", ""))
        labels.append(label if len(label) <= 32 else label[:31] + "…")
    return labels


def _goto_combo(choices: list[str], current) -> QComboBox:
    """「跳到動作」下拉：#序號＋名稱，userData 是序號字串（空＝未設定）。"""
    box = QComboBox()
    box.addItem("（未設定）", "")
    for i, label in enumerate(choices):
        box.addItem(f"#{i}　{label}", str(i))
    if isinstance(current, int) and not isinstance(current, bool):
        found = box.findData(str(current))
        if found < 0:                      # 指向清單外（例如已刪除的動作）：保留原值
            box.addItem(f"#{current}　（不存在的動作）", str(current))
            found = box.count() - 1
        box.setCurrentIndex(found)
    return box


class _BranchesEdit(QWidget):
    """「依小地圖位置跳轉」的區域對應：每列一個區域＋要跳到的動作，不用手打 JSON。
    text() 回傳 JSON 字串，與原本的欄位格式相容。"""

    def __init__(self, form, branches: list, goto_choices: list[str] | None):
        super().__init__()
        self._form = form
        self._choices = goto_choices
        self._rows: list[tuple] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._rows_layout = QVBoxLayout()
        outer.addLayout(self._rows_layout)
        add = QPushButton("＋ 新增區域")
        add.clicked.connect(lambda: self.add_row())
        outer.addWidget(add)
        for branch in branches if isinstance(branches, list) else []:
            if isinstance(branch, dict):
                self.add_row(branch.get("area"), branch.get("goto_index"))
        if not self._rows:
            self.add_row()

    def add_row(self, area=None, goto=None) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        area_edit = QLineEdit(", ".join(str(v) for v in area) if isinstance(area, list) else "")
        area_edit.setPlaceholderText("x, y, 寬, 高（視窗相對）")
        area_edit.setMinimumWidth(150)
        pick = QPushButton("框選")
        pick.setToolTip("在畫面上拖曳框出小地圖上的區域")
        pick.clicked.connect(lambda: self._form.pick_region_into(area_edit, "區域"))
        here = QPushButton("人物位置")
        here.setToolTip("以人物目前在小地圖的位置建立區域（左右各 30、上下各 3）")
        here.clicked.connect(lambda: self._fill_from_dot(area_edit))
        if self._choices is not None:
            target = _goto_combo(self._choices, goto)
        else:
            target = QSpinBox()
            target.setRange(0, 99999)
            target.setPrefix("跳到 #")
            if isinstance(goto, int):
                target.setValue(goto)
        remove = QPushButton("刪除")
        entry = (row, area_edit, target)
        remove.clicked.connect(lambda: self._remove(entry))
        if isinstance(target, QComboBox):
            target.setMinimumContentsLength(16)
            target.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        lay.addWidget(area_edit, 1)
        lay.addWidget(pick)
        lay.addWidget(here)
        lay.addWidget(QLabel("→"))
        lay.addWidget(target, 1)
        lay.addWidget(remove)
        self._rows_layout.addWidget(row)
        self._rows.append(entry)

    def _remove(self, entry) -> None:
        if entry in self._rows:
            self._rows.remove(entry)
            entry[0].setParent(None)
            entry[0].deleteLater()

    def _fill_from_dot(self, area_edit) -> None:
        dot = self._form.read_player_dot()
        if dot is not None:
            x, y = dot
            area_edit.setText(f"{x - 30}, {y - 3}, 60, 7")
            self._form.pick_status.setText(f"已用人物位置 ({x}, {y}) 建立區域")

    def text(self) -> str:
        from keyboard_executor.app.action_fields import parse_int_list
        branches = []
        for _, area_edit, target in self._rows:
            raw = area_edit.text().strip()
            if not raw:
                continue
            try:
                area = parse_int_list("area", raw, 4)
            except ScriptValidationError:
                area = raw                 # 交給動作驗證顯示錯誤訊息
            goto = (target.currentData() if isinstance(target, QComboBox)
                    else str(target.value()))
            branches.append({"area": area, "goto_index": int(goto) if goto else None})
        return json.dumps(branches, ensure_ascii=False)


class ActionForm(QDialog):
    """依 FIELD_SPECS 宣告式產生欄位的通用動作表單（欄位名與選項皆繁中）。

    座標欄位可用取點覆蓋層在畫面上直接選（見 point_picker）：動作存的是視窗相對
    座標，使用者無從目測，故取點器負責換算並回填。需要目標視窗才能換算，由
    get_target_window 注入（ScriptEditorDialog 傳它的 title_edit）。"""

    def __init__(self, atype: str, initial: dict | None = None, parent=None,
                 get_target_window=None, get_platform=None, capture_factory=None,
                 goto_choices: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"編輯「{action_type_label(atype)}」動作")
        self._edits: dict[str, QLineEdit | QComboBox] = {}
        self._get_target_window = get_target_window
        self._overlay = None                 # 保留引用避免被 GC
        if get_platform is None:
            from keyboard_executor.platforms.factory import get_platform as _real
            get_platform = _real
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._get_platform = get_platform
        self._capture_factory = capture_factory
        layout = QFormLayout(self)
        initial = initial or {}
        for name, kind in FIELD_SPECS[atype]:
            if name in _GOTO_FIELDS and goto_choices is not None:
                box = _goto_combo(goto_choices, initial.get(name))
                layout.addRow(field_label(name), box)
                self._edits[name] = box
                continue
            if name == "branches":
                widget = _BranchesEdit(self, initial.get(name) or [], goto_choices)
                layout.addRow(field_label(name), widget)
                self._edits[name] = widget
                continue
            if kind == "bool":
                kind = "choice:false/true"
                if isinstance(initial.get(name), bool):
                    initial = {**initial, name: str(initial[name]).lower()}
            if kind.startswith("choice:"):
                box = QComboBox()
                for v in kind.split(":", 1)[1].split("/"):
                    box.addItem(choice_label(v), v)     # 顯示繁中、userData 存原值
                if name in initial and initial[name] is not None:
                    idx = box.findData(str(initial[name]))
                    if idx >= 0:
                        box.setCurrentIndex(idx)
                layout.addRow(field_label(name), box)
                self._edits[name] = box
                continue
            if kind in ("key", "keys"):
                widget = _KeyCaptureEdit(combo=(kind == "keys"))
                val = initial.get(name)
                if val is not None:
                    widget.setText("+".join(val) if isinstance(val, list) else str(val))
                layout.addRow(field_label(name), widget)
                self._edits[name] = widget
                continue
            edit = QLineEdit()
            value = initial.get(name)
            if value is not None:
                if kind == "keys":
                    edit.setText("+".join(value))
                elif kind == "actions_json":
                    edit.setText(json.dumps(value, ensure_ascii=False))
                elif isinstance(value, list):
                    edit.setText(", ".join(str(v) for v in value))
                else:
                    edit.setText(str(value))
            if kind == "point":     # 起點/終點：同列右側附取點鈕
                row = QWidget()
                row_lay = QHBoxLayout(row)
                row_lay.setContentsMargins(0, 0, 0, 0)
                pick_one = QPushButton("選取")
                pick_one.setToolTip("在畫面上點一下，自動換算成視窗相對座標")
                pick_one.clicked.connect(
                    lambda _checked=False, n=name: self._pick_point(n))
                row_lay.addWidget(edit, stretch=1)
                row_lay.addWidget(pick_one)
                layout.addRow(field_label(name), row)
                self._edits[name] = edit
                continue
            if kind == "region":    # 區域：同列右側附框選鈕
                row = QWidget()
                row_lay = QHBoxLayout(row)
                row_lay.setContentsMargins(0, 0, 0, 0)
                pick_region = QPushButton("框選")
                pick_region.setToolTip("在畫面上拖曳框出範圍，自動換算成視窗相對區域")
                pick_region.clicked.connect(
                    lambda _checked=False, n=name: self._pick_region(n))
                row_lay.addWidget(edit, stretch=1)
                row_lay.addWidget(pick_region)
                layout.addRow(field_label(name), row)
                self._edits[name] = edit
                continue
            layout.addRow(field_label(name), edit)
            self._edits[name] = edit
        self.pick_status = QLabel("")
        self.pick_status.setWordWrap(True)
        if atype in _XY_PICK_TYPES:
            self.pick_button = QPushButton("在畫面上選取座標")
            self.pick_button.setToolTip(
                "凍結畫面後點一下目標位置，自動填入 X／Y（已換算成視窗相對座標）")
            self.pick_button.clicked.connect(self._pick_xy)
            layout.addRow("", self.pick_button)
        if atype == "minimap_move":
            self.dot_button = QPushButton("用人物目前位置當目標")
            self.dot_button.setToolTip(
                "先把人物走到想去的位置，再按這裡：讀取小地圖黃點並填入目標位置")
            self.dot_button.clicked.connect(self._fill_target_from_dot)
            layout.addRow("", self.dot_button)
        layout.addRow("", self.pick_status)
        ok = QPushButton("確定")
        ok.setProperty("variant", "primary")
        ok.clicked.connect(self.accept)
        layout.addRow(ok)

    # ---------- 取點 ----------

    def _resolve_window(self):
        """目標視窗（換算視窗相對座標的必要前提）；失敗時說明原因並回 None。"""
        title = ((self._get_target_window() or "").strip()
                 if self._get_target_window is not None else "")
        if not title:
            self.pick_status.setText(
                "請先在編輯器上方填「視窗標題（regex）」，才能換算成視窗相對座標")
            return None
        wm = self._get_platform().window_manager
        windows = wm.find_windows(title_pattern=title)
        if not windows:
            self.pick_status.setText(f"找不到符合 {title!r} 的視窗")
            return None
        # 框選／取點／讀小地圖都要看到遊戲畫面：先把目標視窗切到最上層。
        try:
            active = wm.activate(windows[0])
        except Exception as e:
            self.pick_status.setText(f"無法將目標視窗切到最上層：{e}")
            return None
        if not active:
            self.pick_status.setText("無法將目標視窗切到最上層，請確認視窗未被系統阻擋")
            return None
        return wm.refresh(windows[0]) or windows[0]

    def _open_point_picker(self, on_point) -> None:
        from PySide6.QtGui import QGuiApplication

        from keyboard_executor.app.point_picker import PointPickerOverlay
        from keyboard_executor.app.region_math import screen_point_to_window_point
        from keyboard_executor.app.region_picker import drag_scale
        from keyboard_executor.core.geometry import Point

        win = self._resolve_window()
        if win is None:
            return
        origin = Point(win.x, win.y)

        def to_window(sx: int, sy: int):
            scale = drag_scale(QGuiApplication.primaryScreen().devicePixelRatio())
            return screen_point_to_window_point(sx, sy, origin, scale)

        overlay = PointPickerOverlay(self._capture_factory, to_window, self)
        self._overlay = overlay
        overlay.point_picked.connect(lambda sx, sy: on_point(*to_window(sx, sy)))
        overlay.open_fullscreen()

    def _pick_xy(self) -> None:
        def fill(wx: int, wy: int) -> None:
            self._edits["x"].setText(str(wx))
            self._edits["y"].setText(str(wy))
            self.pick_status.setText(f"已填入座標 {wx}, {wy}")

        self._open_point_picker(fill)

    def _pick_point(self, name: str) -> None:
        def fill(wx: int, wy: int) -> None:
            self._edits[name].setText(f"{wx}, {wy}")
            self.pick_status.setText(f"已填入{field_label(name)}：{wx}, {wy}")

        self._open_point_picker(fill)

    def _pick_region(self, name: str) -> None:
        self.pick_region_into(self._edits[name], field_label(name))

    def pick_region_into(self, edit, label: str) -> None:
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.core.geometry import Point

        win = self._resolve_window()
        if win is None:
            return
        overlay = RegionPickerOverlay(self, capture_factory=self._capture_factory)
        self._overlay = overlay

        def on_selected(rect) -> None:
            scale = drag_scale(overlay.devicePixelRatio())
            try:
                region = screen_rect_to_window_region(rect, Point(win.x, win.y), scale)
            except ValueError as e:
                self.pick_status.setText(str(e))
                return
            edit.setText(", ".join(str(v) for v in region))
            self.pick_status.setText(f"已填入{label}：{', '.join(map(str, region))}")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()

    def _fill_target_from_dot(self) -> None:
        dot = self.read_player_dot()
        if dot is not None:
            self._edits["target"].setText(f"{dot[0]}, {dot[1]}")
            self.pick_status.setText(f"已填入人物目前位置：{dot[0]}, {dot[1]}")

    def read_player_dot(self):
        """讀小地圖黃點（視窗相對座標）；失敗時在狀態列說明原因並回 None。"""
        from keyboard_executor.app.action_fields import parse_int_list
        from keyboard_executor.core.geometry import Rect
        from keyboard_executor.core.minimap import find_player_dot

        raw = self._edits["region"].text().strip()
        if not raw:
            self.pick_status.setText("請先框選小地圖範圍")
            return None
        try:
            rx, ry, rw, rh = parse_int_list("region", raw, 4)
        except ScriptValidationError as e:
            self.pick_status.setText(str(e))
            return None
        win = self._resolve_window()
        if win is None:
            return None
        capture = self._capture_factory()
        try:
            scale = capture.scale_factor()
            image = capture.capture(Rect(round((win.x + rx) * scale), round((win.y + ry) * scale),
                                         round(rw * scale), round(rh * scale)))
        finally:
            close = getattr(capture, "close_current_thread", None)
            if close is not None:
                close()
        dot = find_player_dot(image, scale)
        if dot is None:
            self.pick_status.setText("小地圖範圍內找不到唯一的黃點，請確認範圍與人物位置")
            return None
        return rx + int(dot[0] / scale), ry + int(dot[1] / scale)

    def values(self) -> dict[str, str]:
        return {name: (w.currentData() if isinstance(w, QComboBox) else w.text())
                for name, w in self._edits.items()}


def _action_form(atype, initial=None, parent=None, **options):
    """迴圈以遞迴表單編輯，其他動作沿用欄位表單。"""
    if atype == "loop":
        return LoopActionForm(initial=initial, parent=parent, **options)
    return ActionForm(atype, initial=initial, parent=parent, **options)


class LoopActionForm(QDialog):
    """每層迴圈各自編輯次數與動作；接受後才交回上層草稿。"""

    def __init__(self, initial=None, parent=None, **form_options):
        from keyboard_executor.app.script_editor_model import ScriptEditorModel

        super().__init__(parent)
        self.setWindowTitle("編輯迴圈與內含動作")
        form_options.pop("goto_choices", None)    # 迴圈內「跳到動作」指的是迴圈內的序號
        self._form_options = form_options
        self._model = ScriptEditorModel.new()
        initial = initial or {}
        for action in initial.get("actions", []):
            self._model.insert(len(self._model), action)
        layout = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名稱（可留空）"))
        self.name_edit = QLineEdit(initial.get("name") or "")
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("重複次數（-1＝無限，直到停止）"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(-1, 999999)
        self.count_spin.setValue(initial.get("count", 1))
        count_row.addWidget(self.count_spin)
        layout.addLayout(count_row)
        hint = QLabel("可新增另一個迴圈。選取內層迴圈後按「編輯」，設定它的次數與動作。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.action_list = QListWidget()
        self.action_list.setMinimumHeight(180)
        self.action_list.itemDoubleClicked.connect(lambda _: self._on_edit())
        layout.addWidget(self.action_list, 1)
        buttons = QHBoxLayout()
        self.type_combo = QComboBox()
        for atype in FIELD_SPECS:
            self.type_combo.addItem(action_type_label(atype), atype)
        self.add_button = QPushButton("新增動作")
        self.edit_button = QPushButton("編輯")
        self.remove_button = QPushButton("刪除")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        for widget in (self.type_combo, self.add_button, self.edit_button,
                       self.remove_button, self.up_button, self.down_button):
            buttons.addWidget(widget)
        layout.addLayout(buttons)
        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.remove_button.clicked.connect(self._on_remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        done = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        done.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        done.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        done.accepted.connect(self.accept)
        done.rejected.connect(self.reject)
        layout.addWidget(done)
        self._refresh()
        fit_window_to_available_screen(self, 680, 450)

    def _choices(self) -> list[str]:
        return goto_choices_for([self._model.action_at(i) for i in range(len(self._model))])

    def values(self) -> dict[str, str]:
        return {"name": self.name_edit.text(),
                "count": str(self.count_spin.value()),
                "actions": json.dumps([self._model.action_at(i) for i in range(len(self._model))],
                                      ensure_ascii=False)}

    def add_action(self, atype: str, values: dict[str, str]) -> None:
        self._model.insert(len(self._model), to_action_dict(atype, values))
        self._refresh(len(self._model) - 1)

    def _refresh(self, selected=-1) -> None:
        self.action_list.clear()
        for index, row in enumerate(self._model.rows()):
            self.action_list.addItem(f"#{index} {row['label']}")
        self.action_list.setCurrentRow(selected)
        self.status_label.clear()

    def _on_add(self) -> None:
        atype = str(self.type_combo.currentData())
        form = _action_form(atype, parent=self, goto_choices=self._choices(),
                            **self._form_options)
        if form.exec() == QDialog.DialogCode.Accepted:
            try:
                self.add_action(atype, form.values())
            except ScriptValidationError as exc:
                self.status_label.setText(str(exc))

    def _on_edit(self) -> None:
        index = self.action_list.currentRow()
        if index < 0:
            return
        current = self._model.action_at(index)
        atype = current.pop("type")
        form = _action_form(atype, initial=current, parent=self, goto_choices=self._choices(),
                            **self._form_options)
        if form.exec() == QDialog.DialogCode.Accepted:
            try:
                self._model.update(index, to_action_dict(atype, form.values()))
                self._refresh(index)
            except ScriptValidationError as exc:
                self.status_label.setText(str(exc))

    def _on_remove(self) -> None:
        index = self.action_list.currentRow()
        if index >= 0:
            self._model.remove(index)
            self._refresh(min(index, len(self._model) - 1))

    def _move(self, delta) -> None:
        index = self.action_list.currentRow()
        if index >= 0:
            self._refresh(self._model.move(index, delta))

    def accept(self) -> None:
        try:
            action_from_dict(to_action_dict("loop", self.values()))
        except ScriptValidationError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()


class ScriptEditorDialog(QDialog):
    def __init__(self, model, storage, parent=None, window_lister=None, *, ai_model_label="",
                 platform_name=None):
        super().__init__(parent)
        self._model = model
        self._storage = storage
        self._window_lister = window_lister
        self._ai_model_label = ai_model_label
        self._windows = []
        self._nodes = []
        self._positions: list[QPoint] = []
        self._clipboard: list[dict] = []     # 複製/剪下的動作（Ctrl+C／X → Ctrl+V）
        self._undo_stack: list[tuple] = []   # (model snapshot, positions) 供 Ctrl+Z
        self._redo_stack: list[tuple] = []
        self._selected = -1
        self._multi = set()          # 多選（供框選組成迴圈）
        self._links: set[int] = set()   # 手動連接：i 在集合裡＝「#i → #i+1」固定，不依位置重排
        self._pending_map = None        # 繞一圈學到的地圖分析，存檔時一起寫入
        self._zoom = 1.0
        self._label_to_type = {action_type_label(t): t for t in sorted(FIELD_SPECS)}
        self.setWindowTitle(f"腳本編輯器——{model.name}")
        layout = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("腳本名稱"))
        self.name_edit = QLineEdit(model.name)
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)

        # 目標視窗：手動輸入 regex／app 名稱，或從開啟的視窗挑選。回放只會對此視窗
        # 切前景執行，找不到就中止、絕不誤送輸入到其他畫面（core/player 保證）。
        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("目標視窗"))
        self.window_combo = QComboBox()
        self.refresh_windows_button = QPushButton("重新整理")
        self.use_window_button = QPushButton("用此視窗")
        pick_row.addWidget(self.window_combo, stretch=1)
        pick_row.addWidget(self.refresh_windows_button)
        pick_row.addWidget(self.use_window_button)
        layout.addLayout(pick_row)
        tw_form = QFormLayout()
        self.title_edit = QLineEdit(model.target_title)
        self.title_edit.setPlaceholderText("視窗標題 regex，如 .*記事本.*")
        tw_form.addRow("視窗標題（regex）", self.title_edit)
        self.app_edit = QLineEdit(model.target_app)
        self.app_edit.setPlaceholderText("應用程式名稱（可留空）")
        tw_form.addRow("應用程式名稱", self.app_edit)
        layout.addLayout(tw_form)

        self.loop_check = QCheckBox("循環執行（重複整段動作，直到按停止或 F10）")
        self.loop_check.setChecked(model.loop_forever)
        layout.addWidget(self.loop_check)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("鍵盤輸入模式"))
        self.input_mode_combo = QComboBox()
        if (platform_name or sys.platform) == "darwin":
            self.input_mode_combo.addItem("標準模式（macOS）", "normal")
            self.input_mode_combo.setToolTip(
                "使用 macOS 標準鍵盤輸入，需授予「輔助使用」權限。"
                "Windows 腳本儲存後會改用此模式。")
        else:
            self.input_mode_combo.addItem("一般模式（SendInput）", "normal")
            self.input_mode_combo.addItem("遊戲模式（DirectInput scan code）", "game")
            self.input_mode_combo.addItem(
                "前景訊息相容模式（WM_KEYDOWN／WM_KEYUP；含四方向鍵）",
                "window_message")
            self.input_mode_combo.addItem(
                "掃描碼脈衝模式（方向鍵每約 30ms 重新觸發）",
                "scan_pulse")
            self.input_mode_combo.setToolTip(
                "前景訊息相容模式只在目標視窗位於前景時送出鍵盤訊息；"
                "掃描碼脈衝模式會把長按拆成反覆按下/放開；"
                "用於一般、遊戲與前景訊息模式仍收不到部分方向鍵時。")
        self.input_mode_combo.setCurrentIndex(
            max(0, self.input_mode_combo.findData(model.input_mode)))
        input_row.addWidget(self.input_mode_combo, 1)
        layout.addLayout(input_row)

        hk_row = QHBoxLayout()
        hk_row.addWidget(QLabel("啟動快捷鍵"))
        self.hotkey_edit = _KeyCaptureEdit(combo=True)
        self.hotkey_edit.setText(model.hotkey)
        hk_row.addWidget(self.hotkey_edit, 1)
        layout.addLayout(hk_row)

        timed_row = QHBoxLayout()
        timed_row.addWidget(QLabel("定時技能"))      # 預設垂直置中
        from keyboard_executor.app.timed_keys_widget import TimedKeysWidget
        self.timed_keys_edit = TimedKeysWidget(model.timed_keys_text)
        self.timed_keys_edit.setToolTip(
            "每隔幾秒自動按一次（buff 等）。開始時先放一次，之後在兩個動作之間插入，"
            "不打斷正在走路或爬繩的動作。")
        timed_row.addWidget(self.timed_keys_edit, 1)
        layout.addLayout(timed_row)

        chat_row = QHBoxLayout()
        self.chat_reply_button = QPushButton("AI 自動回覆")
        self.chat_reply_button.clicked.connect(self._on_chat_reply)
        self.chat_reply_status = QLabel()
        chat_row.addWidget(self.chat_reply_button)
        chat_row.addWidget(self.chat_reply_status, 1)
        layout.addLayout(chat_row)
        image_row = QHBoxLayout()
        self.sequence_input_button = QPushButton("圖片順序輸入")
        self.sequence_input_button.clicked.connect(self._on_sequence_input)
        self.sequence_input_status = QLabel()
        image_row.addWidget(self.sequence_input_button)
        image_row.addWidget(self.sequence_input_status, 1)
        layout.addLayout(image_row)
        route_row = QHBoxLayout()
        self.learn_route_button = QPushButton("繞一圈學路線")
        self.learn_route_button.setToolTip(
            "在遊戲裡照平常跑一圈，自動學會走路、攻擊、爬繩、下跳、傳點和按鍵，"
            "產生的動作放進這個腳本。")
        self.learn_route_button.clicked.connect(self._on_learn_route)
        route_row.addWidget(self.learn_route_button)
        route_row.addWidget(QLabel("小地圖範圍與定時技能沿用這個腳本的設定"), 1)
        layout.addLayout(route_row)

        # 序列標題列：說明 + 自動排列 + 縮放
        seq_head = QHBoxLayout()
        seq_head.addWidget(QLabel("動作序列"))
        hint = QLabel("自由拖動擺位＝依位置排序・從右側圓點拉到另一個動作＝手動連接（橘線，右鍵可取消）・空白處拉框選取・雙擊編輯・Ctrl＋滾輪縮放")
        hint.setObjectName("moduleSub")
        seq_head.addWidget(hint)
        seq_head.addStretch(1)
        self.arrange_button = QPushButton("校正距離")
        self.arrange_button.setProperty("variant", "ghost")
        self.arrange_button.setToolTip("把散亂的動作一鍵校正成等間隔排列（依實際寬度平均間隔）")
        seq_head.addWidget(self.arrange_button)
        self.zoom_out_button = QPushButton("－")
        self.zoom_out_button.setObjectName("zoomBtn")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        self.zoom_in_button = QPushButton("＋")
        self.zoom_in_button.setObjectName("zoomBtn")
        seq_head.addWidget(self.zoom_out_button)
        seq_head.addWidget(self.zoom_label)
        seq_head.addWidget(self.zoom_in_button)
        layout.addLayout(seq_head)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("flowScroll")
        self.scroll.setWidgetResizable(True)
        self.canvas = _ChipCanvas()
        self.scroll.setWidget(self.canvas)
        self.canvas.zoomRequested.connect(self._zoom_step)
        self.canvas.rubberSelected.connect(self._on_rubber)
        self.canvas.menuRequested.connect(self._show_seq_menu)
        self.canvas.linkDragged.connect(self._on_link_dragged)
        self.canvas.linkDropped.connect(self._on_link_dropped)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 快捷鍵僅在畫布（或其中的 chip）有焦點時作用，才不會搶走名稱/視窗輸入框的文字複製
        for seq, slot in (
            (QKeySequence.StandardKey.Copy, self._copy),
            (QKeySequence.StandardKey.Cut, self._cut),
            (QKeySequence.StandardKey.Paste, self._paste),
            (QKeySequence.StandardKey.Delete, self._delete),
            (QKeySequence.StandardKey.SelectAll, self._select_all),
            (QKeySequence.StandardKey.Undo, self._undo),        # Ctrl+Z
            (QKeySequence.StandardKey.Redo, self._redo),        # Ctrl+Y
            (QKeySequence.StandardKey.Save, self._on_save),     # Ctrl+S
            (QKeySequence("Ctrl+D"), self._on_duplicate),       # 複製一份
            (QKeySequence("Ctrl+Shift+Z"), self._redo),         # 另一種重做習慣
        ):
            sc = QShortcut(QKeySequence(seq), self.canvas)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
        layout.addWidget(self.scroll, stretch=1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("新增動作")
        self.edit_button = QPushButton("編輯")
        self.duplicate_button = QPushButton("複製")
        self.remove_button = QPushButton("刪除")
        self.remove_button.setProperty("variant", "danger")
        self.group_button = QPushButton("組成迴圈")
        self.group_button.setToolTip("Ctrl/Shift 選取多個連續動作後，把它們包成重複執行的迴圈")
        self.ungroup_button = QPushButton("解散迴圈")
        self.ungroup_button.setToolTip("把選取的迴圈拆回其內含動作")
        self.save_button = QPushButton("儲存")
        self.save_button.setProperty("variant", "primary")
        for b in (self.add_button, self.edit_button, self.duplicate_button, self.remove_button):
            buttons.addWidget(b)
        buttons.addSpacing(14)
        buttons.addWidget(self.group_button)
        buttons.addWidget(self.ungroup_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.remove_button.clicked.connect(self._on_remove)
        self.duplicate_button.clicked.connect(self._on_duplicate)
        self.group_button.clicked.connect(self._on_group_loop)
        self.ungroup_button.clicked.connect(self._on_ungroup_loop)
        self.save_button.clicked.connect(self._on_save)
        self.arrange_button.clicked.connect(self.auto_arrange)
        self.zoom_in_button.clicked.connect(lambda: self._zoom_step(1))
        self.zoom_out_button.clicked.connect(lambda: self._zoom_step(-1))
        self.refresh_windows_button.clicked.connect(self._refresh_windows)
        self.use_window_button.clicked.connect(self._use_selected_window)
        self._refresh_windows()
        self._load_layout()
        self.refresh()
        fit_window_to_available_screen(self, 820, 660)

    def _load_layout(self) -> None:
        """開啟時還原上次儲存的版面（chip 座標/縮放），避免重開後「自動改變樣子」；
        沒有版面或動作數不符則留空，交給 refresh→auto_arrange 自動排列。"""
        if self._storage is None or not hasattr(self._storage, "load_layout"):
            return
        try:
            layout = self._storage.load_layout(self._model.name)
        except Exception:
            layout = None
        if not layout:
            return
        pts = layout.get("positions")
        if isinstance(pts, list) and len(pts) == len(self._model):
            try:
                self._positions = [QPoint(int(x), int(y)) for x, y in pts]
            except (TypeError, ValueError):
                self._positions = []
        z = layout.get("zoom")
        if isinstance(z, (int, float)) and not isinstance(z, bool):
            self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, float(z)))
            self.zoom_label.setText(f"{int(self._zoom * 100)}%")
        links = layout.get("manual_links")
        if isinstance(links, list) and len(self._positions) == len(self._model):
            self._links = {i for i in links
                           if isinstance(i, int) and 0 <= i < len(self._model) - 1}

    # -- 位置與畫布佈局 --

    def _band(self) -> int:
        return max(1, int(70 * self._zoom))

    def _canvas_width(self) -> int:
        w = self.scroll.viewport().width()
        return w if w > 80 else 760

    def _grid_slot(self, i: int) -> QPoint:
        """第 i 個節點在整齊格線上的座標（row-major，供初次擺放與自動排列）。"""
        step_x, step_y = int(150 * self._zoom), int(96 * self._zoom)
        cols = max(1, (self._canvas_width() - 28) // step_x)
        r, c = divmod(i, cols)
        return QPoint(14 + c * step_x, 14 + r * step_y)

    def _tail_slot(self) -> QPoint:
        """新動作接在目前最後一個動作後面（同列右側，放不下就換到最下面一列）。
        用格線位置會落在既有動作中間，拖動任何動作後順序就被重排、連線跑掉。"""
        if not self._positions:
            return self._grid_slot(0)
        def size(i):
            if i < len(self._nodes):
                hint = self._nodes[i].sizeHint()
                return hint.width(), hint.height()
            return int(130 * self._zoom), int(60 * self._zoom)
        gap = int(28 * self._zoom)
        last = self._positions[-1]
        w, _ = size(len(self._positions) - 1)
        bottom = max(p.y() + size(i)[1] for i, p in enumerate(self._positions))
        below = QPoint(14, max(bottom + gap, max(p.y() for p in self._positions) + self._band()))
        candidates = [below]
        if last.x() + w + gap + int(130 * self._zoom) <= self._canvas_width() - 14:
            candidates.insert(0, QPoint(last.x() + w + gap, last.y()))
        n = len(self._positions)
        for slot in candidates:
            pts = self._centers(self._positions + [slot])
            if order_from_positions(pts, self._band())[-1] == n:
                return slot
        return below

    def _centers(self, positions) -> list[tuple[int, float]]:
        """排序依據：左上角 x、節點垂直中心 y（還沒建立的節點用一般高度估）。"""
        def height(i):
            if i < len(self._nodes):
                return self._nodes[i].sizeHint().height()
            return int(60 * self._zoom)
        return [(p.x(), p.y() + height(i) / 2) for i, p in enumerate(positions)]

    def _ensure_positions(self) -> None:
        """節點數與位置數不一致時（首次開啟等），退回整齊格線排一次。"""
        if len(self._positions) != len(self._model):
            self._positions = [self._grid_slot(i) for i in range(len(self._model))]

    def _even_spacing_positions(self) -> list[QPoint]:
        """依各節點實際寬度算出等間隔位置（校正距離／平均間隔）。需節點已建立可量測。"""
        sizes = [(n.sizeHint().width(), n.sizeHint().height()) for n in self._nodes]
        gap = int(28 * self._zoom)
        pts = even_layout(sizes, self._canvas_width() - 28, gap, start=14)
        return [QPoint(x, y) for x, y in pts]

    def _apply_even_spacing(self) -> None:
        """實際套用等間隔位置（不記 undo）；供首次擺放與 auto_arrange 共用。"""
        if len(self._nodes) != len(self._model):
            self.refresh()
        self._positions = self._even_spacing_positions()
        for i, node in enumerate(self._nodes):
            node.move(self._positions[i])
        self.canvas.set_bounds()
        self.canvas.update()

    def auto_arrange(self) -> None:
        """一鍵校正距離：把動作依執行順序、實際寬度排成等間隔（超寬換列）。可 Ctrl+Z 復原。"""
        self._push_undo()
        self._apply_even_spacing()

    # -- chip 畫布（可測 seam） --

    def refresh(self) -> None:
        sequence = self._model.sequence_input
        if sequence and sequence.enabled:
            mode = "OCR 偵測 → AI 辨識" if sequence.mode == "panel" else "舊版手動設定"
            self.sequence_input_status.setText(f"已啟用：{mode}／總時限 30 秒")
        else:
            self.sequence_input_status.setText("未啟用")
        config = self._model.chat_reply
        if not config or not config.enabled:
            self.chat_reply_status.setText("未啟用")
        elif not config.active:
            self.chat_reply_status.setText("已暫停（未選回覆頻道）")
        else:
            channels = [label for label, selected in
                        (("密語", config.reply_whisper), ("地圖", config.reply_map)) if selected]
            self.chat_reply_status.setText("已啟用：" + "／".join(channels))
        self.canvas.clear()
        self._nodes = []
        fresh = len(self._positions) != len(self._model)   # 位置數不符＝需重新擺放
        self._ensure_positions()
        for i in range(len(self._model)):
            d = self._model.action_at(i)
            if d["type"] == "loop":
                node = _LoopGroup(i, d, self._zoom)
                node.innerDoubleClicked.connect(self._edit_loop_inner)
                node.addClicked.connect(self._add_to_loop)
            else:
                main, sub, kind = _chip_spec(d)
                node = _ActionChip(i, main, sub, kind, self._zoom)
            node.setToolTip(
                f"#{i} {action_type_label(d['type'])}（自由拖動擺位・雙擊編輯）")
            node.clicked.connect(self._select)
            node.doubleClicked.connect(self._edit_index)
            node.movedBy.connect(self._on_node_moved_by)
            node.dropped.connect(self._on_node_dropped)
            node.menuRequested.connect(self._node_menu)
            node.linkDragged.connect(self._on_link_dragged)
            node.linkDropped.connect(self._on_link_dropped)
            self.canvas.add_node(node)
            node.move(self._positions[i])
            self._nodes.append(node)
        self._links = {i for i in self._links if 0 <= i < len(self._model) - 1}
        self.canvas.manual_links = set(self._links)
        self.canvas.set_bounds()
        if fresh:
            self._apply_even_spacing()   # 首次擺放：節點已建立可量測寬度→等間隔（不記 undo）
        self._apply_selection()

    def chip_count(self) -> int:
        return len(self._nodes)

    def arrow_count(self) -> int:
        return max(0, len(self._model) - 1)

    def select_index(self, index: int) -> None:
        self._select(index)

    def _select(self, index: int) -> None:
        if not (0 <= index < len(self._nodes)):
            self._selected, self._multi = -1, set()
            self._apply_selection()
            return
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier and 0 <= self._selected < len(self._nodes):
            lo, hi = sorted((self._selected, index))
            self._multi = set(range(lo, hi + 1))        # Shift：選一整段（供組成迴圈）
        elif mods & Qt.KeyboardModifier.ControlModifier:
            self._multi = set(self._multi) ^ {index}     # Ctrl：加/減個別
            self._selected = index
        elif index in self._multi and len(self._multi) > 1:
            self._selected = index       # 點「已在多選中的」節點：保留多選以便整組拖動
        else:
            self._multi = {index}
            self._selected = index
        self._apply_selection()
        self.canvas.setFocus()          # 點 chip 後焦點在畫布，Ctrl+C/V 才生效

    def _selection_indices(self) -> list:
        sel = self._multi if self._multi else ({self._selected} if self._selected >= 0 else set())
        return sorted(i for i in sel if 0 <= i < len(self._model))

    def _apply_selection(self) -> None:
        sel = set(self._selection_indices())
        for i, node in enumerate(self._nodes):
            node.setProperty("selected", i in sel)
            node.style().unpolish(node)
            node.style().polish(node)

    def _on_rubber(self, indices: list) -> None:
        """框選命中的動作 → 設為多選（接著可 Ctrl+C 複製、按「組成迴圈」或右鍵）。"""
        self._multi = set(indices)
        self._selected = indices[0] if indices else -1
        self._apply_selection()
        self.canvas.setFocus()          # 讓 Ctrl+C/V 等快捷鍵針對畫布

    def _select_all(self) -> None:
        n = len(self._model)
        self._multi = set(range(n))
        self._selected = 0 if n else -1
        self._apply_selection()
        self.canvas.setFocus()

    # -- 複製／剪下／貼上／刪除（畫布快捷鍵與右鍵選單共用） --

    def _copy(self) -> None:
        sel = self._selection_indices()
        if not sel:
            return
        self._clipboard = [self._model.action_at(i) for i in sel]   # action_at＝deepcopy
        self.status_label.setText(f"已複製 {len(sel)} 個動作（Ctrl+V 貼上）")

    def _cut(self) -> None:
        sel = self._selection_indices()
        if not sel:
            return
        self._clipboard = [self._model.action_at(i) for i in sel]
        self._push_undo()
        for i in reversed(sel):
            self._model.remove(i)
            del self._positions[i]
        self._remap_links(self._kept_map(sel))
        self._selected, self._multi = -1, set()
        self.status_label.setText(f"已剪下 {len(sel)} 個動作（Ctrl+V 貼上）")
        self.refresh()

    def _paste(self) -> None:
        if not self._clipboard:
            return
        self._push_undo()
        start = len(self._model)
        for action in self._clipboard:
            self._model.insert(len(self._model), action)            # 貼到序列尾端
            self._positions.append(self._tail_slot())
        self._multi = set(range(start, len(self._model)))
        self._selected = start
        self.status_label.setText(f"已貼上 {len(self._clipboard)} 個動作（可拖動排位置）")
        self.refresh()
        self.canvas.setFocus()

    def _delete(self) -> None:
        self._on_remove()

    def _kept_map(self, removed) -> dict[int, int]:
        removed = set(removed)
        kept = [i for i in range(len(self._model) + len(removed)) if i not in removed]
        return {old: new for new, old in enumerate(kept)}

    # -- 復原／重做（Ctrl+Z / Ctrl+Y）：快照模型狀態＋chip 位置 --

    def _push_undo(self) -> None:
        """在每個會改動內容/位置的操作「之前」呼叫，記下當前狀態供復原。"""
        self._undo_stack.append((self._model.snapshot(),
                                 [QPoint(p) for p in self._positions], set(self._links)))
        self._redo_stack.clear()
        if len(self._undo_stack) > 100:      # 限制歷史長度
            self._undo_stack.pop(0)

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((self._model.snapshot(),
                                 [QPoint(p) for p in self._positions], set(self._links)))
        snap, positions, links = self._undo_stack.pop()
        self._model.restore(snap)
        self._positions = [QPoint(p) for p in positions]
        self._links = set(links)
        self._selected, self._multi = -1, set()
        self.status_label.setText("已復原")
        self.refresh()
        self.canvas.setFocus()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((self._model.snapshot(),
                                 [QPoint(p) for p in self._positions], set(self._links)))
        snap, positions, links = self._redo_stack.pop()
        self._model.restore(snap)
        self._positions = [QPoint(p) for p in positions]
        self._links = set(links)
        self._selected, self._multi = -1, set()
        self.status_label.setText("已重做")
        self.refresh()
        self.canvas.setFocus()

    def _select_single(self, index: int) -> None:
        self._selected, self._multi = index, {index}
        self._apply_selection()

    def _node_menu(self, index: int, global_pos) -> None:
        if index not in set(self._selection_indices()):
            self._select_single(index)      # 右鍵未選取的節點＝先單選它
        self._show_seq_menu(global_pos)

    def _show_seq_menu(self, global_pos) -> None:
        """畫布右鍵選單：複製/剪下/貼上/刪除、全選、校正距離、框選組迴圈、解散迴圈。"""
        sel = self._selection_indices()
        menu = QMenu(self)
        menu.addAction("復原\tCtrl+Z", self._undo).setEnabled(bool(self._undo_stack))
        menu.addAction("重做\tCtrl+Y", self._redo).setEnabled(bool(self._redo_stack))
        menu.addSeparator()
        menu.addAction("複製\tCtrl+C", self._copy).setEnabled(len(sel) >= 1)
        menu.addAction("剪下\tCtrl+X", self._cut).setEnabled(len(sel) >= 1)
        menu.addAction("貼上\tCtrl+V", self._paste).setEnabled(bool(self._clipboard))
        menu.addAction("刪除\tDel", self._delete).setEnabled(len(sel) >= 1)
        menu.addSeparator()
        one = sel[0] if len(sel) == 1 else -1
        menu.addAction("取消與下一個的手動連接",
                       lambda: self.cancel_link(one)).setEnabled(one in self._links)
        menu.addAction("取消與上一個的手動連接",
                       lambda: self.cancel_link(one - 1)).setEnabled(
                           one > 0 and one - 1 in self._links)
        menu.addAction("取消全部手動連接", self.cancel_all_links).setEnabled(bool(self._links))
        menu.addSeparator()
        menu.addAction("全選\tCtrl+A", self._select_all)
        menu.addAction("校正距離（平均間隔）", self.auto_arrange)
        menu.addSeparator()
        act_group = menu.addAction("組成迴圈…", self._on_group_loop)
        act_group.setEnabled(len(sel) >= 1)
        act_ungroup = menu.addAction("解散迴圈", self._on_ungroup_loop)
        act_ungroup.setEnabled(len(sel) == 1 and self._model.is_loop(sel[0]))
        menu.exec(global_pos)

    def _edit_index(self, index: int) -> None:
        self._selected, self._multi = index, {index}
        self._apply_selection()
        if self._model.is_loop(index):
            self._edit_loop_count(index)
        else:
            self._on_edit()

    def _top_choices(self) -> list[str]:
        return goto_choices_for([self._model.action_at(i) for i in range(len(self._model))])

    def _loop_choices(self, loop_index: int) -> list[str]:
        return goto_choices_for(self._model.action_at(loop_index).get("actions", []))

    def _edit_loop_inner(self, loop_index: int, inner_index: int) -> None:
        """雙擊迴圈框內的動作 → 開表單編輯它（免解散迴圈）。"""
        current = self._model.loop_inner_at(loop_index, inner_index)
        atype = current.pop("type")
        form = _action_form(atype, initial=current, parent=self,
                          get_target_window=lambda: self.title_edit.text(),
                          goto_choices=self._loop_choices(loop_index))
        if form.exec() != QDialog.DialogCode.Accepted:
            return
        self._push_undo()
        try:
            self._model.update_loop_inner(
                loop_index, inner_index, to_action_dict(atype, form.values()))
            self.status_label.setText("")
            self.refresh()
        except ScriptValidationError as e:
            self._undo_stack.pop()
            self.status_label.setText(f"無效的動作：{e}")

    def _edit_loop_count(self, index: int) -> None:
        """雙擊迴圈外框：改名稱與重複次數。"""
        cur = self._model.action_at(index)
        dialog = QDialog(self)
        dialog.setWindowTitle("編輯迴圈")
        form = QFormLayout(dialog)
        name_edit = QLineEdit(cur.get("name") or "")
        count_spin = QSpinBox()
        count_spin.setRange(-1, 999999)
        count_spin.setValue(cur.get("count", 1))
        form.addRow("名稱（可留空）", name_edit)
        form.addRow("重複次數（-1＝無限，直到停止）", count_spin)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        form.addRow(box)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._push_undo()
            self._model.set_loop_count(index, count_spin.value())
            self._model.set_action_name(index, name_edit.text())
            self.refresh()

    # -- 拖動排序：位置決定順序 --

    def _on_node_moved_by(self, index: int, delta) -> None:
        """拖動中：若被拖的節點屬於多選，讓其餘選取節點跟著同步位移（整組一起拖）。"""
        if len(self._multi) > 1 and index in self._multi:
            for i in self._multi:
                if i != index and 0 <= i < len(self._nodes):
                    node = self._nodes[i]
                    pos = node.pos() + delta
                    pos.setX(max(0, pos.x()))
                    pos.setY(max(0, pos.y()))
                    node.move(pos)
        self.canvas.update()

    def _on_node_dropped(self, index: int) -> None:
        self._commit_positions()

    def _commit_positions(self, *, undo: bool = True) -> None:
        """讀節點目前 live 位置 → 依位置重排 model（必要時），再重繪。
        手動連接的動作串成一組，整組跟著第一個動作的位置排，組內順序不變。"""
        if undo:
            self._push_undo()
        self._positions = [n.pos() for n in self._nodes] or self._positions
        groups: list[list[int]] = []
        for i in range(len(self._positions)):
            if i - 1 in self._links and groups:
                groups[-1].append(i)
            else:
                groups.append([i])
        centers = self._centers(self._positions)
        heads = order_from_positions([centers[g[0]] for g in groups], self._band())
        perm = [i for g in heads for i in groups[g]]
        if perm != list(range(len(perm))):
            self._apply_perm(perm)
        self._selected, self._multi = -1, set()
        self.refresh()

    # -- 手動連接（逐條；沒連接的仍依位置自動排序） --

    def _apply_perm(self, perm: list[int]) -> None:
        """依 perm（新順序的舊索引）重排 model、位置與手動連接。"""
        self._model.reorder(perm)
        self._positions = [self._positions[i] for i in perm]
        self._remap_links({old: new for new, old in enumerate(perm)})

    def _remap_links(self, new_of: dict[int, int]) -> None:
        """動作索引變動後保留仍相鄰的手動連接，不相鄰的自動取消。"""
        self._links = {new_of[i] for i in self._links
                       if i in new_of and i + 1 in new_of and new_of[i + 1] == new_of[i] + 1}

    def cancel_link(self, index: int) -> None:
        """取消「#index → #index+1」的手動連接，並立刻依位置重新排序。"""
        if index not in self._links:
            return
        self._push_undo()
        self._links.discard(index)
        self._commit_positions(undo=False)
        self.status_label.setText("已取消這條手動連接，改回依位置決定順序")

    def cancel_all_links(self) -> None:
        if not self._links:
            return
        self._push_undo()
        self._links.clear()
        self._commit_positions(undo=False)
        self.status_label.setText("已取消全部手動連接，改回依位置決定順序")

    def _on_link_dragged(self, index: int, point) -> None:
        node = self._nodes[index]
        self.canvas.set_link(node.mapToParent(node.out_port()), point)

    def _on_link_dropped(self, index: int, point) -> None:
        self.canvas.set_link(None, None)
        target = self.canvas.node_at(point, exclude=index)
        if target is not None:
            self.connect_actions(index, target)

    def connect_actions(self, src: int, dst: int) -> None:
        """手動連接 src → dst：把 dst 移到 src 的下一個，這一條之後不依位置重排。"""
        if src == dst or not (0 <= src < len(self._model) and 0 <= dst < len(self._model)):
            return
        self._push_undo()
        if dst != src + 1:
            # dst 離開原本的位置：它前後原有的手動連接斷開；src 原本接的下一個也被擠開。
            self._links -= {dst - 1, dst, src}
            order = list(range(len(self._model)))
            order.remove(dst)
            order.insert(order.index(src) + 1, dst)
            self._apply_perm(order)
            src, dst = order.index(src), order.index(dst)
        self._links.add(src)
        self._selected, self._multi = dst, {dst}
        self.status_label.setText(
            f"已手動連接 #{src} → #{dst}（橘色線）；這條不會因拖動位置改變，右鍵可取消")
        self.refresh()

    def _zoom_step(self, direction: int) -> None:
        new = round(self._zoom + 0.1 * direction, 2)
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, new))
        self.zoom_label.setText(f"{int(self._zoom * 100)}%")
        self.refresh()

    def add_action(self, atype: str, values: dict[str, str]) -> None:
        """表單字串值 → 驗證 → 加到序列尾端（自由畫布靠拖動排位置）。"""
        action = to_action_dict(atype, values)
        self._push_undo()
        self._model.insert(len(self._model), action)
        self._positions.append(self._tail_slot())
        self._selected = len(self._model) - 1
        self.refresh()

    # -- 按鈕處理器（thin） --

    def _on_add(self) -> None:
        label, ok = QInputDialog.getItem(
            self, "新增動作", "選擇動作類型", sorted(self._label_to_type), 0, False)
        if not ok:
            return
        atype = self._label_to_type.get(label, label)
        form = _action_form(atype, parent=self,
                          get_target_window=lambda: self.title_edit.text(),
                          goto_choices=self._top_choices())
        if form.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.add_action(atype, form.values())
            self.status_label.setText("")
        except ScriptValidationError as e:
            self.status_label.setText(f"無效的動作：{e}")

    def add_to_loop_action(self, loop_index: int, atype: str, values: dict) -> None:
        """表單字串值 → 驗證 → 加到 loop_index 迴圈末尾（可直接測試，不開對話框）。"""
        action = to_action_dict(atype, values)   # 無效→在此拋（尚未 push，不留孤兒快照）
        self._push_undo()
        try:
            self._model.add_to_loop(loop_index, action)
        except ScriptValidationError:
            self._undo_stack.pop()               # 驗證失敗→撤回這次快照，避免孤兒
            raise
        self.refresh()

    def _add_to_loop(self, loop_index: int) -> None:
        label, ok = QInputDialog.getItem(
            self, "在迴圈內新增動作", "選擇動作類型", sorted(self._label_to_type), 0, False)
        if not ok:
            return
        atype = self._label_to_type.get(label, label)
        form = _action_form(atype, parent=self,
                          get_target_window=lambda: self.title_edit.text(),
                          goto_choices=self._loop_choices(loop_index))
        if form.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.add_to_loop_action(loop_index, atype, form.values())
            self.status_label.setText("")
        except ScriptValidationError as e:
            self.status_label.setText(f"無效的動作：{e}")

    def _on_edit(self) -> None:
        index = self._selected
        if index < 0 or index >= len(self._model):
            self.status_label.setText("請先選取要編輯的動作（單擊節點）")
            return
        current = self._model.action_at(index)
        atype = current.pop("type")
        form = _action_form(atype, initial=current, parent=self,
                          get_target_window=lambda: self.title_edit.text(),
                          goto_choices=self._top_choices())
        if form.exec() != QDialog.DialogCode.Accepted:
            return
        self._push_undo()
        try:
            self._model.update(index, to_action_dict(atype, form.values()))
            self.status_label.setText("")
            self.refresh()
        except ScriptValidationError as e:
            self._undo_stack.pop()          # 撤回這次無效編輯的快照
            self.status_label.setText(f"無效的動作：{e}")

    def _on_remove(self) -> None:
        targets = self._selection_indices()
        if not targets:
            return
        self._push_undo()
        for i in reversed(targets):
            self._model.remove(i)
            del self._positions[i]
        self._remap_links(self._kept_map(targets))
        self._selected = min(targets[-1], len(self._model) - 1)
        self._multi = {self._selected} if self._selected >= 0 else set()
        self.refresh()

    def _on_group_loop(self) -> None:
        idx = self._selection_indices()
        if not idx:
            self.status_label.setText("請先選取要組成迴圈的動作（Ctrl／Shift 多選）")
            return
        lo, hi = idx[0], idx[-1]
        if list(range(lo, hi + 1)) != idx:
            self.status_label.setText("迴圈只能包住「連續」的動作")
            return
        count, ok = QInputDialog.getInt(
            self, "組成迴圈", "重複次數（-1＝無限，直到停止）", 2, -1, 999999)
        if not ok:
            return
        self._push_undo()
        total = len(self._model)
        self._selected = self._model.group_into_loop(lo, hi, count)
        self._remap_links({i: (i if i < lo else lo if i <= hi else i - (hi - lo))
                           for i in range(total)})
        self._positions[lo:hi + 1] = [self._positions[lo]]     # 迴圈盒沿用第一個的位置
        self._multi = {self._selected}
        self.status_label.setText("")
        self.refresh()

    def _on_ungroup_loop(self) -> None:
        index = self._selected
        if not self._model.is_loop(index):
            self.status_label.setText("請先選取一個迴圈再解散")
            return
        inner_n = len(self._model.action_at(index).get("actions", []))
        base = self._positions[index]
        step = int(150 * self._zoom)
        self._push_undo()
        total = len(self._model)
        self._model.ungroup_loop(index)
        grow = max(1, inner_n) - 1
        self._remap_links({i: (i if i <= index else i + grow) for i in range(total)})
        self._positions[index:index + 1] = [
            base + QPoint(j * step, 0) for j in range(max(1, inner_n))]
        self._multi = {index}
        self.refresh()

    def _on_duplicate(self) -> None:
        index = self._selected
        if index < 0 or index >= len(self._model):
            return
        self._push_undo()
        total = len(self._model)
        self._model.duplicate(index)
        self._remap_links({i: (i if i <= index else i + 1) for i in range(total)})
        self._positions.insert(index + 1, self._positions[index] + QPoint(24, 24))
        self._selected = index + 1
        self.refresh()

    # -- 繞一圈學路線 --

    route_panel_factory = None      # 測試可替換；預設用錄製面板的路線模式

    def _minimap_region(self):
        """腳本裡第一個小地圖動作的範圍（含迴圈內），沒有回 None。"""
        def scan(actions):
            for a in actions:
                if a.get("type") in ("minimap_move", "minimap_goto") and a.get("region"):
                    return a["region"]
                found = scan(a.get("actions") or [])
                if found:
                    return found
            return None
        return scan([self._model.action_at(i) for i in range(len(self._model))])

    def _on_learn_route(self) -> None:
        factory = self.route_panel_factory
        if factory is None:
            from keyboard_executor.app.recorder_panel import RecorderPanel
            from keyboard_executor.platforms.factory import get_platform

            def factory(**kw):
                return RecorderPanel(get_platform().window_manager, None, **kw)
        panel = factory(route_only=True, preset_region=self._minimap_region(),
                        preset_timed=self.timed_keys_edit.text().strip(),
                        preset_title=self.title_edit.text().strip(), parent=self)
        if panel.exec() != QDialog.DialogCode.Accepted or not panel.learned_actions:
            return
        learned = [action_to_dict(a) for a in panel.learned_actions]
        replace = False
        if len(self._model):
            box = QMessageBox(self)
            box.setWindowTitle("繞一圈學路線")
            box.setText("學到的路線要怎麼放？")
            replace_button = box.addButton("取代現有動作", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("加在最後面", QMessageBox.ButtonRole.ActionRole)
            cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                return
            replace = box.clickedButton() is replace_button
        self.apply_learned_route(learned, panel.learned_timed, replace=replace,
                                 window=getattr(panel, "_win", None))
        if getattr(panel, "learned_map", None):
            self._pending_map = (panel.learned_map, getattr(panel, "learned_png", None))

    def apply_learned_route(self, actions: list[dict], timed=(), *, replace: bool,
                            window=None) -> None:
        from keyboard_executor.core.models import timed_keys_to_text
        self._push_undo()
        if replace:
            while len(self._model):
                self._model.remove(len(self._model) - 1)
            self._positions = []
            self._links.clear()
        for action in actions:
            self._model.insert(len(self._model), action)
            self._positions.append(self._tail_slot())
            self.refresh()
        if timed and not self.timed_keys_edit.text().strip():
            self.timed_keys_edit.setText(timed_keys_to_text(timed))
        if window is not None and not (self.title_edit.text().strip()
                                       or self.app_edit.text().strip()):
            self.title_edit.setText(re.escape(window.title))
            self.app_edit.setText(window.app_name)
        self._selected = len(self._model) - 1
        self.refresh()
        self.status_label.setText(
            f"已{'取代成' if replace else '加入'}學到的路線（{len(actions)} 個動作），"
            "檢查後按儲存")

    def _refresh_windows(self) -> None:
        """列出開啟中、有標題的視窗供挑選（無 lister 時清單留空）。"""
        try:
            wins = list(self._window_lister()) if self._window_lister else []
        except Exception:
            wins = []
        self._windows = [w for w in wins if getattr(w, "title", "").strip()]
        self.window_combo.clear()
        self.window_combo.addItems(
            [f"{w.title}（{w.app_name}）" for w in self._windows])

    def _use_selected_window(self) -> None:
        i = self.window_combo.currentIndex()
        if 0 <= i < len(self._windows):
            w = self._windows[i]
            # 標題欄是 regex（re.search）；視窗標題常含 () 等特殊字元，直接填會被當成
            # 群組而配不到自己的視窗。escape 成字面比對（鏡射 recorder_session 的策略）。
            self.title_edit.setText(re.escape(w.title))
            self.app_edit.setText(w.app_name)

    def _on_save(self) -> None:
        self._model.set_name(self.name_edit.text())
        self._model.set_target(self.title_edit.text(), self.app_edit.text())
        self._model.set_loop_forever(self.loop_check.isChecked())
        self._model.set_input_mode(str(self.input_mode_combo.currentData()))
        self._model.set_hotkey(self.hotkey_edit.text())
        try:
            self._model.set_timed_keys_text(self.timed_keys_edit.text())
            path = self._storage.save(self._model.to_script())
        except ScriptValidationError as e:
            self.status_label.setText(f"儲存失敗：{e}")   # 名稱/目標視窗/動作不合法→重試
            return
        if hasattr(self._storage, "save_layout"):        # 一併存版面，重開才不會跑掉
            self._storage.save_layout(self._model.name, {
                "positions": [[p.x(), p.y()] for p in self._positions],
                "zoom": self._zoom, "manual_links": sorted(self._links)})
        old = self._model.original_name
        if self._pending_map is not None and hasattr(self._storage, "save_route_map"):
            self._storage.save_route_map(self._model.name, *self._pending_map)
            self._pending_map = None
        elif old and old != self._model.name and hasattr(self._storage, "copy_route_map"):
            self._storage.copy_route_map(old, self._model.name)    # 改名：地圖分析跟著走
        if old and old != self._model.name:
            # 編輯既有腳本且改了名 → 刪掉舊名那條（delete 一併清版面 sidecar），
            # 才是「同一條改名」而非新增一條。
            try:
                self._storage.delete(old)
            except ScriptValidationError:
                pass                       # 舊檔已不在也無妨
        self._model.mark_saved()          # 之後在同一視窗再存以新名為準
        self.status_label.setText(f"已儲存：{path}")
        self.accept()                       # 儲存成功 → 自動關閉

    def _on_sequence_input(self) -> None:
        from keyboard_executor.app.sequence_input_dialog import SequenceInputDialog
        dialog = SequenceInputDialog(self._model.sequence_input, self,
            get_target_window=lambda: self.title_edit.text(),
            get_target_app=lambda: self.app_edit.text(), model_label=self._ai_model_label)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.config()
            self._push_undo()
            self._model.set_sequence_input(config)
            self.refresh()
            self.status_label.setText("已更新圖片順序輸入；按「儲存」寫入腳本")

    def _on_chat_reply(self) -> None:
        from keyboard_executor.app.chat_reply_dialog import ChatReplyDialog

        dialog = ChatReplyDialog(
            self._model.chat_reply, self,
            get_target_window=lambda: self.title_edit.text(),
            get_target_app=lambda: self.app_edit.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.config()
            self._push_undo()
            self._model.set_chat_reply(config)
            self.refresh()
            self.status_label.setText("已更新 AI 自動回覆設定；按「儲存」寫入腳本")
