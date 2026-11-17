import cv2
import numpy as np
import pytest

from keyboard_executor.core.chat_observer import ChatMessage, ChatObserver
from keyboard_executor.platforms.base import TextBox


def frame(*rows):
    image = np.full((max(1, len(rows)) * 28 + 12, 800, 3), 20, dtype=np.uint8)
    boxes = []
    for index, (text, color) in enumerate(rows):
        x, y = 8, 5 + index * 28
        bgr = {"green": (0, 245, 20), "white": (245, 245, 245),
               "blue": (245, 180, 60)}[color]
        cv2.putText(image, "Chat Text 123", (x + 2, y + 17),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, bgr, 1, cv2.LINE_AA)
        boxes.append(TextBox(text, x, y, 320, 22, .98))
    return image, boxes


def test_each_player_keeps_latest_fifty_without_evicting_another_player():
    observer = ChatObserver("自己")
    observer.observe(*frame(("乙：乙唯一一句", "white"), *[
        (f"甲：第{i}句", "white") for i in range(55)]))

    assert [m.text for m in observer.history_for("甲")] == [f"第{i}句" for i in range(5, 55)]
    assert [m.text for m in observer.history_for("乙")] == ["乙唯一一句"]
    assert len(observer.history) == 50


def test_our_replies_share_players_combined_channel_limit():
    observer = ChatObserver("自己", history_limit=3)
    observer.observe(*frame(("甲：地圖問題", "white"), ("乙：別人的問題", "white")))
    original = observer.history_for("甲")[0]
    observer.record_reply(original, "地圖回答")
    incoming = observer.observe(*frame(("甲[CH.301]>>密語問題", "green")))[0]
    observer.record_reply(incoming, "密語回答")

    history = observer.history_for("甲")
    assert [(m.channel, m.text, m.incoming, m.recipient) for m in history] == [
        ("map", "地圖回答", False, "甲"),
        ("whisper", "密語問題", True, ""),
        ("whisper", "密語回答", False, "甲"),
    ]
    assert [m.text for m in observer.history_for("甲", channel="map")] == ["地圖回答"]
    assert [m.text for m in observer.history_for("乙")] == ["別人的問題"]
    assert observer.history_for("自己") == []


def test_manual_whispers_are_routed_to_recipient_not_our_name():
    observer = ChatObserver("自己")
    observer.observe(*frame(("甲>>手動回甲", "green"), ("乙<<手動回乙", "green"),
                           ("自己：無指定玩家的地圖發言", "white"),
                           ("系統公告", "blue"), ("不安全名字!：不可歸檔", "white")))

    assert [(m.sender, m.text, m.incoming, m.recipient)
            for m in observer.history_for("甲")] == [("自己", "手動回甲", False, "甲")]
    assert [m.recipient for m in observer.history_for("乙")] == ["乙"]
    assert set(observer.conversations) == {"甲", "乙"}
    assert len(observer.history) == 5


def test_low_confidence_rows_do_not_enter_player_history_or_images():
    observer = ChatObserver("自己")
    image, boxes = frame(("甲[CH.301]>>不能信任的辨識", "green"))
    box = boxes[0]
    boxes = [TextBox(box.text, box.x, box.y, box.width, box.height, .5)]
    observer.observe(image, boxes)

    assert observer.history_for("甲") == []
    assert observer.image_for("甲") is None


def test_full_normalized_names_share_channel_changes_but_not_similar_names():
    observer = ChatObserver("自己")
    observer.observe(*frame(("Ａｌｉｃｅ[CH.301]>>第一句", "green")))
    observer.observe(*frame(("Alice[CH-484]>>第二句", "green"),
                           ("Alicf：別人的內容", "white")))

    assert [m.text for m in observer.history_for(" Ａｌｉｃｅ ")] == ["第一句", "第二句"]
    assert [m.text for m in observer.history_for("Alicf")] == ["別人的內容"]
    assert observer.history_for("alice") == []
    assert set(observer.conversations) == {"Alice", "Alicf"}


