import io
import urllib.parse
from fastapi.testclient import TestClient
import pytest

import config
from main import app
from services.gemini_service import (
    generate_chat_reply,
    generate_page_post,
    read_knowledge_base,
)
from services.image_service import get_free_image_url

client = TestClient(app)


def test_home_dashboard():
    """Verify that the home dashboard loads successfully with HTML content."""
    response = client.get("/")
    assert response.status_code == 200
    assert "NewGo Learn Auto" in response.text
    assert "text/html" in response.headers["content-type"]


def test_health_endpoint():
    """Verify that /health returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "facebook-ai-automation"


def test_webhook_verification_success():
    """Test successful Facebook Webhook challenge verification."""
    challenge = "987654321"
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": config.FB_VERIFY_TOKEN,
            "hub.challenge": challenge,
        },
    )
    assert response.status_code == 200
    assert response.text == challenge


def test_webhook_verification_forbidden():
    """Test rejection when verify token does not match."""
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 403


def test_webhook_receive_message():
    """Test receiving incoming Messenger message event via POST /webhook."""
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "123456789",
                "time": 1710000000,
                "messaging": [
                    {
                        "sender": {"id": "user_test_101"},
                        "recipient": {"id": "123456789"},
                        "message": {
                            "mid": "mid.test_msg_9999",
                            "text": "আসসালামু আলাইকুম, আপনাদের কার্যক্রম সম্পর্কে জানতে চাই।",
                        },
                    }
                ],
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.text == "EVENT_RECEIVED"


def test_webhook_duplicate_message_skipped():
    """Test that a duplicate message ID is safely skipped."""
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "123456789",
                "time": 1710000000,
                "messaging": [
                    {
                        "sender": {"id": "user_test_101"},
                        "recipient": {"id": "123456789"},
                        "message": {
                            "mid": "mid.test_msg_9999",  # Same mid
                            "text": "Repeat message",
                        },
                    }
                ],
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.text == "EVENT_RECEIVED"


def test_image_service_pollinations():
    """Verify that Pollinations AI image service constructs a valid URL."""
    url = get_free_image_url("peaceful sunrise", "A sunrise over river")
    assert "https://image.pollinations.ai/prompt/" in url
    assert "width=1200" in url


def test_knowledge_base_reading():
    """Verify that knowledge_base.txt is loaded correctly."""
    kb_text = read_knowledge_base()
    assert len(kb_text) > 0
    assert "As-Sunnah" in kb_text or "ফেসবুক" in kb_text


def test_gemini_chat_fallback():
    """Verify graceful handling when Gemini API key is not configured."""
    reply = generate_chat_reply("test_user_dummy", "আপনার অফিসের সময় কখন?")
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_draft_store_crud():
    """Verify that drafts can be created, retrieved, and deleted."""
    from services.draft_store import add_draft, get_draft_by_id, delete_draft, get_pending_drafts
    
    draft = add_draft("Test Caption", "https://example.com/img.jpg", "Test Topic")
    draft_id = draft["id"]
    
    fetched = get_draft_by_id(draft_id)
    assert fetched is not None
    assert fetched["caption"] == "Test Caption"
    assert fetched["status"] == "pending"
    
    # Delete
    deleted = delete_draft(draft_id)
    assert deleted is True
    assert get_draft_by_id(draft_id) is None


def test_dashboard_draft_delete_endpoint():
    """Verify POST /drafts/{id}/delete redirects cleanly."""
    from services.draft_store import add_draft
    draft = add_draft("To be deleted", "https://example.com/del.jpg")
    draft_id = draft["id"]
    
    response = client.post(f"/drafts/{draft_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=deleted"



def test_create_custom_draft_endpoint():
    """Verify manual custom post creation with video/text/photo."""
    response = client.post(
        "/drafts/create-custom",
        data={
            "caption": "Custom Video Post",
            "media_type": "video",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=draft_created"


def test_create_custom_draft_file_upload():
    """Verify manual custom post creation with direct file upload."""
    import io
    fake_file = io.BytesIO(b"fake image data")
    response = client.post(
        "/drafts/create-custom",
        data={
            "caption": "Device Upload Image Post",
            "media_type": "photo",
        },
        files={"media_file": ("test_pic.jpg", fake_file, "image/jpeg")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=draft_created"


def test_health_timezone():
    """Verify health endpoint returns BST timezone and dual schedules."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == "Asia/Dhaka"
    assert "BST" in data["current_bst_time"]
    assert len(data["schedules"]) == 2


