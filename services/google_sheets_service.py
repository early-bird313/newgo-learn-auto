import csv
import io
import logging
import re
from typing import Any, Dict, List, Tuple
import requests
import config
from services.draft_store import add_draft
from services.gemini_service import generate_page_post
from services.image_service import get_free_image_url

logger = logging.getLogger(__name__)


def convert_to_csv_url(raw_url: str) -> str:
    """
    Converts any regular Google Sheet link into a direct CSV export download link.
    Example: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5.../edit#gid=0
    Becomes: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5.../export?format=csv
    """
    url = raw_url.strip()
    if not url:
        return ""
    
    # If already a CSV / pub URL, return as is
    if "format=csv" in url or "output=csv" in url:
        return url

    # Extract Spreadsheet ID
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        sheet_id = match.group(1)
        # Check for specific gid
        gid_match = re.search(r"gid=([0-9]+)", url)
        gid_part = f"&gid={gid_match.group(1)}" if gid_match else ""
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid_part}"

    return url


def fetch_sheet_rows(sheet_url: str) -> List[Dict[str, str]]:
    """
    Downloads and parses the Google Sheet rows as dictionaries.
    Expects standard headers: Topic, Caption, Media_Type, Media_URL, Status.
    """
    csv_url = convert_to_csv_url(sheet_url)
    if not csv_url:
        return []

    try:
        logger.info(f"Fetching Google Sheet CSV from: {csv_url}")
        res = requests.get(csv_url, timeout=15)
        if res.status_code != 200:
            logger.error(f"Failed to fetch Google Sheet CSV: HTTP {res.status_code}")
            return []

        # Parse CSV text
        content = res.content.decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(content))
        
        # Clean and normalize header keys to lowercase
        rows = []
        for raw_row in reader:
            normalized_row = {}
            for k, v in raw_row.items():
                if k:
                    clean_k = k.strip().lower().replace(" ", "_")
                    normalized_row[clean_k] = (v or "").strip()
            if normalized_row:
                rows.append(normalized_row)
        return rows
    except Exception as e:
        logger.error(f"Error reading Google Sheet: {e}")
        return []


def import_drafts_from_google_sheet(sheet_url: str = "", max_count: int = 5) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Reads rows from the Google Sheet and imports unused/pending topics as drafts.
    Returns: (imported_count, list_of_new_drafts)
    """
    target_url = sheet_url or config.GOOGLE_SHEET_CSV_URL
    if not target_url:
        logger.warning("No Google Sheet URL provided.")
        return 0, []

    rows = fetch_sheet_rows(target_url)
    if not rows:
        return 0, []

    created_drafts = []
    count = 0

    for row in rows:
        if count >= max_count:
            break

        # Check status column: skip if marked used/done/posted
        status = row.get("status", "").lower()
        if status in ["used", "posted", "done", "published"]:
            continue

        # Extract fields with multiple possible column names
        topic = (
            row.get("topic")
            or row.get("idea")
            or row.get("title")
            or row.get("content")
            or ""
        )
        custom_caption = row.get("caption") or row.get("custom_caption") or ""
        media_type = row.get("media_type") or row.get("type") or "photo"
        media_url = row.get("media_url") or row.get("image_url") or row.get("video_url") or ""

        if not topic and not custom_caption:
            continue

        # If caption not provided in sheet, generate engaging text via Gemini AI
        caption_to_use = custom_caption
        keyword_to_use = ""
        image_url_to_use = media_url if media_type == "photo" else ""
        video_url_to_use = media_url if media_type == "video" else ""

        if not caption_to_use:
            caption_to_use, keyword_to_use, visual_prompt = generate_page_post(topic)
            if not image_url_to_use and media_type != "text" and media_type != "video":
                image_url_to_use = get_free_image_url(keyword_to_use, visual_prompt)
        elif not image_url_to_use and media_type == "photo":
            # Generate relevant image for the provided caption
            image_url_to_use = get_free_image_url(topic, topic)

        new_draft = add_draft(
            caption=caption_to_use,
            image_url=image_url_to_use,
            video_url=video_url_to_use,
            media_type=media_type,
            topic=topic or "Google Sheet Import",
            keyword=keyword_to_use,
        )
        created_drafts.append(new_draft)
        count += 1

    logger.info(f"Successfully imported {count} drafts from Google Sheet.")
    return count, created_drafts
