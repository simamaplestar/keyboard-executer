"""小地圖上「自己人物」黃點的定位（純影像，無輸入）。

實測（2026-10-11, MSW 楓之谷世界）：黃點是約 96 實體像素的飽和黃圓；地圖上其他
偏黃圖示面積只有 26–34。只取面積夠大且唯一的色塊，兩個大小相近的候選視為
無法判斷，寧可回 None 也不猜錯位置。
"""
from __future__ import annotations

import cv2
import numpy as np

# HSV（OpenCV：H 0–179）：飽和亮黃。
_HUE = (20, 34)
_MIN_SAT = 170
_MIN_VAL = 200
_MIN_AREA = 50          # 實體像素，scale=1；高 DPI 依面積平方放大


def find_player_dot(image: np.ndarray, scale: float = 1.0) -> tuple[float, float] | None:
    """回傳黃點中心（影像實體像素，可含小數）；找不到或不唯一回 None。"""
    if image is None or image.ndim != 3 or image.shape[2] < 3 or not image.size:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(image[:, :, :3]), cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= _HUE[0]) & (hsv[:, :, 0] <= _HUE[1])
            & (hsv[:, :, 1] >= _MIN_SAT) & (hsv[:, :, 2] >= _MIN_VAL)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    minimum = _MIN_AREA * scale * scale
    blobs = sorted(((int(stats[i][4]), centroids[i]) for i in range(1, count)
                    if stats[i][4] >= minimum), key=lambda blob: -blob[0])
    if not blobs or (len(blobs) > 1 and blobs[1][0] >= blobs[0][0] * .6):
        return None
    x, y = blobs[0][1]
    return float(x), float(y)


# 實測：走路約 27 px/s；按下到黃點開始動、放開到停住各約 0.15–0.3 秒，
# 放開後黃點還會再走約 6 px。50ms 點按剛好 1 px。
_INITIAL_SLIDE = 6.0
_POLL = .03
_SETTLE_STABLE = .15
_STUCK_SEC = 1.5
_DIRECTION_LEAD = .1
_RESPONSE = .25         # 輸入後黃點反應延遲；先等過才判斷是否停穩
_FALL_START = 1.5       # 下跳後最久等多久高度開始改變
_GRAB_JUMP = .5         # 按住上這麼久仍不動，改用跳躍抓繩
_JUMP_ATTEMPTS = 3      # 下跳連續幾次高度沒變才放棄
_STUCK_TAPS = 6         # 連續幾次微調點按都沒移動就放棄
_PATH_STEP = 5          # 沿路按鍵預設：每走 5 格（約 0.2 秒路程）按一下
_PATH_TAP = .1
_QUICK_FINISH_TOL = 3   # 誤差 ≥ 3 格才在放開後直接完成（不等停穩）
_SLIDE_ERROR = 2        # 滑行距離預估的誤差（格）
# 轉身按法實機測試（2026-10-23 左牆 10 次）：等 0.5 秒、方向 0.35 秒、重疊 0.1 秒 5/5 成功；
# 馬上轉身＋方向 0.2 秒只有 1/2，點一下方向鍵 1/2。
_TURN_COOLDOWN = .5     # 上一段技能放開後等多久才轉身（技能動作還沒結束時轉不了身）
_FACE_LEAD = .35        # 先按住方向鍵多久再按技能
_FACE_OVERLAP = .1      # 技能按下後方向鍵再按住多久才放
_DASH_GAIN = 8.0        # 往目標前進超過這麼多格才算衝刺有效
_HOLD_STUCK = 2.5       # 按住攻擊鍵這麼久沒前進才算卡住（打怪時會停一下）
_TELEPORT_BACK = 10     # 往反方向跳這麼多格＝面向錯了
_WRONG_WAY = 25         # 衝刺往反方向超過這麼多格（約半次衝刺）＝轉身方向猜錯
_HOLD_SETTLE = 1.5      # 衝刺前最多等上一段動作停下多久
_HOLD_REPEAT = .05      # 按住技能時像實體鍵盤自動重複一樣重送按下（遊戲忙碌時會漏收第一下）