def test_update_draft_endpoint():
    """Verify draft photo/caption/type can be updated without publishing."""
    from services.draft_store import add_draft, get_draft_by_id
    draft = add_draft("Initial Caption", "https://example.com/initial.jpg", "Initial Topic")
    draft_id = draft["id"]

    # Update caption and switch to text-only
    response = client.post(
        f"/drafts/{draft_id}/update",
        data={
            "caption": "Updated Caption Text",
            "media_type": "text",
            "media_url": "",
            "local_file_path": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=draft_updated"

    updated = get_draft_by_id(draft_id)
    assert updated["caption"] == "Updated Caption Text"
    assert updated["media_type"] == "text"


def test_regenerate_image_endpoint():
    """Verify draft image can be regenerated."""
    from services.draft_store import add_draft, get_draft_by_id
    draft = add_draft("Regen Caption", "https://example.com/old.jpg", "Technology")
    draft_id = draft["id"]

    response = client.post(f"/drafts/{draft_id}/regenerate-image", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=image_regenerated"

    updated = get_draft_by_id(draft_id)
    assert "/uploads/" in updated["image_url"] or "pollinations.ai" in updated["image_url"]



def test_webhook_receive_sticker():
    """Verify that Facebook Messenger thumbs-up/sticker event is accepted."""
    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "test_sticker_sender_99"},
                        "message": {
                            "mid": "mid_sticker_12345",
                            "sticker_id": 369239263222822,
                            "attachments": [{"type": "image", "payload": {"url": "https://example.com/like.png"}}],
                        },
                    }
                ]
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.text == "EVENT_RECEIVED"


def test_privacy_policy_endpoint():
    """Verify that /privacy returns 200 and Privacy Policy HTML."""
    response = client.get("/privacy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text


def test_terms_endpoint():
    """Verify that /terms returns 200 and Terms of Service HTML."""
    response = client.get("/terms")
    assert response.status_code == 200
    assert "Terms of Service" in response.text


def test_news_agent_memory_alternating():
    """Verify that agent memory alternating shuffle logic works correctly."""
    from services.news_agent_service import get_next_mode, save_agent_memory

    # Test when last mode was 'tips'
    save_agent_memory({"last_mode": "tips", "seen_news_hashes": [], "total_posts_created": 0, "history": []})
    assert get_next_mode() == "news"

    # Test when last mode was 'news'
    save_agent_memory({"last_mode": "news", "seen_news_hashes": [], "total_posts_created": 1, "history": []})
    assert get_next_mode() == "tips"


def test_news_agent_clean_html():
    """Verify HTML tag cleaning and entity decoding."""
    from services.news_agent_service import clean_html

    sample = "<p>Breaking: <b>OpenAI</b> announces &amp; launches new model &quot;GPT-5&quot;.</p>"
    cleaned = clean_html(sample)
    assert "<p>" not in cleaned
    assert "<b>" not in cleaned
    assert "Breaking: OpenAI announces & launches new model \"GPT-5\"." == cleaned


def test_agent_run_endpoint():
    """Verify that POST /agent/run redirects properly on success."""
    from unittest.mock import patch

    with patch("main.run_autonomous_content_agent", return_value={"success": True, "draft_id": "test_123"}):
        response = client.post("/agent/run", data={"mode": "auto"}, follow_redirects=False)
        assert response.status_code == 303
        assert "msg=agent_success" in response.headers["location"]


def test_image_sanitization_no_humans():
    """Verify that human and female keywords are stripped and negative prompts are added."""
    from services.image_service import sanitize_prompt_for_no_humans, get_free_image_url

    raw_prompt = "A young woman programmer and male hacker writing code with a robotic face"
    sanitized = sanitize_prompt_for_no_humans(raw_prompt)

    # Must NOT contain forbidden terms
    forbidden = ["woman", "women", "female", "girl", "hacker", "programmer", "face"]
    for word in forbidden:
        assert word not in sanitized.lower().split()

    # Must contain negative reinforcement
    assert "no humans" in sanitized
    assert "no women" in sanitized
    assert "no female" in sanitized

    # URL generation test
    url = get_free_image_url("female developer robot", raw_prompt)
    assert "pollinations.ai" in url
    assert "woman" not in urllib.parse.unquote(url).lower().split()


def test_caption_synchronized_image_generation():
    """Verify that get_free_image_url accepts caption and generates image."""
    from services.image_service import get_free_image_url

    test_caption = "আজকের দিনে অডিও এডিটিং ও ব্যাকগ্রাউন্ড নয়েজ দূর করতে সেরা এআই টুলস।"
    url = get_free_image_url(caption=test_caption)
    assert "https://image.pollinations.ai/prompt/" in url
    assert "no%20humans" in url or "no humans" in urllib.parse.unquote(url)