@pytest.mark.parametrize("channel,initial,current", [
    ("map", "相似名字甲：", "相似名字乙："),
    ("whisper", "相似名字甲[CH.301]>>", "相似名字乙[CH.301]>>"),
])
def test_same_long_text_from_similar_names_is_not_swallowed(channel, initial, current):
    observer = ChatObserver("自己")
    text = "這是很長而且兩個玩家都可能發出的相同文字所以不能因為看起來很像就合併姓名"
    color = "white" if channel == "map" else "green"
    observer.observe(*frame((initial + text, color)))

    result = observer.observe(*frame((current + text, color)))

    assert [m.sender for m in result] == ["相似名字乙"]
    assert [m.sender for m in observer.history_for("相似名字甲")] == ["相似名字甲"]
    assert [m.sender for m in observer.history_for("相似名字乙")] == ["相似名字乙"]


def test_trust_change_is_a_new_message_even_when_raw_text_is_identical():
    observer = ChatObserver("自己")
    text = "甲：這是一段不能讓不同顏色的系統公告搶走新訊息身分的長文字"
    observer.observe(*frame((text, "blue")))

    result = observer.observe(*frame((text, "white")))

    assert [m.sender for m in result] == ["甲"]


def test_recorded_replies_still_deduplicate_visible_echoes_in_both_channels():
    observer = ChatObserver("自己")
    observer.observe(*frame(("甲：第一題", "white"), ("乙[CH.301]>>第二題", "green")))
    observer.record_reply(observer.history_for("甲")[0], "答甲")
    observer.record_reply(observer.history_for("乙")[0], "答乙")

    observer.observe(*frame(("自己：答甲", "white"), ("乙>>答乙", "green")))

    assert [m.text for m in observer.history_for("甲")] == ["第一題", "答甲"]
    assert [m.text for m in observer.history_for("乙")] == ["第二題", "答乙"]
    assert len(observer.history) == 4


def test_returned_histories_and_conversation_mapping_are_defensive():
    observer = ChatObserver("自己")
    observer.observe(*frame(("甲：保留我", "white")))
    observer.history_for("甲").clear()
    exported = observer.conversations
    exported["甲"].clear()
    exported["假玩家"] = []
    observer.history.clear()

    assert [m.text for m in observer.history_for("甲")] == ["保留我"]
    assert set(observer.conversations) == {"甲"}
    assert len(observer.history) == 1


def test_image_for_stacks_only_players_trusted_rows_and_filters_channel():
    observer = ChatObserver("自己")
    image, boxes = frame(("甲：地圖問題", "white"), ("乙：別人的秘密", "white"),
                         ("系統公告", "blue"), ("甲>>手動密語", "green"),
                         ("自己：無指定玩家的話", "white"))
    # Unique pixels inside each row make accidental full-frame/other-player
    # inclusion observable without an OCR engine or a live window.
    for index, box in enumerate(boxes):
        image[box.y + 1, box.x + 300] = (index + 1, 70, 90)
    expected_map = image[5:27, 8:328].copy()
    expected_whisper = image[89:111, 8:328].copy()
    observer.observe(image, boxes)

    assert np.array_equal(observer.image_for("甲"), np.vstack([expected_map, expected_whisper]))
    assert np.array_equal(observer.image_for("甲", channel="map"), expected_map)
    assert np.array_equal(observer.image_for("甲", channel="whisper"), expected_whisper)
    assert observer.image_for("自己") is None
    assert observer.image_for("不存在") is None
    image[:] = 0
    returned = observer.image_for("甲")
    returned[:] = 0
    assert np.array_equal(observer.image_for("甲", channel="map"), expected_map)


