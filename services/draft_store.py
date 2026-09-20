from datetime import datetime
import json
import logging
from pathlib import Path
import time
import uuid
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import config

logger = logging.getLogger(__name__)

DRAFTS_FILE = config.BASE_DIR / "drafts.json"


def get_current_bst_time_str() -> str:
    """Returns the current formatted time in Bangladesh Timezone (Asia/Dhaka)."""
    try:
        tz = ZoneInfo(config.APP_TIMEZONE)
        return datetime.now(tz).strftime("%Y-%m-%d %I:%M %p (BST)")
    except Exception as e:
        logger.warning(f"Error computing timezone {config.APP_TIMEZONE}: {e}")
        return time.strftime("%Y-%m-%d %I:%M %p")


def _load_drafts() -> List[Dict[str, Any]]:
    if not DRAFTS_FILE.exists():
        return []
    try:
        with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading drafts.json: {e}")
        return []


def _save_drafts(drafts: List[Dict[str, Any]]) -> None:
    try:
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving drafts.json: {e}")


def get_all_drafts() -> List[Dict[str, Any]]:
    """Returns all drafts sorted by creation time descending."""
    drafts = _load_drafts()
    return sorted(drafts, key=lambda d: d.get("created_at", 0), reverse=True)


def get_pending_drafts() -> List[Dict[str, Any]]:
    """Returns only drafts that are pending approval."""
    return [d for d in get_all_drafts() if d.get("status") == "pending"]


def get_published_drafts(limit: int = 10) -> List[Dict[str, Any]]:
    """Returns recently published drafts."""
    published = [d for d in get_all_drafts() if d.get("status") == "published"]
    return published[:limit]


def get_draft_by_id(draft_id: str) -> Optional[Dict[str, Any]]:
    drafts = _load_drafts()
    for d in drafts:
        if d.get("id") == draft_id:
            return d
    return None


def add_draft(
    caption: str,
    image_url: str = "",
    topic: str = "",
    keyword: str = "",
    media_type: str = "photo",
    video_url: str = "",
    local_file_path: str = "",
) -> Dict[str, Any]:
    """
    Adds a newly generated post to the pending drafts queue.
    media_type can be 'photo', 'video', or 'text'.
    Supports local file path for direct device uploads.
    """
    drafts = _load_drafts()
    
    # Normalize media type
    m_type = media_type.lower().strip()
    if m_type not in ["photo", "video", "text"]:
        m_type = "photo" if (image_url or not video_url) else "video"

    new_draft = {
        "id": str(uuid.uuid4())[:8],
        "caption": caption,
        "image_url": image_url,
        "video_url": video_url,
        "local_file_path": local_file_path,
        "media_type": m_type,
        "topic": topic or config.DEFAULT_POST_TOPIC,
        "keyword": keyword,
        "created_at": time.time(),
        "created_time_str": get_current_bst_time_str(),
        "status": "pending",
        "fb_post_id": None,
    }
    drafts.insert(0, new_draft)
    _save_drafts(drafts)
    logger.info(f"Created new pending draft with ID: {new_draft['id']} (Media: {m_type}, File: {bool(local_file_path)})")
    return new_draft


def mark_draft_as_published(draft_id: str, fb_post_id: str = "") -> bool:
    """Updates draft status to published with Facebook post ID and exact BST time."""
    drafts = _load_drafts()
    for d in drafts:
        if d.get("id") == draft_id:
            d["status"] = "published"
            d["published_at"] = time.time()
            d["published_time_str"] = get_current_bst_time_str()
            d["fb_post_id"] = fb_post_id
            _save_drafts(drafts)
            logger.info(f"Marked draft {draft_id} as published (FB ID: {fb_post_id})")
            return True
    return False


def delete_draft(draft_id: str) -> bool:
    """Deletes a draft by ID."""
    drafts = _load_drafts()
    initial_len = len(drafts)
    drafts = [d for d in drafts if d.get("id") != draft_id]
    if len(drafts) < initial_len:
        _save_drafts(drafts)
        logger.info(f"Deleted draft ID: {draft_id}")
        return True
    return False
