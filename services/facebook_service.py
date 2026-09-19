import json
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


def publish_post_to_page(message: str, image_url: str = "", as_draft: bool = True) -> Dict[str, Any]:
    """
    Creates a post on the Facebook Page.
    When as_draft=True (default), the post is saved as an unpublished DRAFT in Meta Business Suite,
    so the user can review and approve/publish it manually.
    """
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        err = "FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID is not configured."
        logger.error(err)
        return {"success": False, "error": err}

    params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}

    # Case 1: Photo Draft or Post
    if image_url:
        try:
            if as_draft:
                logger.info(f"Creating unpublished temporary photo from: {image_url}")
                photo_url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/photos"
                photo_res = requests.post(
                    photo_url,
                    data={"url": image_url, "published": False, "temporary": True},
                    params=params,
                    timeout=20,
                )
                photo_data = photo_res.json()
                if photo_res.status_code == 200 and "id" in photo_data:
                    photo_id = photo_data["id"]
                    # Attach photo to draft feed post
                    feed_url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/feed"
                    feed_payload = {
                        "message": message,
                        "published": False,
                        "attached_media": json.dumps([{"media_fbid": photo_id}]),
                    }
                    feed_res = requests.post(feed_url, data=feed_payload, params=params, timeout=15)
                    feed_data = feed_res.json()
                    if feed_res.status_code == 200:
                        logger.info(f"Successfully created DRAFT photo post on Facebook! ID: {feed_data.get('id')}")
                        return {"success": True, "type": "draft_photo", "data": feed_data}
            else:
                # Direct live publish (only if explicitly requested)
                url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/photos"
                payload = {"url": image_url, "caption": message, "published": True}
                response = requests.post(url, data=payload, params=params, timeout=20)
                res_data = response.json()
                if response.status_code == 200:
                    logger.info(f"Successfully published live photo post! ID: {res_data.get('id')}")
                    return {"success": True, "type": "photo", "data": res_data}
        except Exception as e:
            logger.error(f"Error handling photo post: {e}, falling back to text feed post...")

    # Case 2: Text Post (Draft or Live)
    feed_url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/feed"
    payload = {
        "message": message,
        "published": not as_draft,
    }
    try:
        response = requests.post(feed_url, data=payload, params=params, timeout=15)
        res_data = response.json()
        if response.status_code == 200:
            post_type = "draft_text" if as_draft else "text"
            logger.info(f"Successfully created {post_type} post! ID: {res_data.get('id')}")
            return {"success": True, "type": post_type, "data": res_data}
        else:
            logger.error(f"Failed to create post: {res_data}")
            return {"success": False, "error": res_data}
    except Exception as e:
        logger.error(f"Exception creating post: {e}")
        return {"success": False, "error": str(e)}