class MinimapMover:
    """以小地圖黃點做閉迴路移動。所有輸入/讀取/時間皆由呼叫端注入。

    read() -> (x, y) | None：視窗相對座標（可含小數）。
    press(key)/release(key)：按下/放開；呼叫端負責實際輸入與停止檢查。
    interrupted() -> bool：按住途中需要先放鍵讓出（例如圖片順序輸入提示）。
    idle()：未按任何鍵時的安全點（呼叫端可在此暫停/恢復）。
    回傳 True＝到達容許誤差內；False＝逾時、黃點消失或卡住。
    """

    def __init__(self, read, press, release, sleep, clock, *, interrupted=lambda: False,
                 idle=lambda: None, log=lambda message: None, path_key=None,
                 path_gate=None, path_step=_PATH_STEP, hold_keys=(), face_reverse=False):
        self._read, self._press, self._release = read, press, release
        self._sleep, self._clock = sleep, clock
        self._interrupted, self._idle, self._log = interrupted, idle, log
        self._path_key = path_key
        self._path_gate = path_gate          # () -> bool：畫面上有目標怪物才按
        self._path_step = path_step
        # 走路全程一起按住的鍵（例如攻擊 C）：錄製學到「按住右＋C 走到某處」時使用。
        self._hold_keys = tuple(hold_keys)
        self.face_reverse = face_reverse     # 衝刺技能往背後衝：轉身要按反方向
        self._path_from = None
        self.path_tapped_at = None
        self._yield = False
        self._held: list[str] = []
        self.slide = _INITIAL_SLIDE
        self.last = None

    def _down(self, key):
        self._held.append(key)
        self._press(key)

    def _up(self, key):
        self._held.remove(key)
        self._release(key)

    def _must_yield(self):
        if self._interrupted():
            self._yield = True
        return self._yield

    def _checkpoint(self):
        """每輪開頭的安全點（此時沒有按住任何鍵）。"""
        self._yield = False
        self._idle()

    def _path_tap(self, x):
        """沿路按鍵：每走 _PATH_STEP 格點一下。人物因按鍵停住時不會連按。"""
        if self._path_key is None or x is None:
            return
        if self._path_from is None:
            self._path_from = x
            return
        if abs(x - self._path_from) < self._path_step:
            return
        self._path_from = x
        if self._path_gate is not None and not self._path_gate():
            return
        self._down(self._path_key)
        self._sleep(_PATH_TAP)
        self._up(self._path_key)
        self._path_from = x
        self.path_tapped_at = self._clock()

    def _stuck_sec(self):
        # 按住攻擊鍵時打怪會停頓，多給一點時間才算被擋住。
        return _STUCK_SEC * 2 if self._hold_keys else _STUCK_SEC

    def _stuck_message(self):
        if self._hold_keys:
            return (f'按住方向鍵和 {"+".join(self._hold_keys)} 黃點仍未移動，'
                    '可能被擋住或一直在打怪')
        if self._path_key is not None:
            return (f'按方向鍵黃點仍未移動，可能被擋住，或沿路按的 {self._path_key} '
                    '讓人物一直停在原地')
        return '按方向鍵黃點仍未移動，可能被擋住'

    def release_all(self):
        while self._held:
            self._release(self._held.pop())

    def settle(self, limit=1.0, *, after_input=True, y_only=False):
        """等黃點連續 _SETTLE_STABLE 秒不動（y_only＝只看高度，左右滑動不算）；
        超過 limit 回傳最後一次讀數。"""
        if after_input:
            self._sleep(_RESPONSE)
        end = self._clock() + limit
        last, since = None, None
        while True:
            pos = self._read()
            now = self._clock()
            if pos is not None:
                self.last = pos
                if (last is not None and (y_only or abs(pos[0]-last[0]) < .3)
                        and abs(pos[1]-last[1]) < .3):
                    if now - since >= _SETTLE_STABLE:
                        return pos
                else:
                    last, since = pos, now
            if now >= end:
                return pos if pos is not None else last
            self._sleep(_POLL)

    def peek(self, limit=.3):
        """立即讀一次黃點，不等停穩（手扶梯一直在動時用）；暫時讀不到最多重試 limit 秒。"""
        end = self._clock() + limit
        while True:
            pos = self._read()
            if pos is not None:
                self.last = pos
                return pos
            if self._clock() >= end:
                return None
            self._sleep(_POLL)

    def walk(self, tx, tolerance, deadline):
        try:
            still_taps, last_x, pressed = 0, None, False
            while self._clock() < deadline:
                self._checkpoint()
                # 還沒按過鍵時不必等按鍵反應時間，只確認黃點已停。
                pos = self.settle(after_input=pressed)
                pressed = True
                if pos is None:
                    return False
                if last_x is not None:
                    still_taps = still_taps + 1 if abs(pos[0] - last_x) < 1 else 0
                    if still_taps >= _STUCK_TAPS:
                        self._log(self._stuck_message())
                        return False
                last_x = None
                dx = tx - pos[0]
                if abs(dx) <= tolerance:
                    return True
                key, sign = ('right', 1) if dx > 0 else ('left', -1)
                if abs(dx) <= self.slide + 1:
                    # 接近目標：短按逐步修正，50ms≈1px。
                    tap = .05 if abs(dx) <= 2 else .1 if abs(dx) <= 4 else .15
                    # 上一次點按沒讓黃點換格：逐次加長，避免卡在像素邊界。
                    tap = min(.2, tap * (1 + still_taps))
                    self._down(key)
                    self._sleep(tap)
                    self._up(key)
                    last_x = pos[0]
                    continue
                for held in self._hold_keys:
                    self._down(held)
                self._down(key)
                started, moved_at, origin = self._clock(), None, pos[0]
                at_release, cur = pos[0], pos
                while self._clock() < deadline and not self._must_yield():
                    cur = self._read()
                    now = self._clock()
                    if cur is None:
                        cur = (at_release, pos[1])
                    else:
                        self._path_tap(cur[0])
                        at_release = cur[0]
                        if abs(cur[0] - origin) >= 1:
                            moved_at, origin = now, cur[0]
                        if (tx - cur[0]) * sign <= self.slide:
                            break
                    # 最後一次有進展（開始、移動或沿路按鍵的僵直起點）後太久不動才算被擋。
                    progress = max(started, moved_at or started, self.path_tapped_at or started)
                    if now - progress >= self._stuck_sec():
                        self.release_all()
                        self._log(self._stuck_message())
                        return False
                    self._sleep(_POLL)
                self.release_all()
                landing = at_release + self.slide * sign
                if (moved_at is not None and tolerance >= _QUICK_FINISH_TOL
                        and abs(tx - landing) <= tolerance - _SLIDE_ERROR):
                    # 誤差寬鬆且預估滑行後停在範圍內：不等停穩，直接做下一個動作。
                    self.last = (landing, cur[1])
                    return True
                final = self.settle()
                if final is not None and moved_at is not None:
                    observed = (final[0] - at_release) * sign
                    self.slide = min(15., max(1., (self.slide + observed) / 2))
            return False
        finally:
            self.release_all()

    def hold_move(self, tx, tolerance, deadline):
        """衝刺型攻擊移動：按住方向鍵轉身、按住期間按下 hold_keys（例如 C），一直按住直到
        黃點到達或超過目標（誤差 tolerance 內）。往反方向衝＝轉身方向猜錯，換邊一次；
        兩邊都衝不動就改用走的。"""
        if not self._hold_keys:
            raise ValueError("hold_move 需要 hold_keys")
        try:
            self._checkpoint()
            # 上一段衝刺可能還在進行（小地圖也慢半拍）：等完全停下再轉身。
            pos = self.settle(after_input=True, limit=_HOLD_SETTLE)
            if pos is None:
                return False
            sign = 1 if tx > pos[0] else -1
            if (tx - pos[0]) * sign <= tolerance:
                return True

            def face():
                """照實錄：按住方向鍵 → 按住期間按下技能 → 再放開方向鍵。回傳起點讀數。"""
                forward = sign > 0
                key = 'right' if forward != self.face_reverse else 'left'
                self._sleep(_TURN_COOLDOWN)
                self._down(key)
                self._sleep(_FACE_LEAD)
                for held in self._hold_keys:
                    self._down(held)
                self._sleep(_FACE_OVERLAP)
                self._up(key)
                return self.last or pos

            base = face()
            best, progress = base[0], self._clock()
            advanced = flipped = False
            judge_after = self._clock() + _RESPONSE     # 小地圖慢半拍，之前的移動不算
            repeat_at = self._clock() + _HOLD_REPEAT

            while self._clock() < deadline and not self._must_yield():
                cur = self._read()
                now = self._clock()
                if now >= repeat_at:
                    for held in self._hold_keys:
                        if held in self._held:
                            self._press(held)
                    repeat_at = now + _HOLD_REPEAT
                if cur is not None:
                    self.last = cur
                    if (tx - cur[0]) * sign <= tolerance:
                        return True
                    if now < judge_after:
                        base = cur
                        best = cur[0]
                    elif (cur[0] - best) * sign >= 1:
                        best, progress = cur[0], now
                        # 按方向鍵轉身時會順便走一兩格，不算衝刺有效。
                        advanced = advanced or (cur[0] - base[0]) * sign >= _DASH_GAIN
                    elif (cur[0] - base[0]) * sign <= -_WRONG_WAY and not advanced:
                        if flipped:
                            self._log(f'按住 {"+".join(self._hold_keys)} 兩種轉身都往反方向衝')
                            return False
                        flipped = True
                        self._flip('衝刺方向和轉身相反')
                        base = face()
                        best, progress = base[0], self._clock()
                        judge_after = self._clock() + _RESPONSE
                        continue
                if now - progress >= _HOLD_STUCK:
                    if not advanced and not flipped:
                        flipped = True
                        self._flip('衝刺完全沒往目標前進')
                        base = face()
                        best, progress = base[0], self._clock()
                        judge_after = self._clock() + _RESPONSE
                        continue
                    if not advanced:
                        # 兩邊轉身都衝不動（例如貼在牆角）：放開技能改用走的。
                        self.release_all()
                        self._log('衝刺兩個方向都沒前進，改用走的')
                        return self._walk_plain(tx, tolerance, deadline)
                    self._log(f'按住 {"+".join(self._hold_keys)} 黃點沒有往目標前進，'
                              '可能到平台盡頭或被擋住')
                    return False
                self._sleep(_POLL)
            return False
        finally:
            self.release_all()

    def _flip(self, why):
        """換另一邊轉身：放開技能、等衝刺完全停下，之後都用這個方向。"""
        self.release_all()
        self.face_reverse = not self.face_reverse
        self._log(f'{why}，改按另一邊轉身')
        self.settle(after_input=True, limit=_HOLD_SETTLE)

    def _walk_plain(self, tx, tolerance, deadline):
        held, self._hold_keys = self._hold_keys, ()
        try:
            return self.walk(tx, tolerance, deadline)
        finally:
            self._hold_keys = held

    def rope(self, tx, ty, x_tolerance, tolerance, jump_key, deadline):
        """先對齊繩子 X，再按住上/下直到 Y；繩子末端在頭上時按住上再跳一下抓繩。"""
        pos = self.settle(after_input=False)
        if pos is None:
            return False
        # 繩子可抓範圍很窄：X 一律對齊到 ±1 以內。
        x_tolerance = min(x_tolerance, 1)
        if abs(tx - pos[0]) > x_tolerance and not self.walk(tx, x_tolerance, deadline):
            return False
        try:
            progressed = False
            while self._clock() < deadline:
                self._checkpoint()
                pos = self.settle()
                if pos is None:
                    return False
                dy = ty - pos[1]
                if abs(dy) <= tolerance:
                    return True
                key, sign = ('down', 1) if dy > 0 else ('up', -1)
                self._down(key)
                last_y, last_change, jumped, moved = pos[1], self._clock(), False, False
                while self._clock() < deadline and not self._must_yield():
                    cur = self._read()
                    now = self._clock()
                    if cur is not None:
                        if abs(cur[1] - last_y) >= 1:
                            last_y, last_change, moved = cur[1], now, True
                        if (ty - cur[1]) * sign <= tolerance:
                            break
                    idle_for = now - last_change
                    if (key == 'up' and not moved and not progressed and not jumped
                            and idle_for >= _GRAB_JUMP):
                        # 繩子末端比頭高：按住上的同時跳一下。
                        self._down(jump_key)
                        self._sleep(.1)
                        self._up(jump_key)
                        jumped, last_change = True, self._clock()
                        continue
                    if idle_for >= _STUCK_SEC:
                        break
                    self._sleep(_POLL)
                self._up(key)
                after = self.settle()
                if after is not None and abs(after[1] - pos[1]) < 1:
                    self._log('已到繩子盡頭，目標高度超出繩子範圍' if progressed
                              else '按住上/下仍抓不到繩子，請確認目標 X 是繩子位置')
                    return False
                progressed = True
            return False
        finally:
            self.release_all()

    def down_jump(self, ty, tolerance, jump_key, deadline, *, quick=False):
        """quick：第一次不等高度停下（被手扶梯往上帶時高度一直變，等下去就到上層了）。"""
        unchanged, jumped, landed = 0, False, None
        try:
            while self._clock() < deadline:
                self._checkpoint()
                # 第一次只需確認高度；走路剛放開還在滑行也能直接下跳。
                # 下跳後已等落地站穩，直接用那次讀數，不再多等一次。
                if landed is not None:
                    pos, landed = landed, None
                elif jumped:
                    pos = self.settle()
                elif quick:
                    pos = self.peek()
                else:
                    pos = self.settle(after_input=False, y_only=True)
                if pos is None:
                    return False
                dy = ty - pos[1]
                if abs(dy) <= tolerance:
                    return True
                if dy < 0:
                    self._log('已低於目標高度，下跳無法往上')
                    return False
                self._down('down')
                self._sleep(_DIRECTION_LEAD)
                self._down(jump_key)
                self._sleep(.1)
                self._up(jump_key)
                self._sleep(_DIRECTION_LEAD)
                self._up('down')
                jumped = True
                changed_by = self._clock() + _FALL_START
                while self._clock() < changed_by:
                    cur = self._read()
                    if cur is not None and abs(cur[1] - pos[1]) >= 1:
                        break
                    self._sleep(_POLL)
                after = self.settle(limit=2.5, after_input=False)   # 上面已等到高度開始變化
                if after is not None and after[1] - pos[1] < 1:
                    # 被怪物撞到硬直時下跳會沒反應：重新站穩再試，連續多次才放棄。
                    unchanged += 1
                    if unchanged >= _JUMP_ATTEMPTS:
                        self._log('連續下跳高度都沒有改變，可能已在最底層或一直被怪物撞開')
                        return False
                else:
                    unchanged = 0
                landed = after
            return False
        finally:
            self.release_all()
