"""AI 對話的內部多模態訊息格式與供應商轉換。

內部 user message 可帶 ``images``：每張圖片含 name/media_type/data/path。
``data`` 是不含 data-URL 前綴的 base64；``path`` 只供本機訂閱 provider 使用。
assistant message 維持純文字。這個模組只做資料轉換，無 Qt、無檔案 I/O。
"""
from __future__ import annotations

from copy import deepcopy


def message_images(message: dict) -> list[dict]:
    images = message.get("images") or []
    return [item for item in images if isinstance(item, dict)]


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """轉成 Chat Completions 的 text/image_url content parts。"""
    converted = []
    for message in messages:
        role = message.get("role", "user")
        text = str(message.get("content", ""))
        images = message_images(message) if role == "user" else []
        if not images:
            converted.append({"role": role, "content": text})
            continue
        content = []
        # 圖片先於意圖文字，兩家 vision 文件皆建議這個順序。
        for image in images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": (f"data:{image['media_type']};base64,"
                            f"{image['data']}")
                },
            })
        content.append({"type": "text", "text": text})
        converted.append({"role": role, "content": content})
    return converted


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """轉成 Anthropic Messages API 的 image/text content blocks。"""
    converted = []
    for message in messages:
        role = message.get("role", "user")
        text = str(message.get("content", ""))
        images = message_images(message) if role == "user" else []
        if not images:
            converted.append({"role": role, "content": text})
            continue
        content = []
        for image in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image["media_type"],
                    "data": image["data"],
                },
            })
        content.append({"type": "text", "text": text})
        converted.append({"role": role, "content": content})
    return converted


def render_subscription_history(messages: list[dict]) -> str:
    """把對話轉成訂閱 runtime 的文字 prompt，並標示附件順序。"""
    blocks = []
    image_no = 0
    for message in messages:
        lines = [f"[{message.get('role', 'user')}]", str(message.get("content", ""))]
        for image in message_images(message):
            image_no += 1
            lines.append(f"[圖片附件 {image_no}：{image.get('name', '圖片')}]")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def subscription_image_paths(messages: list[dict]) -> list[str]:
    """依對話出現順序取出本機圖片路徑。"""
    return [str(image["path"])
            for message in messages
            for image in message_images(message)
            if image.get("path")]


def with_transformed_image_paths(messages: list[dict], transform) -> list[dict]:
    """複製訊息並轉換附件路徑（Windows 打包版 → WSL CLI）。"""
    copied = deepcopy(messages)
    for message in copied:
        for image in message_images(message):
            if image.get("path"):
                image["path"] = transform(str(image["path"]))
    return copied
