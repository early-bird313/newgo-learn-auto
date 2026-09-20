import csv
import io
import json
import logging
import re
from typing import Any, Dict, List, Tuple
import requests
import config
from services.draft_store import add_draft
from services.gemini_service import generate_page_post
from services.image_service import get_free_image_url

logger = logging.getLogger(__name__)

SETTINGS_FILE = config.BASE_DIR / "sheet_settings.json"


def get_active_sheet_url() -> str:
    """
    Returns the currently active Google Sheet URL from sheet_settings.json
    or falls back to config.GOOGLE_SHEET_CSV_URL.
    """
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved_url = data.get("sheet_url", "").strip()
                if saved_url:
                    return saved_url
    except Exception as e:
        logger.warning(f"Error reading sheet_settings.json: {e}")
    return config.GOOGLE_SHEET_CSV_URL


def save_active_sheet_url(sheet_url: str):
    """
    Persists the Google Sheet URL so the 9 AM & 8 PM daily scheduler
    can automatically read from it even across server restarts.
    """
    cleaned = sheet_url.strip()
    if not cleaned:
        return
    data = {}
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    data["sheet_url"] = cleaned
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved active Google Sheet URL: {cleaned}")
    except Exception as e:
        logger.error(f"Failed to save sheet_settings.json: {e}")


def get_used_row_keys() -> set:
    """Returns set of row signatures already drafted."""
    used = set()
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in data.get("used_keys", []):
                    used.add(k.strip().lower())
    except Exception as e:
        logger.warning(f"Error reading used keys: {e}")
    return used


def mark_row_key_used(row_key: str):
    """Records a row signature as drafted so scheduler doesn't re-draft it."""
    clean_key = row_key.strip().lower()
    if not clean_key:
        return
    data = {}
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    used_list = data.get("used_keys", [])
    if clean_key not in [x.lower() for x in used_list]:
        used_list.append(clean_key)
        data["used_keys"] = used_list
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving used row key: {e}")


def convert_to_csv_url(raw_url: str) -> str:
    """
    Converts any regular Google Sheet link into a direct CSV export download link.
    Handles protocol-less URLs like //docs.google.com/... or docs.google.com/...
    """
    url = raw_url.strip()
    if not url:
        return ""

    # Normalize protocol
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # If already a CSV / pub URL, return as is
    if "format=csv" in url or "output=csv" in url:
        return url

    # Extract Spreadsheet ID
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        sheet_id = match.group(1)
        # Check for specific gid
        gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
        gid_part = f"&gid={gid_match.group(1)}" if gid_match else ""
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid_part}"

    return url


def fetch_sheet_rows(sheet_url: str) -> Tuple[List[Dict[str, str]], str]:
    """
    Downloads and parses the Google Sheet rows as dictionaries.
    Returns: (rows, error_message)
    """
    csv_url = convert_to_csv_url(sheet_url)
    if not csv_url:
        return [], "Google Sheet URL খালি দেওয়া হয়েছে।"

    try:
        logger.info(f"Fetching Google Sheet CSV from: {csv_url}")
        res = requests.get(csv_url, timeout=15)
        if res.status_code == 404:
            err = (
                "গুগল শিট পাওয়া যায়নি (HTTP 404)। আপনার শিটটি সম্ভবত Restricted/Private করা আছে। "
                "দয়া করে গুগল শিটের Share অপশনে গিয়ে General access: 'Anyone with the link' (Viewer/দর্শক) করে দিন।"
            )
            logger.error(err)
            return [], err
        elif res.status_code == 403 or res.status_code == 401:
            err = (
                "গুগল শিট এক্সেস করার অনুমতি নেই (HTTP 403)। "
                "দয়া করে শিটটির Share সেটিংসে 'Anyone with the link' (Viewer) করে দিন।"
            )
            logger.error(err)
            return [], err
        elif res.status_code != 200:
            err = f"গুগল শিট ডাউনলোড করা যায়নি (HTTP {res.status_code})।"
            logger.error(err)
            return [], err

        content = res.content.decode("utf-8-sig", errors="ignore")
        if not content.strip():
            return [], "গুগল শিটটি সম্পূর্ণ খালি।"

        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for raw_row in reader:
            normalized_row = {}
            for k, v in raw_row.items():
                if k:
                    clean_k = k.strip().lower().replace(" ", "_")
                    normalized_row[clean_k] = (v or "").strip()
            if normalized_row and any(normalized_row.values()):
                rows.append(normalized_row)

        if not rows:
            return [], "গুগল শিটে কোনো বৈধ ডেটা রো পাওয়া যায়নি। নিশ্চিত করুন প্রথম সারিতে হেডার রয়েছে: Topic, Caption, Media_Type, Media_URL"

        return rows, ""
    except Exception as e:
        err = f"গুগল শিট কানেকশন এরর: {str(e)}"
        logger.error(err)
        return [], err


def import_drafts_from_google_sheet(sheet_url: str = "", max_count: int = 5) -> Tuple[int, List[Dict[str, Any]], str]:
    """
    Reads rows from the Google Sheet and imports unused/pending topics as drafts.
    Automatically saves the sheet URL so the 9 AM & 8 PM daily scheduler can use it.
    Returns: (imported_count, list_of_new_drafts, error_message)
    """
    target_url = sheet_url.strip() or get_active_sheet_url()
    if not target_url:
        logger.warning("No Google Sheet URL provided.")
        return 0, [], "কোনো গুগল শিট লিংক দেওয়া হয়নি।"

    rows, error_msg = fetch_sheet_rows(target_url)
    if error_msg:
        return 0, [], error_msg

    # Persist the valid URL for future scheduled jobs
    save_active_sheet_url(target_url)

    used_keys = get_used_row_keys()
    created_drafts = []
    count = 0

    for row in rows:
        if count >= max_count:
            break

        # Check status column: skip if marked used/done/posted
        status = row.get("status", "").lower()
        if status in ["used", "posted", "done", "published"]:
            continue

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

        # Prevent duplicate drafts by topic & caption signature
        row_signature = f"{topic}::{custom_caption}".strip().lower()
        if row_signature in used_keys:
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
            image_url_to_use = get_free_image_url(topic, topic)

        new_draft = add_draft(
            caption=caption_to_use,
            image_url=image_url_to_use,
            video_url=video_url_to_use,
            media_type=media_type,
            topic=topic or "Google Sheet Content",
            keyword=keyword_to_use,
        )
        created_drafts.append(new_draft)
        mark_row_key_used(row_signature)
        count += 1

    if count == 0:
        return 0, [], "গুগল শিটের সবগুলো কনটেন্ট ইতিমধ্যে ড্রাফট করা হয়ে গেছে। শিটে নতুন রো যোগ করুন।"

    logger.info(f"Successfully imported {count} drafts from Google Sheet.")
    return count, created_drafts, ""
