import json
import logging
import os
from typing import Any, Dict
import requests
import config

logger = logging.getLogger(__name__)

GRAPH_API_URL = f"https://graph.facebook.com/{config.FB_GRAPH_API_VERSION}"
GRAPH_VIDEO_URL = f"https://graph-video.facebook.com/{config.FB_GRAPH_API_VERSION}"


def ensure_page_webhook_subscribed() -> bool:
    """
    Subscribes the Facebook Page to this app's webhooks for messages and messaging_postbacks.
    Required for Meta to forward real-time Messenger messages to our webhook endpoint.
    """
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        logger.warning("FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID not set. Skipping webhook subscription.")
        return False
    try:
        url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/subscribed_apps"
        params = {
            "subscribed_fields": "messages,messaging_postbacks",
            "access_token": config.FB_PAGE_ACCESS_TOKEN,
        }
        res = requests.post(url, params=params, timeout=10)
        data = res.json()
        if data.get("success"):
            logger.info("Successfully ensured Facebook Page is subscribed to webhook events!")
            return True
        else:
            logger.warning(f"Could not auto-subscribe page to webhooks: {data}")
            return False
    except Exception as e:
        logger.error(f"Error subscribing page to webhooks: {e}")
        return False


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


def publish_video_to_page(description: str, video_url: str = "", local_file_path: str = "") -> Dict[str, Any]:
    """
    Publishes a video to the Facebook Page using a direct video URL or uploaded local file.
    """
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        err = "FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID is not configured."
        logger.error(err)
        return {"success": False, "error": err}

    url = f"{GRAPH_VIDEO_URL}/{config.FB_PAGE_ID}/videos"
    params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}

    try:
        # Case A: Local file upload (direct binary upload to Facebook)
        if local_file_path and os.path.exists(local_file_path):
            logger.info(f"Uploading local video file to Facebook: {local_file_path}")
            with open(local_file_path, "rb") as f:
                files = {"source": f}
                data = {"description": description}
                response = requests.post(url, files=files, data=data, params=params, timeout=120)
        # Case B: Video URL
        elif video_url:
            logger.info(f"Publishing video to Facebook from URL: {video_url}")
            data = {"description": description, "file_url": video_url}
            response = requests.post(url, data=data, params=params, timeout=60)
        else:
            return {"success": False, "error": "No video file or URL provided."}

        res_data = response.json()
        if response.status_code == 200:
            logger.info(f"Successfully published video! ID: {res_data.get('id')}")
            return {"success": True, "type": "video", "data": res_data}
        else:
            logger.error(f"Failed to publish video: {res_data}")
            return {"success": False, "error": res_data}
    except Exception as e:
        logger.error(f"Exception publishing video: {e}")
        return {"success": False, "error": str(e)}


def publish_post_to_page(
    message: str,
    image_url: str = "",
    video_url: str = "",
    local_file_path: str = "",
    media_type: str = "photo",
    as_draft: bool = False,
) -> Dict[str, Any]:
    """
    Creates or publishes a post (Text, Photo, or Video) to the Facebook Page.
    Supports direct local file upload or remote media URLs.
    """
    if not config.FB_PAGE_ACCESS_TOKEN or not config.FB_PAGE_ID:
        err = "FB_PAGE_ACCESS_TOKEN or FB_PAGE_ID is not configured."
        logger.error(err)
        return {"success": False, "error": err}

    params = {"access_token": config.FB_PAGE_ACCESS_TOKEN}
    normalized_media = media_type.lower().strip()

    # Case 1: Video Post
    if normalized_media == "video" and (video_url or local_file_path):
        return publish_video_to_page(description=message, video_url=video_url, local_file_path=local_file_path)

    # Case 2: Photo Post with Local File
    if local_file_path and os.path.exists(local_file_path):
        try:
            logger.info(f"Uploading local photo file to Facebook: {local_file_path}")
            url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/photos"
            with open(local_file_path, "rb") as f:
                files = {"source": f}
                data = {"caption": message, "published": True}
                response = requests.post(url, files=files, data=data, params=params, timeout=40)
            res_data = response.json()
            if response.status_code == 200:
                logger.info(f"Successfully published photo from file! ID: {res_data.get('id')}")
                return {"success": True, "type": "photo", "data": res_data}
            else:
                logger.error(f"Failed to upload photo file: {res_data}")
                return {"success": False, "error": res_data}
        except Exception as e:
            logger.error(f"Error publishing local photo file: {e}")
            return {"success": False, "error": str(e)}

    # Case 3: Photo Post with URL (Draft or Live)
    if (normalized_media == "photo" or not normalized_media) and image_url:
        try:
            if as_draft:
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
                    feed_url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/feed"
                    feed_payload = {
                        "message": message,
                        "published": False,
                        "attached_media": json.dumps([{"media_fbid": photo_id}]),
                    }
                    feed_res = requests.post(feed_url, data=feed_payload, params=params, timeout=15)
                    feed_data = feed_res.json()
                    if feed_res.status_code == 200:
                        return {"success": True, "type": "draft_photo", "data": feed_data}
            else:
                # Direct live photo publish
                url = f"{GRAPH_API_URL}/{config.FB_PAGE_ID}/photos"
                payload = {"url": image_url, "caption": message, "published": True}
                response = requests.post(url, data=payload, params=params, timeout=25)
                res_data = response.json()
                if response.status_code == 200:
                    logger.info(f"Successfully published live photo post! ID: {res_data.get('id')}")
                    return {"success": True, "type": "photo", "data": res_data}
                else:
                    logger.warning(f"Photo post failed ({res_data}), falling back to text...")
        except Exception as e:
            logger.error(f"Error handling photo post: {e}, falling back to text feed post...")

    # Case 4: Text-only Post
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
            logger.error(f"Failed to create text post: {res_data}")
            return {"success": False, "error": res_data}
    except Exception as e:
        logger.error(f"Exception creating post: {e}")
        return {"success": False, "error": str(e)}
