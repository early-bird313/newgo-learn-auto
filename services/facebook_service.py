import logging
from typing import Any, Dict
import requests
import config

logger = logging.getLogger(__name__)

GRAPH_API_URL = f"https://graph.facebook.com/{config.FB_GRAPH_API_VERSION}"


def send_typing_indicator(recipient_id: str, action: str = "typing_on") -> bool:
    """Sends typing indicator (typing_on / typing_off) to user in Messenger."""
    if not config.FB_PAGE_ACCESS_TOKEN:
        return False
    try:
        url = f"{GRAPH_API_URL}/me/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "sender_action": action,
        }
        params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}
        requests.post(url, json=payload, params=params, timeout=5)
        return True
    except Exception as e:
        logger.debug(f"Typing indicator failed: {e}")
        return False


def send_messenger_reply(recipient_id: str, message_text: str) -> Dict[str, Any]:
    """
    Sends a text message reply to a user via the Messenger Send API.
    """
    if not config.FB_PAGE_ACCESS_TOKEN:
        err = "FB_PAGE_ACCESS_TOKEN is missing. Cannot send message."
        logger.error(err)
        return {"success": False, "error": err}

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE",
    }

    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        res_data = response.json()
        if response.status_code == 200:
            logger.info(f"Successfully sent reply to recipient {recipient_id}: {res_data}")
            return {"success": True, "data": res_data}
        else:
            logger.error(f"Facebook Send API error: {res_data}")
            return {"success": False, "error": res_data}
    except Exception as e:
        logger.error(f"Exception while sending messenger reply: {e}")
        return {"success": False, "error": str(e)}


def publish_post_to_page(message: str, image_url: str = "") -> Dict[str, Any]:
    """
    Publishes a post (photo with caption, or plain text) to the Facebook Page feed.
    """
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        err = "FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID is not configured."
        logger.error(err)
        return {"success": False, "error": err}

    params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}

    # Case 1: Photo Post
    if image_url:
        url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/photos"
        payload = {
            "url": image_url,
            "caption": message,
            "published": True,
        }
        try:
            logger.info(f"Attempting to publish photo post with image: {image_url}")
            response = requests.post(url, data=payload, params=params, timeout=20)
            res_data = response.json()
            if response.status_code == 200:
                logger.info(f"Successfully published photo post! ID: {res_data.get('id')}")
                return {"success": True, "type": "photo", "data": res_data}
            else:
                logger.warning(f"Photo post failed ({res_data}), falling back to text post...")
        except Exception as e:
            logger.error(f"Error publishing photo post: {e}, attempting text post fallback...")

    # Case 2: Text Post fallback or direct text post
    url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/feed"
    payload = {"message": message}
    try:
        response = requests.post(url, data=payload, params=params, timeout=15)
        res_data = response.json()
        if response.status_code == 200:
            logger.info(f"Successfully published text post! ID: {res_data.get('id')}")
            return {"success": True, "type": "text", "data": res_data}
        else:
            logger.error(f"Failed to publish post: {res_data}")
            return {"success": False, "error": res_data}
    except Exception as e:
        logger.error(f"Exception publishing feed post: {e}")
        return {"success": False, "error": str(e)}
