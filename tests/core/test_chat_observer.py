from dataclasses import replace

import cv2
import numpy as np
import pytest

from keyboard_executor.platforms.base import TextBox


COLORS = {
    "green": (0, 245, 20),
    "white": (245, 245, 245),
    "blue": (245, 180, 60),
    "yellow": (0, 220, 245),
    "dark": (25, 35, 20),
}


def draw_box(image, text, x, y, color="white", confidence=0.98, width=320,
             background=None):
    if background is not None:
        image[y:y + 22, x:x + width] = background
    # Real foreground strokes, with most of each OCR box showing background.
    cv2.putText(image, "Chat Text 123", (x + 2, y + 17),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLORS[color], 1, cv2.LINE_AA)
    return TextBox(text, x, y, width, 22, confidence)


def frame(*rows):
    image = np.full((max(1, len(rows)) * 28 + 12, 1000, 3), 20, dtype=np.uint8)
    boxes = [draw_box(image, text, 6, 5 + i * 28, color)
             for i, (text, color) in enumerate(rows)]
    return image, boxes


@pytest.fixture
def observer():
    from keyboard_executor.core.chat_observer import ChatObserver
    return ChatObserver("胖胖布丁幻影")


def test_first_frame_is_context_only_and_unchanged_frame_does_not_repeat(observer):
    image, boxes = frame(("慕尼歌劇院[CH.301]>>借我測試", "green"), ("朋友：嗨", "white"))
    assert observer.observe(image, boxes) == []
    assert [(m.channel, m.sender, m.text) for m in observer.history] == [
        ("whisper", "慕尼歌劇院", "借我測試"), ("map", "朋友", "嗨")]
    assert observer.observe(image, boxes) == []
    assert len(observer.history) == 2


@pytest.mark.parametrize("chat,color", [
    ("慕尼歌劇院[CH.301]>>你好", "green"), ("朋友：你在嗎", "white")])
def test_fixed_chat_input_footer_does_not_hide_new_message(observer, chat, color):
    observer.observe(*frame(("系統準備好了", "blue"), ("對所有人7", "white")))
    current = frame(("系統準備好了", "blue"), (chat, color), ("對所有人7", "white"))
    result = observer.observe(*current)
    assert len(result) == 1
    assert result[0].text in ("你好", "你在嗎")
    assert observer.observe(*current) == []


def test_repeated_system_banner_below_whisper_cannot_hide_new_whisper(observer):
    observer.observe(*frame(("遠征隊你們才是真正的時間勝利者", "blue"),
                           ("路人：舊對話", "white")))
    current = frame(("慕尼歌劇院[CH.301]>>你好", "green"),
                    ("遠征隊你們才是真正的時間勝利者", "blue"))
    assert [m.sender for m in observer.observe(*current)] == ["慕尼歌劇院"]
    assert observer.observe(*current) == []


def test_footer_does_not_replay_old_whispers_when_frame_scrolls_back(observer):
    old = frame(("甲[CH.301]>>舊訊息", "green"), ("對所有人7", "white"))
    observer.observe(*old)
    current = frame(("甲[CH.301]>>舊訊息", "green"),
                    ("乙[CH.355]>>新訊息", "green"), ("對所有人7", "white"))
    assert [m.sender for m in observer.observe(*current)] == ["乙"]
    assert observer.observe(*old) == []
    assert observer.observe(*current) == []


@pytest.mark.parametrize("include_footer", [False, True])
def test_same_whisper_sent_again_after_banner_is_new(observer, include_footer):
    chat = ("朋友[CH.301]>>你好", "green")
    banner = ("系統公告", "blue")
    footer = [("對所有人7", "white")] if include_footer else []
    observer.observe(*frame(chat, banner, *footer))
    current = frame(banner, chat, *footer)
    assert [m.text for m in observer.observe(*current)] == ["你好"]
    assert observer.observe(*current) == []


def test_recovered_middle_ocr_row_does_not_replay_already_seen_rows(observer):
    first = ("甲[CH.301]>>第一句", "green")
    middle = ("乙[CH.355]>>第二句", "green")
    last = ("丙[CH.284]>>第三句", "green")
    footer = ("對所有人7", "white")
    observer.observe(*frame(first, last, footer))
    current = frame(first, middle, last, footer)
    assert [m.sender for m in observer.observe(*current)] == ["乙"]
    assert observer.observe(*current) == []
    assert observer.observe(*frame(first, last, footer)) == []
    assert observer.observe(*current) == []


