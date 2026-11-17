from keyboard_executor.core.ai.messages import (
    render_subscription_history,
    to_anthropic_messages,
    to_openai_messages,
)


def _messages():
    return [{"role": "user", "content": "依畫面建立規則", "images": [{
        "name": "畫面.png", "media_type": "image/png", "data": "YWJj",
        "path": "/tmp/image.png",
    }]}]


def test_openai_message_uses_base64_data_url_before_text():
    content = to_openai_messages(_messages())[0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,YWJj"
    assert content[1] == {"type": "text", "text": "依畫面建立規則"}


def test_anthropic_message_uses_base64_image_block_before_text():
    content = to_anthropic_messages(_messages())[0]["content"]
    assert content[0] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "YWJj"}}
    assert content[1] == {"type": "text", "text": "依畫面建立規則"}


def test_subscription_history_labels_images_without_embedding_base64():
    rendered = render_subscription_history(_messages())
    assert "圖片附件 1：畫面.png" in rendered
    assert "YWJj" not in rendered