def test_images_follow_latest_frame_even_if_it_has_no_new_messages_or_no_ocr():
    observer = ChatObserver("自己")
    first = frame(("甲：第一句", "white"), ("乙：第二句", "white"))
    observer.observe(*first)
    next_image, next_boxes = frame(("乙：第二句", "white"))
    next_image[6, 310] = (77, 80, 90)
    assert observer.observe(next_image, next_boxes) == []

    assert observer.image_for("甲") is None
    assert np.array_equal(observer.image_for("乙"), next_image[5:27, 8:328])
    observer.observe(np.zeros_like(next_image), [])
    assert observer.image_for("乙") is None
    assert observer.observe(*first) == []


def test_player_callback_excludes_unassigned_rows_and_duplicate_observations():
    appended = []
    observer = ChatObserver("自己", on_message=lambda player, message: appended.append((player, message)))
    baseline = frame(("甲：問題", "white"), ("乙>>手動回答", "green"),
                     ("公告", "blue"), ("自己：自己的地圖話", "white"))
    observer.observe(*baseline)
    observer.observe(*baseline)
    observer.record_reply(observer.history_for("甲")[0], "回答")

    assert [(player, message.text) for player, message in appended] == [
        ("甲", "問題"), ("乙", "手動回答"), ("甲", "回答")]


def test_restore_is_defensive_bounded_and_advances_ids_without_callbacks():
    appended = []
    observer = ChatObserver("自己", on_message=lambda *args: appended.append(args))
    saved = {" Ａｌｉｃｅ ": [ChatMessage(i + 100, "map", "Alice", f"舊{i}") for i in range(55)],
             "乙": [ChatMessage(900, "whisper", "乙", "保留乙")]}
    observer.restore_conversations(saved)
    saved[" Ａｌｉｃｅ "].clear()
    saved.clear()

    assert [m.text for m in observer.history_for("Alice")] == [f"舊{i}" for i in range(5, 55)]
    assert [m.text for m in observer.history_for("乙")] == ["保留乙"]
    assert appended == []
    assert observer.observe(*frame(("Alice：新句", "white"))) == []
    newest = observer.history_for("Alice")[-1]
    assert newest.id > 900
    assert [(name, msg.text) for name, msg in appended] == [("Alice", "新句")]


def test_restored_baseline_deduplicates_per_player_preserving_repeat_occurrences():
    appended = []
    observer = ChatObserver("自己", on_message=lambda player, msg: appended.append((player, msg.text)))
    observer.restore_conversations({
        "甲": [ChatMessage(1, "whisper", "甲", "重複"),
               ChatMessage(2, "whisper", "甲", "中間"),
               ChatMessage(3, "whisper", "甲", "重複")],
        "乙": [ChatMessage(4, "whisper", "乙", "重複")],
    })
    restored_frame = frame(("甲[CH-484]>>中間", "green"),
                           ("甲[CH-484]>>重複", "green"),
                           ("甲[CH-484]>>新句", "green"),
                           ("甲[CH-484]>>重複", "green"),
                           ("乙[CH.301]>>重複", "green"),
                           ("丙[CH.301]>>重複", "green"))

    assert observer.observe(*restored_frame) == []
    assert [m.text for m in observer.history_for("甲")] == ["重複", "中間", "重複", "新句", "重複"]
    assert [m.text for m in observer.history_for("乙")] == ["重複"]
    assert [m.text for m in observer.history_for("丙")] == ["重複"]
    assert appended == [("甲", "新句"), ("甲", "重複"), ("丙", "重複")]
    assert observer.observe(*restored_frame) == []
    assert len(appended) == 3


def test_restored_outgoing_whisper_is_not_written_again_on_first_frame():
    observer = ChatObserver("自己")
    observer.restore_conversations({"甲": [
        ChatMessage(1, "whisper", "甲", "問題"),
        ChatMessage(2, "whisper", "自己", "回答", False, "甲"),
    ]})
    observer.observe(*frame(("甲[CH.301]>>問題", "green"), ("甲>>回答", "green")))

    assert [(m.text, m.incoming, m.recipient) for m in observer.history_for("甲")] == [
        ("問題", True, ""), ("回答", False, "甲")]