def test_only_green_whisper_and_white_map_messages_trigger(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    result = observer.observe(*frame(
        ("系統準備好了", "blue"), ("慕尼歌劇院[CH.301]>>借我測試", "green"),
        ("朋友：你好啊", "white"), ("廣播者：全服公告", "yellow")))
    assert [(m.channel, m.sender, m.text) for m in result] == [
        ("whisper", "慕尼歌劇院", "借我測試"), ("map", "朋友", "你好啊")]
    assert observer.history[-1].channel == "other"
    assert "全服公告" in observer.history[-1].text
    assert len({m.id for m in observer.history}) == 4


def test_incoming_whisper_with_channel_tag_uses_clean_sender(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    result = observer.observe(*frame(("系統準備好了", "blue"),
                                    ("慕尼歌劇院[CH-301]>> ~", "green")))
    assert [(m.channel, m.sender, m.text, m.incoming) for m in result] == [
        ("whisper", "慕尼歌劇院", "~", True)]


def test_channel_tag_does_not_bypass_sender_validation(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    assert observer.observe(*frame(("系統準備好了", "blue"),
                                  ("bad/name[CH-301]>> 你好", "green"))) == []


def test_tagged_whisper_still_triggers_when_ocr_misses_punctuation_body(observer):
    # 使用者的真實截圖只有「~」，Paddle 辨識出名字與頻道卻漏掉正文。
    observer.observe(*frame(("系統準備好了", "blue")))
    result = observer.observe(*frame(("系統準備好了", "blue"),
                                    ("慕尼歌劇院[CH-301]>>", "green")))
    assert len(result) == 1
    assert result[0].sender == "慕尼歌劇院" and result[0].incoming
    assert "截圖" in result[0].text


@pytest.mark.parametrize("background", [(135, 188, 151), (0, 245, 20)])
def test_green_background_dark_text_is_only_context(observer, background):
    observer.observe(*frame(("系統準備好了", "blue")))
    image, boxes = frame(("系統準備好了", "blue"))
    image = np.pad(image, ((0, 28), (0, 0), (0, 0)), constant_values=20)
    boxes.append(draw_box(image, "世界頻道<<不是密語", 6, 33, "dark",
                          background=background))
    assert observer.observe(image, boxes) == []
    assert observer.history[-1].channel == "other"


def test_group_split_ocr_boxes_in_same_visual_line_and_sort_by_x(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    image = np.full((75, 1000, 3), 20, dtype=np.uint8)
    boxes = [draw_box(image, "借我測試", 345, 35, "green"),
             draw_box(image, "系統準備好了", 6, 5, "blue"),
             draw_box(image, "慕尼歌劇院[CH.301]>>", 6, 33, "green")]
    result = observer.observe(image, boxes)
    assert [(m.sender, m.text) for m in result] == [("慕尼歌劇院", "借我測試")]


def test_self_messages_and_outgoing_whispers_never_trigger(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    assert observer.observe(*frame(
        ("系統準備好了", "blue"), ("胖胖布丁幻影：asd", "white"),
        ("慕尼歌劇院>>已經回覆", "green"), ("胖胖布丁幻影[CH.301]>>自己的文字", "green"),
        ("慕尼歌劇院<<送出的測試", "green"))) == []
    assert len(observer.history) == 5
    assert all(not message.incoming for message in observer.history[1:])


def test_scrolling_keeps_overlap_and_all_appended_messages(observer):
    observer.observe(*frame(("甲：第一句", "white"), ("乙：第二句", "white"),
                           ("丙：第三句", "white")))
    result = observer.observe(*frame(("乙：第二句", "white"), ("丙：第三句", "white"),
                                    ("丁：第四句", "white"), ("戊[CH.301]>>第五句", "green")))
    assert [(m.sender, m.text) for m in result] == [("丁", "第四句"), ("戊", "第五句")]
    assert len(observer.history) == 5


def test_identical_new_message_below_overlap_is_still_new(observer):
    observer.observe(*frame(("甲：嗨", "white"), ("乙：你好", "white")))
    result = observer.observe(*frame(("甲：嗨", "white"), ("乙：你好", "white"),
                                    ("乙：你好", "white")))
    assert len(result) == 1
    assert result[0].text == "你好"
    assert result[0].id != observer.history[-2].id


def test_scrolling_repeated_lines_does_not_hide_last_new_repeat(observer):
    observer.observe(*frame(("甲：嗨", "white"), ("乙：你好", "white"),
                           ("甲：嗨", "white")))
    result = observer.observe(*frame(("乙：你好", "white"), ("甲：嗨", "white"),
                                    ("甲：嗨", "white")))
    assert [(m.sender, m.text) for m in result] == [("甲", "嗨")]


def test_appended_repeats_of_older_messages_are_new_after_latest_overlap(observer):
    observer.observe(*frame(("甲：嗨", "white"), ("乙：你好", "white"),
                           ("丙：準備好了", "white"), ("丁：出發吧", "white")))
    result = observer.observe(*frame(("丁：出發吧", "white"), ("甲：嗨", "white"),
                                    ("乙：你好", "white")))
    assert [(m.sender, m.text) for m in result] == [("甲", "嗨"), ("乙", "你好")]


def test_same_frame_with_repeated_lines_is_not_replayed(observer):
    image, boxes = frame(("甲：嗨", "white"), ("乙：你好", "white"), ("甲：嗨", "white"))
    observer.observe(image, boxes)
    assert observer.observe(image, boxes) == []
    assert len(observer.history) == 3


def test_unicode_and_whitespace_ocr_jitter_do_not_retrigger(observer):
    observer.observe(*frame(("Alice：Hello world １２３", "white")))
    assert observer.observe(*frame(("Alice : Hello  world 123", "white"))) == []
    assert len(observer.history) == 1


def test_small_ocr_jitter_in_a_long_existing_line_does_not_retrigger(observer):
    observer.observe(*frame(("Alice：Could you help with this quest today?", "white")))
    assert observer.observe(*frame(("Alice：Could you he1p with this quest today?", "white"))) == []
    assert len(observer.history) == 1


def test_short_different_messages_are_not_fuzzy_deduplicated(observer):
    observer.observe(*frame(("甲：123", "white")))
    result = observer.observe(*frame(("甲：123", "white"), ("甲：124", "white")))
    assert [m.text for m in result] == ["124"]


@pytest.mark.parametrize("readings", [
    ["甲史達兔[CH.301]>>哈樓", "甲史達兔[CH.301]>>哈搜", "甲史達兔[CH.301]>>哈接"],
    ["甲史達兔[CH.301]>>安安在嘛", "甲史達兔[CH.301]>>安安在嘛e", "甲史達兔[CH.301]>>三安安在嘛"],
    ["甲史達兔[CH.301]>>安安在嘛", "甲史達免[CH.301]>>安安在嘛", "甲史達兔[CH.301]>>安安在嘛"],
])
def test_same_row_reread_by_ocr_is_not_a_new_message(observer, readings):
    # 實機：同一則密語每張畫面被讀成不同字，舊讀法消失、新讀法出現在同一列。
    observer.observe(*frame(("系統公告", "blue")))
    first = observer.observe(*frame(("乙：在嗎", "white"), (readings[0], "green")))
    assert len(first) == 2
    for text in readings[1:] + readings:
        assert observer.observe(*frame(("乙：在嗎", "white"), (text, "green"))) == []


def test_similar_message_below_the_old_one_is_still_new(observer):
    observer.observe(*frame(("甲史達兔[CH.301]>>哈樓", "green")))
    result = observer.observe(*frame(("甲史達兔[CH.301]>>哈樓", "green"),
                                    ("甲史達兔[CH.301]>>哈搜", "green")))
    assert [m.text for m in result] == ["哈搜"]


def test_blank_ocr_does_not_erase_baseline(observer):
    previous = frame(("甲：你好", "white"))
    observer.observe(*previous)
    assert observer.observe(previous[0], []) == []
    assert observer.observe(*previous) == []
    assert len(observer.history) == 1


def test_initial_blank_frame_waits_for_first_readable_baseline(observer):
    assert observer.observe(np.zeros((20, 20, 3), dtype=np.uint8), []) == []
    assert observer.observe(*frame(("甲：啟動以前的話", "white"))) == []


def test_low_confidence_name_is_never_a_reply_recipient(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    image, boxes = frame(("系統準備好了", "blue"), ("猜出來的名字[CH.301]>>你好", "green"))
    low = boxes[-1]
    boxes[-1] = TextBox(low.text, low.x, low.y, low.width, low.height, 0.40)
    assert observer.observe(image, boxes) == []
    assert observer.history[-1].sender == ""
    assert "猜出來的名字" in observer.history[-1].text


@pytest.mark.parametrize("text,color", [
    ("沒有名字的文字", "white"), ("：沒有名字", "white"),
    ("不是密語格式：你好", "green"), ("甲<<", "green"),
    ("bad/name<<你好", "green"),
])
def test_ambiguous_lines_only_become_context(observer, text, color):
    observer.observe(*frame(("系統準備好了", "blue")))
    assert observer.observe(*frame(("系統準備好了", "blue"), (text, color))) == []
    assert len(observer.history) == 2


def test_scrolling_back_to_known_lines_does_not_retrigger(observer):
    first = frame(("甲：第一句", "white"), ("乙：第二句", "white"))
    observer.observe(*first)
    observer.observe(*frame(("乙：第二句", "white"), ("丙：第三句", "white")))
    assert observer.observe(*first) == []
    result = observer.observe(*frame(("乙：第二句", "white"), ("丙：第三句", "white"),
                                    ("丁：第四句", "white")))
    assert [m.sender for m in result] == ["丁"]
    assert len(observer.history) == 4


def test_record_reply_preserves_channel_and_limits_history():
    from keyboard_executor.core.chat_observer import ChatObserver
    observer = ChatObserver("自己", history_limit=3)
    observer.observe(*frame(("系統準備好了", "blue")))
    message = observer.observe(*frame(("系統準備好了", "blue"),
                                      ("甲[CH.301]>>你好", "green")))[0]
    observer.record_reply(message, "你好，我在這裡")
    reply = observer.history[-1]
    assert (reply.channel, reply.sender, reply.text, reply.incoming) == (
        "whisper", "自己", "你好，我在這裡", False)
    observer.observe(*frame(("甲[CH.301]>>你好", "green"), ("乙：再問一次", "white")))
    assert len(observer.history) == 3
    assert observer.history[-2] == reply
    assert len({m.id for m in observer.history}) == 3


def test_recorded_reply_is_not_duplicated_when_ocr_sees_it(observer):
    observer.observe(*frame(("系統準備好了", "blue")))
    message = observer.observe(*frame(("系統準備好了", "blue"),
                                      ("甲[CH.301]>>你好", "green")))[0]
    observer.record_reply(message, "你好，我在這裡")
    assert observer.observe(*frame(("甲[CH.301]>>你好", "green"),
                                  ("甲>>你好，我在這裡", "green"))) == []
    assert len(observer.history) == 3


def test_history_property_cannot_mutate_internal_context(observer):
    observer.observe(*frame(("甲：你好", "white")))
    observer.history.clear()
    assert len(observer.history) == 1


@pytest.mark.parametrize("tag", ["[CH-2021>>", "|CH.301]>>", "[CH.301|>>", "(CH.301)>>", "[CH-202 >>"])
def test_small_window_tag_bracket_misreads_still_parse_whisper(observer, tag):
    # 視窗縮小時實測 ] 被讀成 1、[ 被讀成 |；姓名本身仍不修改。
    observer.observe(*frame(("系統公告", "blue")))
    new = observer.observe(*frame(("系統公告", "blue"), (f"甲史達兔{tag}在嘛", "green")))
    assert [(m.channel, m.sender, m.text) for m in new] == [("whisper", "甲史達兔", "在嘛")]


def test_far_low_confidence_background_box_does_not_spoil_whisper(observer):
    # 0.8 倍視窗實測：背景物件被讀成 'D'(0.42) 併進密語列，整列變成不可信。
    observer.observe(*frame(("系統公告", "blue")))
    image, boxes = frame(("系統公告", "blue"), ("甲史達兔[CH-202]>>在嘛", "green"))
    stray = replace(boxes[1], text="D", x=834, width=12, confidence=.42)
    new = observer.observe(image, boxes + [stray])
    assert [(m.sender, m.text) for m in new] == [("甲史達兔", "在嘛")]


def test_near_low_confidence_box_still_makes_row_untrusted(observer):
    observer.observe(*frame(("系統公告", "blue")))
    image, boxes = frame(("系統公告", "blue"), ("甲史達兔[CH-202]>>在嘛", "green"))
    near = replace(boxes[1], text="嗎", x=boxes[1].x + boxes[1].width + 4, width=14, confidence=.42)
    assert observer.observe(image, boxes + [near]) == []


def _read_name_many_times(observer, name, times=6):
    for i in range(times):
        observer.observe(*frame((f"系統{i}", "blue"), (f"{name}[CH.301]>>安安", "green")))


def test_occasional_misread_of_stable_name_is_not_a_new_message(observer):
    # 實機：胖胖布丁狂豹 讀到 47 次，偶爾讀成 胖胖布丁狂的 → 變成假的新密語又無法確認收件人。
    _read_name_many_times(observer, "胖胖布丁狂豹")
    assert observer.observe(*frame(("系統5", "blue"), ("胖胖布丁狂的[CH.301]>>安安", "green"))) == []
    assert observer.sees_incoming_sender("胖胖布丁狂豹", "whisper")


def test_new_message_under_misread_name_goes_to_stable_name(observer):
    _read_name_many_times(observer, "胖胖布丁狂豹")
    new = observer.observe(*frame(("系統5", "blue"), ("胖胖布丁狂豹[CH.301]>>安安", "green"),
                                  ("胖胖布丁狂的[CH.301]>>在嗎", "green")))
    assert [(m.sender, m.text) for m in new] == [("胖胖布丁狂豹", "在嗎")]


@pytest.mark.parametrize("stable,other,times", [
    ("小狗東", "小狗西", 6),               # 短姓名差一字可能是不同人
    ("胖胖布丁狂豹", "胖胖布丁狂的", 3),   # 穩定姓名讀到次數還不夠
    ("胖胖布丁狂豹", "胖胖布丁小的", 6),   # 差兩字：6 字姓名只容許一字
])
def test_misread_folding_stays_conservative(observer, stable, other, times):
    _read_name_many_times(observer, stable, times)
    new = observer.observe(*frame(("系統9", "blue"), (f"{other}[CH.301]>>在嗎", "green")))
    assert [(m.sender, m.text) for m in new] == [(other, "在嗎")]




def test_own_map_reply_under_another_character_name_is_not_answered():
    # 實機 2026-10-30：設定 胖胖布丁狂豹，實際角色 胖胖布丁幻影 → 自己跟自己對話。
    from keyboard_executor.core.chat_observer import ChatObserver
    observer = ChatObserver("胖胖布丁狂豹")
    rows = [("陳小晞：倪好", "white")]
    observer.observe(*frame(("系統準備好了", "blue")))
    assert len(observer.observe(*frame(("系統準備好了", "blue"), *rows))) == 1
    observer.record_reply(observer.history[-1], "笑死 连自己讲的话都能贴错字 你这复读机是当机了吧 XD")
    rows.append(("胖胖布丁幻影：笑死?自己?的?都能??字你?复?机是?机了吧XD", "white"))
    assert observer.observe(*frame(("系統準備好了", "blue"), *rows)) == []
    assert observer.self_aliases == set()        # 一次回音只略過，不當成自己
    observer.record_reply(observer.history[-2], "高山茶喝到字都打不順了喔 還一直貼")
    rows.append(("胖胖布丁幻影：高山茶喝到字都打不順了喔還一直貼", "white"))
    assert observer.observe(*frame(("系統準備好了", "blue"), *rows)) == []
    assert observer.self_aliases == {"胖胖布丁幻影"}
    # 之後這個名字說的任何話都不再觸發 AI
    rows.append(("胖胖布丁幻影：倪好有事义别一直倪好啦XD", "white"))
    assert observer.observe(*frame(("系統準備好了", "blue"), *rows)) == []
    assert observer.history_for("胖胖布丁幻影") == []


def test_other_player_with_different_text_still_triggers_after_a_reply():
    from keyboard_executor.core.chat_observer import ChatObserver
    observer = ChatObserver("胖胖布丁狂豹")
    observer.observe(*frame(("系統準備好了", "blue")))
    rows = [("系統準備好了", "blue"), ("陳小晞：倪好", "white")]
    observer.observe(*frame(*rows))
    observer.record_reply(observer.history[-1], "倪好阿 幹嘛啦 XD")
    rows.append(("陳小晞：你是機器人嗎", "white"))
    result = observer.observe(*frame(*rows))
    assert [(m.sender, m.text) for m in result] == [("陳小晞", "你是機器人嗎")]


def test_learned_self_name_survives_observer_rebuild():
    from keyboard_executor.core.chat_observer import ChatObserver
    old = ChatObserver("胖胖布丁狂豹")
    old._self_aliases.add("胖胖布丁幻影")
    new = ChatObserver("胖胖布丁狂豹")
    new.inherit_self(old)
    assert new.is_self("胖胖布丁幻影")
