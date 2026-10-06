import asyncio
from collections import deque
from contextlib import asynccontextmanager
import html
import logging
import os
from pathlib import Path
import random
import shutil
from typing import Optional
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import config
from services.draft_store import (
    add_draft,
    delete_draft,
    get_current_bst_time_str,
    get_draft_by_id,
    get_pending_drafts,
    get_published_drafts,
    mark_draft_as_published,
    update_draft,
)
try:
    from services.facebook_service import (
        ensure_page_webhook_subscribed,
        publish_post_to_page,
        send_messenger_reply,
        send_typing_indicator,
    )
except ImportError:
    from services.facebook_service import (
        publish_post_to_page,
        send_messenger_reply,
        send_typing_indicator,
    )
    def ensure_page_webhook_subscribed():
        return False

from services.gemini_service import generate_chat_reply, generate_page_post

try:
    from services.google_sheets_service import (
        get_active_sheet_url,
        import_drafts_from_csv_file,
        import_drafts_from_google_sheet,
    )
except ImportError:
    from services.google_sheets_service import (
        get_active_sheet_url,
        import_drafts_from_google_sheet,
    )
    def import_drafts_from_csv_file(*args, **kwargs):
        return 0, [], "CSV processing module pending update"

from services.image_service import get_free_image_url
from services.news_agent_service import (
    get_agent_memory,
    get_next_mode,
    run_autonomous_content_agent,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fb_automation")

# Track recent message IDs to prevent duplicate webhook processing
processed_message_ids = deque(maxlen=500)

# Background scheduler for morning and night draft generation
scheduler = AsyncIOScheduler()


async def scheduled_daily_post():
    """
    Scheduled task to prepare a draft post (sakal 9:00 AM & rat 8:00 PM BST).
    Executes Autonomous Content Agent (alternating Top AI News and AI Tips & Tricks).
    Strictly follows abstract tech imagery (NO humans, NO female figures).
    NOTE: Stored in draft_store for user review and approval before posting to Facebook.
    """
    logger.info("Executing scheduled draft creation via Autonomous AI Agent (Bangladesh Timezone: 9 AM / 8 PM)...")
    try:
        # 1. Autonomous AI Content Agent (Alternating News and Tips & Tricks)
        try:
            agent_result = run_autonomous_content_agent()
            if agent_result.get("success"):
                logger.info(
                    f"Scheduled draft prepared via Autonomous AI Agent! Mode: {agent_result.get('mode')}, Draft ID: {agent_result.get('draft_id')}"
                )
                return
        except Exception as agent_err:
            logger.warning(f"Autonomous agent draft failed: {agent_err}. Falling back to Gemini AI...")

        # 2. Standard Gemini AI Fallback
        caption, keyword, visual_prompt = generate_page_post(config.DEFAULT_POST_TOPIC)
        image_url = get_free_image_url(keyword, visual_prompt)
        draft = add_draft(
            caption=caption,
            image_url=image_url,
            topic=config.DEFAULT_POST_TOPIC,
            keyword=keyword,
            media_type="photo",
        )
        logger.info(f"Scheduled draft prepared via Gemini AI! Draft ID: {draft['id']}")
    except Exception as e:
        logger.error(f"Error preparing scheduled draft post: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Register Morning 9:00 AM and Night 8:00 PM schedules (Asia/Dhaka)
    logger.info(f"Starting background scheduler in timezone: {config.APP_TIMEZONE}")
    
    # Morning: 9:00 AM BST
    morning_trigger = CronTrigger(
        hour=config.SCHEDULE_MORNING_HOUR,
        minute=config.SCHEDULE_MORNING_MINUTE,
        timezone=config.APP_TIMEZONE,
    )
    scheduler.add_job(
        scheduled_daily_post,
        trigger=morning_trigger,
        id="morning_draft_post",
        replace_existing=True,
    )

    # Night: 8:00 PM BST (20:00)
    evening_trigger = CronTrigger(
        hour=config.SCHEDULE_EVENING_HOUR,
        minute=config.SCHEDULE_EVENING_MINUTE,
        timezone=config.APP_TIMEZONE,
    )
    scheduler.add_job(
        scheduled_daily_post,
        trigger=evening_trigger,
        id="evening_draft_post",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler active! Drafts prepared daily at {config.SCHEDULE_MORNING_HOUR:02d}:{config.SCHEDULE_MORNING_MINUTE:02d} AM and {config.SCHEDULE_EVENING_HOUR:02d}:{config.SCHEDULE_EVENING_MINUTE:02d} (BST)"
    )

    # Ensure Facebook Page is subscribed to messages webhook
    try:
        ensure_page_webhook_subscribed()
    except Exception as e:
        logger.warning(f"Failed to auto-subscribe page webhook during startup: {e}")

    yield
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


app = FastAPI(
    title="NewGo Learn Auto - Facebook AI Approval Dashboard",
    description="One-Click Post Approval Dashboard, Direct Device Uploads, Google Sheets Sync, and AI Messenger Bot.",
    version="3.0.0",
    lifespan=lifespan,
)

# Mount local uploads directory for user-uploaded images and videos
app.mount("/uploads", StaticFiles(directory=config.UPLOADS_DIR), name="uploads")


@app.get("/", response_class=HTMLResponse)
async def home(msg: Optional[str] = None, error: Optional[str] = None):
    """Modern, intuitive Post Approval Dashboard with Direct Media Uploads."""
    pending_drafts = get_pending_drafts()
    published_drafts = get_published_drafts(limit=10)
    current_time = get_current_bst_time_str()
    drafts_count = len(pending_drafts)

    agent_mem = get_agent_memory()
    next_agent_mode = get_next_mode()
    total_agent_posts = agent_mem.get("total_posts_created", 0)

    alert_html = ""
    if msg == "draft_created":
        alert_html = f'<div class="alert alert-success">✨ নতুন ড্রাফট যোগ হয়েছে! বর্তমানে মোট {drafts_count}টি ড্রাফট সংরক্ষিত আছে।</div>'
    elif msg == "agent_success":
        alert_html = f'<div class="alert alert-success">🤖 অটোনোমাস এআই এজেন্ট সফলভাবে কন্টেন্ট প্রস্তুত করে ড্রাফটে যুক্ত করেছে! বর্তমানে মোট {drafts_count}টি ড্রাফট কিউ-তে রয়েছে।</div>'
    elif msg == "draft_updated":
        alert_html = '<div class="alert alert-success">💾 ড্রাফটের ছবি/ভিডিও/ক্যাপশন সফলভাবে সেভ করা হয়েছে!</div>'
    elif msg == "image_regenerated":
        alert_html = '<div class="alert alert-success">🔄 নতুন বিমূর্ত এআই ছবি সফলভাবে তৈরি ও যুক্ত করা হয়েছে!</div>'
    elif msg == "published":
        alert_html = '<div class="alert alert-success">🎉 পোস্টটি সফলভাবে আপনার ফেসবুক পেজে লাইভ হয়েছে!</div>'
    elif msg == "deleted":
        alert_html = '<div class="alert alert-info">🗑️ ড্রাফটটি সফলভাবে মুছে ফেলা হয়েছে।</div>'
    elif error:
        alert_html = f'<div class="alert alert-error">❌ এরর: {html.escape(error)}</div>'

    # Build Pending Draft Cards HTML
    pending_cards_html = ""
    if not pending_drafts:
        pending_cards_html = """
        <div class="empty-state">
            <p style="font-size: 1.15rem; color: #cbd5e1; margin-bottom: 0.4rem;">বর্তমানে কোনো ড্রাফট নেই (০টি ড্রাফট)।</p>
            <p style="color: #94a3b8; font-size: 0.95rem; margin: 0;">নিচে <strong>"➕ নতুন ড্রাফট তৈরি করুন"</strong> বাটনে ক্লিক করে এক এক করে ড্রাফট যোগ করতে পারেন অথবা ডিভাইস থেকে ছবি/ভিডিও আপলোড করতে পারেন।</p>
        </div>
        """
    else:
        for idx, d in enumerate(pending_drafts, 1):
            safe_caption = html.escape(d.get("caption", ""))
            safe_img = html.escape(d.get("image_url", ""))
            safe_video = html.escape(d.get("video_url", ""))
            safe_local_file = html.escape(d.get("local_file_path", ""))
            safe_topic = html.escape(d.get("topic", ""))
            media_type = d.get("media_type", "photo").lower()
            draft_id = d["id"]
            created_at = d.get("created_time_str", "Today")

            # Determine media preview element
            media_preview = ""
            media_badge = ""
            if media_type == "video" and (safe_video or safe_local_file):
                video_src = safe_video if safe_video else f"/uploads/{os.path.basename(safe_local_file)}"
                media_badge = '<span class="badge-media badge-video">🎥 Video Post</span>'
                media_preview = f"""
                <div class="video-container">
                    <video src="{video_src}" controls class="post-media" preload="metadata">ভিডিও লোড হচ্ছে...</video>
                </div>
                """
            elif media_type == "photo" and (safe_img or safe_local_file):
                img_src = safe_img if safe_img else f"/uploads/{os.path.basename(safe_local_file)}"
                media_badge = '<span class="badge-media badge-photo">📷 Photo Post</span>'
                media_preview = f'<img src="{img_src}" alt="Post Image" class="post-media" onerror="this.onerror=null; this.src=\'https://picsum.photos/800/450\';" />'
            else:
                media_badge = '<span class="badge-media badge-text">📝 Text-Only Post</span>'
                media_preview = """
                <div class="text-only-box">
                    <span>📄 শুধুমাত্র টেক্সট পোস্ট (কোনো ছবি বা ভিডিও যুক্ত নেই)</span>
                </div>
                """

            url_val = safe_video if media_type == "video" else (safe_img if not safe_local_file else "")

            pending_cards_html += f"""
            <div class="card post-card" id="draft_{draft_id}">
                <div class="post-header">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="draft-num-badge">ড্রাফট #{idx}</span>
                        <span id="badge_media_{draft_id}">{media_badge}</span>
                    </div>
                    <span class="post-time">🕒 {created_at}</span>
                </div>

                <form action="/drafts/{draft_id}/approve" method="post" enctype="multipart/form-data" id="form_draft_{draft_id}">
                    <div class="post-body">
                        <!-- Left Column: Media Preview & Edit Tools -->
                        <div class="media-col">
                            <div id="preview_box_{draft_id}">
                                {media_preview}
                            </div>
                            <span class="topic-tag">📌 টপিক: {safe_topic}</span>

                            <!-- Media Edit Controls -->
                            <div class="media-edit-box">
                                <span class="media-edit-title">🖼️ ছবি বা ভিডিও পরিবর্তন করুন:</span>

                                <!-- 1. Device File Upload Button -->
                                <label class="btn-card-upload">
                                    📁 ডিভাইস থেকে ছবি/ভিডিও বদলান
                                    <input type="file" name="new_media_file" id="file_input_{draft_id}" class="file-hidden-input" accept="image/*,video/*" onchange="handleCardFileChange(event, '{draft_id}')">
                                </label>
                                <div id="card_file_note_{draft_id}" class="card-file-note" style="display:none;"></div>

                                <!-- 2. Media Type Selector -->
                                <div style="margin-top: 0.5rem; display: flex; align-items: center; gap: 0.4rem;">
                                    <label style="font-size: 0.8rem; color: #cbd5e1; white-space: nowrap;">টাইপ:</label>
                                    <select name="media_type" id="media_type_{draft_id}" class="input-text-sm" onchange="handleCardTypeSelect('{draft_id}', this.value)">
                                        <option value="photo" {"selected" if media_type == "photo" else ""}>📷 Photo (ছবি)</option>
                                        <option value="video" {"selected" if media_type == "video" else ""}>🎥 Video (ভিডিও)</option>
                                        <option value="text" {"selected" if media_type == "text" else ""}>📝 Text Only (ছবি ছাড়া)</option>
                                    </select>
                                </div>

                                <!-- 3. URL Input -->
                                <div style="margin-top: 0.4rem;">
                                    <input type="text" name="media_url" id="media_url_{draft_id}" class="input-text-sm" placeholder="অথবা ছবি/ভিডিও লিংক (URL) দিন..." value="{url_val}" oninput="handleCardUrlInput('{draft_id}', this.value)">
                                </div>

                                <!-- 4. Regenerate AI Image Button -->
                                <div style="margin-top: 0.45rem; display: flex; gap: 0.4rem;">
                                    <button type="button" class="btn-regen-sm" onclick="triggerRegenerateImage('{draft_id}')">🔄 নতুন AI ছবি আনুন</button>
                                </div>
                            </div>

                            <input type="hidden" name="local_file_path" id="local_file_{draft_id}" value="{safe_local_file}">
                        </div>

                        <!-- Right Column: Caption & Actions -->
                        <div class="caption-col">
                            <label class="form-label">পোস্টের ক্যাপশন (প্রয়োজনে পরিবর্তন করুন):</label>
                            <textarea name="caption" class="caption-textarea" rows="8">{safe_caption}</textarea>
                            
                            <div class="card-actions">
                                <button type="submit" class="btn btn-approve">🚀 ফেসবুকে পোস্ট করুন (Approve & Post)</button>
                                <button type="button" class="btn btn-save-draft" onclick="submitDraftForm('{draft_id}', '/drafts/{draft_id}/update')">💾 ড্রাফটে সেভ রাখুন</button>
                            </div>
                        </div>
                    </div>
                </form>

                <!-- Separate Delete Action -->
                <div style="display: flex; justify-content: flex-end; margin-top: 0.6rem; border-top: 1px dashed var(--border); padding-top: 0.6rem;">
                    <form action="/drafts/{draft_id}/delete" method="post">
                        <button type="submit" class="btn btn-delete" onclick="return confirm('এই ড্রাফটটি মুছে ফেলতে চান?');">🗑️ ড্রাফট মুছুন</button>
                    </form>
                </div>
            </div>
            """

    # Build Published Drafts HTML
    published_list_html = ""
    if published_drafts:
        for p in published_drafts:
            p_time = p.get("published_time_str", "Recently")
            if isinstance(p_time, tuple):
                p_time = p_time[0]
            snippet = html.escape(p.get("caption", "")[:120] + "...")
            p_type = p.get("media_type", "photo").upper()
            published_list_html += f"""
            <div class="pub-item">
                <div>
                    <span style="color: #38bdf8; font-size: 0.8rem; font-weight: bold;">[{p_type}]</span>
                    <strong>✔ {p_time}</strong>
                    <p style="margin: 0.3rem 0; color: #cbd5e1; font-size: 0.9rem;">{snippet}</p>
                </div>
                <span class="badge-pub">পাবলিশড</span>
            </div>
            """
    else:
        published_list_html = "<p style='color: #94a3b8; font-size: 0.9rem;'>এখনো কোনো পোস্ট পাবলিশ করা হয়নি।</p>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NewGo Learn Auto - Post Approval Dashboard</title>
        <style>
            :root {{
                --bg: #0b1120;
                --card-bg: #1e293b;
                --border: #334155;
                --text: #f8fafc;
                --primary: #2563eb;
                --primary-hover: #1d4ed8;
                --success: #10b981;
                --success-hover: #059669;
                --danger: #ef4444;
            }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--bg); color: var(--text); padding: 1.2rem; margin: 0; }}
            .container {{ max-width: 1050px; margin: 0 auto; }}
            header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }}
            h1 {{ margin: 0; color: #38bdf8; font-size: 1.6rem; }}
            .header-badges {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
            .badge-safe {{ background: #065f46; color: #34d399; padding: 0.35rem 0.8rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
            .badge-tz {{ background: #1e3a8a; color: #93c5fd; padding: 0.35rem 0.8rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
            
            .alert {{ padding: 0.9rem 1.2rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 500; }}
            .alert-success {{ background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }}
            .alert-info {{ background: #1e3a8a; color: #bfdbfe; border: 1px solid #3b82f6; }}
            .alert-error {{ background: #7f1d1d; color: #fecaca; border: 1px solid #dc2626; }}

            .section-title {{ color: #e2e8f0; font-size: 1.25rem; margin: 2rem 0 1rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.8rem; }}
            .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.35rem; margin-bottom: 1.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
            
            .input-text {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.75rem 1rem; border-radius: 8px; font-size: 0.95rem; }}
            .input-text:focus {{ outline: none; border-color: #38bdf8; }}
            .form-label {{ display: block; color: #cbd5e1; font-weight: 500; font-size: 0.9rem; margin-bottom: 0.4rem; }}
            .caption-textarea {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.75rem; border-radius: 8px; font-size: 0.95rem; font-family: inherit; line-height: 1.5; resize: vertical; }}
            .caption-textarea:focus {{ outline: none; border-color: #38bdf8; }}

            /* Device File Upload Box */
            .upload-dropzone {{ border: 2px dashed #475569; border-radius: 10px; padding: 1.5rem; text-align: center; background: #0f172a; cursor: pointer; transition: border-color 0.2s; position: relative; }}
            .upload-dropzone:hover {{ border-color: #38bdf8; }}
            .file-hidden {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }}
            .live-preview-box {{ margin-top: 1rem; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); max-height: 320px; display: none; text-align: center; background: #020617; }}
            .live-preview-img {{ max-width: 100%; max-height: 300px; object-fit: contain; border-radius: 6px; }}
            .live-preview-video {{ max-width: 100%; max-height: 300px; border-radius: 6px; }}

            /* Draft Cards */
            .draft-num-badge {{ background: #0284c7; color: #fff; padding: 0.2rem 0.6rem; border-radius: 8px; font-size: 0.8rem; font-weight: bold; }}
            .badge-media {{ padding: 0.2rem 0.5rem; border-radius: 10px; font-size: 0.75rem; font-weight: bold; }}
            .badge-photo {{ background: #0369a1; color: #bae6fd; }}
            .badge-video {{ background: #701a75; color: #f5d0fe; }}
            .badge-text {{ background: #334155; color: #e2e8f0; }}
            .badge-count-header {{ background: #3b82f6; color: #fff; padding: 0.25rem 0.7rem; border-radius: 20px; font-size: 0.85rem; font-weight: bold; }}

            .post-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
            .post-time {{ color: #94a3b8; font-size: 0.85rem; font-weight: 500; }}
            .post-body {{ display: grid; grid-template-columns: 320px 1fr; gap: 1.5rem; }}
            @media (max-width: 768px) {{ .post-body {{ grid-template-columns: 1fr; }} }}
            
            .post-media {{ width: 100%; border-radius: 8px; object-fit: cover; aspect-ratio: 16/9; border: 1px solid var(--border); }}
            .text-only-box {{ display: flex; align-items: center; justify-content: center; background: #0f172a; border: 1px dashed var(--border); border-radius: 8px; aspect-ratio: 16/9; color: #94a3b8; font-size: 0.85rem; text-align: center; padding: 1rem; box-sizing: border-box; }}
            .topic-tag {{ display: block; color: #94a3b8; font-size: 0.8rem; margin-top: 0.5rem; word-break: break-word; }}

            .card-actions {{ margin-top: 1rem; display: flex; gap: 0.8rem; }}
            .btn {{ padding: 0.75rem 1.3rem; border-radius: 8px; font-weight: bold; font-size: 0.95rem; border: none; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; }}
            .btn-primary {{ background: var(--primary); color: #fff; }}
            .btn-primary:hover {{ background: var(--primary-hover); }}
            .btn-approve {{ background: var(--success); color: #fff; flex: 1; }}
            .btn-approve:hover {{ background: var(--success-hover); }}
            .btn-delete {{ background: transparent; color: #f87171; border: 1px solid #ef4444; font-size: 0.85rem; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; }}
            .btn-delete:hover {{ background: rgba(239,68,68,0.1); }}
            .btn-add-draft {{ background: #0284c7; color: white; padding: 0.5rem 1rem; font-size: 0.9rem; }}

            .empty-state {{ text-align: center; padding: 2.5rem 1rem; background: var(--card-bg); border-radius: 12px; border: 1px dashed var(--border); }}
            .pub-item {{ display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 0; border-bottom: 1px solid var(--border); }}
            .pub-item:last-child {{ border-bottom: none; }}
            .badge-pub {{ background: #064e3b; color: #34d399; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 10px; font-weight: bold; }}
            
            .helper-text {{ font-size: 0.85rem; color: #94a3b8; margin-top: 0.3rem; }}

            /* Draft Card Media Edit Styles */
            .input-text-sm {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.45rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }}
            .input-text-sm:focus {{ outline: none; border-color: #38bdf8; }}
            .media-edit-box {{ margin-top: 0.75rem; background: #0f172a; border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem; }}
            .media-edit-title {{ font-size: 0.85rem; font-weight: bold; color: #38bdf8; display: block; margin-bottom: 0.45rem; }}
            .btn-card-upload {{ display: block; text-align: center; background: #334155; color: #f8fafc; border: 1px solid #475569; padding: 0.5rem 0.8rem; border-radius: 6px; font-size: 0.85rem; font-weight: 500; cursor: pointer; position: relative; overflow: hidden; transition: background 0.2s; }}
            .btn-card-upload:hover {{ background: #475569; }}
            .file-hidden-input {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }}
            .card-file-note {{ font-size: 0.8rem; color: #38bdf8; margin-top: 0.35rem; background: #0284c71a; padding: 0.3rem 0.5rem; border-radius: 4px; border: 1px solid #0284c755; word-break: break-all; }}
            .btn-regen-sm {{ flex: 1; background: #4c1d95; color: #e9d5ff; border: 1px solid #7c3aed; padding: 0.4rem 0.6rem; border-radius: 6px; font-size: 0.8rem; font-weight: 500; cursor: pointer; transition: background 0.2s; }}
            .btn-regen-sm:hover {{ background: #5b21b6; }}
            .btn-save-draft {{ background: #1e3a8a; color: #bfdbfe; border: 1px solid #3b82f6; padding: 0.75rem 1.1rem; border-radius: 8px; font-weight: bold; font-size: 0.95rem; cursor: pointer; transition: all 0.2s; }}
            .btn-save-draft:hover {{ background: #1d4ed8; color: #fff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1>🚀 NewGo Learn Auto</h1>
                    <span style="color: #94a3b8; font-size: 0.9rem;">পোস্ট অনুমোদন ও ডিভাইস আপলোড ড্যাশবোর্ড</span>
                </div>
                <div class="header-badges">
                    <span class="badge-tz">🕒 {current_time}</span>
                    <span class="badge-safe">🛡️ অনুমোদনের পরই পোস্ট লাইভ হবে</span>
                </div>
            </header>

            {alert_html}

            <!-- Action 0: Autonomous AI News & Tips Agent -->
            <div class="card" style="border-left: 4px solid #8b5cf6; background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.6rem;">
                    <div style="display: flex; align-items: center; gap: 0.6rem;">
                        <h3 style="margin: 0; color: #a78bfa; font-size: 1.2rem;">🤖 NewGo Autonomous AI Content Agent</h3>
                        <span style="background: #059669; color: #d1fae5; padding: 0.15rem 0.55rem; border-radius: 12px; font-size: 0.75rem; font-weight: bold;">🟢 সার্বক্ষণিক সক্রিয়</span>
                    </div>
                    <span style="font-size: 0.85rem; color: #cbd5e1;">সর্বমোট স্বয়ংক্রিয় পোস্ট: <strong style="color: #38bdf8;">{total_agent_posts}টি</strong></span>
                </div>
                
                <p style="color: #94a3b8; font-size: 0.88rem; margin-top: 0; margin-bottom: 0.8rem; line-height: 1.5;">
                    শীর্ষ টেক ওয়েবসাইটগুলো (<em>The Verge, TechCrunch, VentureBeat</em>) সার্বক্ষণিক ট্র্যাক করে এবং প্রতিদিনের শিডিউলে (সকাল ৯টা ও রাত ৮টা) একবার <strong>"🔥 শীর্ষ AI নিউজ"</strong> এবং পরের বার <strong>"💡 দরকারি AI টিপস অ্যান্ড ট্রিকস"</strong> শাফল করে স্বয়ংক্রিয় ফেসবুক পোস্ট তৈরি করে।
                </p>
                <div style="margin-bottom: 0.8rem; display: flex; align-items: center; gap: 0.5rem; font-size: 0.82rem; color: #38bdf8; background: #0284c718; padding: 0.35rem 0.75rem; border-radius: 6px; border: 1px solid #0284c740;">
                    <span>🛡️ <strong>কঠোর ইমেজ নীতি:</strong> কোনো মানুষ, মুখমণ্ডল বা নারী প্রতিকৃতি ছাড়া শুধুমাত্র পিউর বিমূর্ত প্রযুক্তি ও সার্কিট ইমেজ তৈরি হয়।</span>
                </div>

                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.8rem; background: rgba(15, 23, 42, 0.6); padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid rgba(139, 92, 246, 0.3);">
                    <div>
                        <span style="font-size: 0.85rem; color: #cbd5e1;">পরবর্তী স্বয়ংক্রিয় পোস্টের ধরন:</span>
                        <span style="font-size: 0.9rem; font-weight: bold; color: {'#f59e0b' if next_agent_mode == 'news' else '#10b981'}; margin-left: 0.4rem;">
                            {'📰 শীর্ষ AI ব্রেকিং নিউজ (Top AI News)' if next_agent_mode == 'news' else '💡 দরকারি AI টিপস অ্যান্ড ট্রিকস (AI Tips & Tricks)'}
                        </span>
                    </div>

                    <div style="display: flex; gap: 0.6rem; flex-wrap: wrap;">
                        <form action="/agent/run" method="post" style="margin: 0;">
                            <input type="hidden" name="mode" value="auto" />
                            <button type="submit" class="btn btn-primary" style="background: #7c3aed; padding: 0.5rem 1rem; font-size: 0.88rem;">
                                ⚡ এখনই এজেন্ট রান করুন (Auto Shuffle)
                            </button>
                        </form>
                        <form action="/agent/run" method="post" style="margin: 0;">
                            <input type="hidden" name="mode" value="news" />
                            <button type="submit" class="btn" style="background: #0284c7; color: white; padding: 0.5rem 0.85rem; font-size: 0.85rem;">
                                📰 শুধু নিউজ
                            </button>
                        </form>
                        <form action="/agent/run" method="post" style="margin: 0;">
                            <input type="hidden" name="mode" value="tips" />
                            <button type="submit" class="btn" style="background: #059669; color: white; padding: 0.5rem 0.85rem; font-size: 0.85rem;">
                                💡 শুধু টিপস
                            </button>
                        </form>
                    </div>
                </div>
            </div>

            <!-- Action 1: Add AI Draft One by One -->
            <div class="card" style="border-left: 4px solid #38bdf8;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.6rem;">
                    <h3 style="margin: 0; color: #38bdf8; font-size: 1.15rem;">✨ এআই দিয়ে নতুন ড্রাফট যোগ করুন</h3>
                    <span style="font-size: 0.85rem; color: #94a3b8;">প্রতি ক্লিকে একটি করে নতুন ড্রাফট কিউ-তে যুক্ত হবে</span>
                </div>
                <form action="/drafts/generate" method="post" style="display: flex; gap: 0.8rem; flex-wrap: wrap;">
                    <input type="text" name="topic" class="input-text" style="flex: 1; min-width: 280px;" placeholder="টপিক বা আইডিয়া লিখুন (যেমন: ChatGPT Tips) অথবা ডিফল্ট রাখতে খালি রাখুন..." />
                    <button type="submit" class="btn btn-primary" style="background: #0284c7;">➕ নতুন ড্রাফট যোগ করুন (+ Add Draft)</button>
                </form>
            </div>

            <!-- Action 2: Direct Device File Upload (Image or Video) -->
            <div class="card" style="border-left: 4px solid #10b981;">
                <h3 style="margin-top: 0; color: #34d399; font-size: 1.15rem;">📁 ডিভাইস থেকে সরাসরি ছবি বা ভিডিও আপলোড করে পোস্ট</h3>
                <p class="helper-text">আপনার ফোন বা কম্পিউটার থেকে ছবি/ভিডিও সিলেক্ট করুন। সাথে সাথে নিচে প্রিভিউ দেখতে পাবেন:</p>
                
                <form action="/drafts/create-custom" method="post" enctype="multipart/form-data">
                    <div style="margin-bottom: 1rem;">
                        <label class="form-label">পোস্টের ক্যাপশন ও হ্যাশট্যাগ:</label>
                        <textarea name="caption" class="caption-textarea" rows="4" placeholder="আপনার পোস্টের বিস্তারিত বার্তা ও হ্যাশট্যাগ লিখুন..." required></textarea>
                    </div>

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                        <div>
                            <label class="form-label">মিডিয়ার ধরন (Media Type):</label>
                            <select name="media_type" id="media_type_select" class="input-text" onchange="handleMediaTypeChange()">
                                <option value="photo">📷 ছবি (Photo Upload)</option>
                                <option value="video">🎥 ভিডিও (Video Upload)</option>
                                <option value="text">📝 শুধুমাত্র টেক্সট (No Media)</option>
                            </select>
                        </div>
                        <div id="file_picker_wrapper">
                            <label class="form-label">ডিভাইস থেকে ফাইল নির্বাচন করুন:</label>
                            <div class="upload-dropzone">
                                <span id="dropzone_label">📁 ফাইল সিলেক্ট করতে এখানে ক্লিক করুন (Image / Video)</span>
                                <input type="file" name="media_file" id="media_file_input" class="file-hidden" accept="image/*,video/*" onchange="previewSelectedMedia(event)" />
                            </div>
                        </div>
                    </div>

                    <!-- Instant Live Media Preview Container -->
                    <div id="live_preview_container" class="live-preview-box">
                        <div style="padding: 0.5rem; background: #0f172a; font-size: 0.85rem; color: #38bdf8; display: flex; justify-content: space-between; align-items: center;">
                            <span id="preview_filename">সিলেক্টেড ফাইল প্রিভিউ:</span>
                            <button type="button" onclick="clearSelectedMedia()" style="background: transparent; border: none; color: #f87171; cursor: pointer; font-size: 0.8rem;">✖ ফাইল সরান</button>
                        </div>
                        <div id="preview_body" style="padding: 1rem;"></div>
                    </div>

                    <div style="margin-top: 1rem;">
                        <button type="submit" class="btn btn-primary" style="background: #059669; width: 100%;">➕ ড্রাফটে সেভ করুন (Save to Drafts)</button>
                    </div>
                </form>
            </div>



            <!-- Pending Approval Section -->
            <div class="section-title">
                <div style="display: flex; align-items: center; gap: 0.6rem;">
                    <span>⏳ অনুমোদনের অপেক্ষায় খসড়া পোস্টসমূহ</span>
                    <span class="badge-count-header">{drafts_count}টি ড্রাফট রেডি</span>
                </div>
                <form action="/drafts/generate" method="post" style="display: inline;">
                    <button type="submit" class="btn btn-add-draft">➕ আরও একটি ড্রাফট যোগ করুন (+)</button>
                </form>
            </div>
            
            {pending_cards_html}

            <!-- Published History -->
            <div class="section-title">
                <span>✅ সম্প্রতি প্রকাশিত পোস্টসমূহ</span>
            </div>
            <div class="card">
                {published_list_html}
            </div>
        </div>

        <script>
            function handleMediaTypeChange() {{
                const type = document.getElementById('media_type_select').value;
                const picker = document.getElementById('file_picker_wrapper');
                const fileInput = document.getElementById('media_file_input');
                if (type === 'text') {{
                    picker.style.display = 'none';
                    clearSelectedMedia();
                }} else {{
                    picker.style.display = 'block';
                    if (type === 'video') {{
                        fileInput.accept = 'video/*';
                        document.getElementById('dropzone_label').innerText = '🎥 ডিভাইস থেকে ভিডিও ফাইল সিলেক্ট করুন';
                    }} else {{
                        fileInput.accept = 'image/*';
                        document.getElementById('dropzone_label').innerText = '📷 ডিভাইস থেকে ছবি সিলেক্ট করুন';
                    }}
                }}
            }}

            function previewSelectedMedia(event) {{
                const file = event.target.files[0];
                if (!file) return;

                const container = document.getElementById('live_preview_container');
                const previewBody = document.getElementById('preview_body');
                const filenameLabel = document.getElementById('preview_filename');

                filenameLabel.innerText = 'সিলেক্টেড: ' + file.name + ' (' + (file.size / (1024*1024)).toFixed(2) + ' MB)';
                const fileURL = URL.createObjectURL(file);

                if (file.type.startsWith('video/')) {{
                    document.getElementById('media_type_select').value = 'video';
                    previewBody.innerHTML = '<video src="' + fileURL + '" controls class="live-preview-video" autoplay muted></video>';
                }} else {{
                    document.getElementById('media_type_select').value = 'photo';
                    previewBody.innerHTML = '<img src="' + fileURL + '" class="live-preview-img" alt="Preview" />';
                }}
                container.style.display = 'block';
            }}

            function clearSelectedMedia() {{
                const fileInput = document.getElementById('media_file_input');
                fileInput.value = '';
                document.getElementById('live_preview_container').style.display = 'none';
                document.getElementById('preview_body').innerHTML = '';
                document.getElementById('dropzone_label').innerText = '📁 ফাইল সিলেক্ট করতে এখানে ক্লিক করুন (Image / Video)';
            }}

            function handleCardFileChange(event, draftId) {{
                const file = event.target.files[0];
                if (!file) return;

                const note = document.getElementById('card_file_note_' + draftId);
                note.style.display = 'block';
                note.innerText = '✨ সিলেক্টেড: ' + file.name + ' (' + (file.size / (1024*1024)).toFixed(2) + ' MB)';

                const previewBox = document.getElementById('preview_box_' + draftId);
                const typeSelect = document.getElementById('media_type_' + draftId);
                const badge = document.getElementById('badge_media_' + draftId);
                const fileURL = URL.createObjectURL(file);

                if (file.type.startsWith('video/')) {{
                    typeSelect.value = 'video';
                    previewBox.innerHTML = '<video src="' + fileURL + '" controls class="post-media" autoplay muted></video>';
                    if (badge) badge.innerHTML = '<span class="badge-media badge-video">🎥 Video Post</span>';
                }} else {{
                    typeSelect.value = 'photo';
                    previewBox.innerHTML = '<img src="' + fileURL + '" alt="Post Image" class="post-media" />';
                    if (badge) badge.innerHTML = '<span class="badge-media badge-photo">📷 Photo Post</span>';
                }}
            }}

            function handleCardTypeSelect(draftId, type) {{
                const previewBox = document.getElementById('preview_box_' + draftId);
                const badge = document.getElementById('badge_media_' + draftId);
                const urlInput = document.getElementById('media_url_' + draftId);

                if (type === 'text') {{
                    previewBox.innerHTML = '<div class="text-only-box"><span>📄 শুধুমাত্র টেক্সট পোস্ট (কোনো ছবি বা ভিডিও পোস্ট হবে না)</span></div>';
                    if (badge) badge.innerHTML = '<span class="badge-media badge-text">📝 Text-Only Post</span>';
                }} else if (type === 'photo') {{
                    if (badge) badge.innerHTML = '<span class="badge-media badge-photo">📷 Photo Post</span>';
                    if (urlInput && urlInput.value) {{
                        previewBox.innerHTML = '<img src="' + urlInput.value + '" alt="Post Image" class="post-media" />';
                    }}
                }} else if (type === 'video') {{
                    if (badge) badge.innerHTML = '<span class="badge-media badge-video">🎥 Video Post</span>';
                    if (urlInput && urlInput.value) {{
                        previewBox.innerHTML = '<video src="' + urlInput.value + '" controls class="post-media"></video>';
                    }}
                }}
            }}

            function handleCardUrlInput(draftId, url) {{
                if (!url.trim()) return;
                const previewBox = document.getElementById('preview_box_' + draftId);
                const typeSelect = document.getElementById('media_type_' + draftId);
                const badge = document.getElementById('badge_media_' + draftId);

                if (url.endsWith('.mp4') || url.endsWith('.webm') || url.endsWith('.mov')) {{
                    typeSelect.value = 'video';
                    previewBox.innerHTML = '<video src="' + url.trim() + '" controls class="post-media"></video>';
                    if (badge) badge.innerHTML = '<span class="badge-media badge-video">🎥 Video Post</span>';
                }} else {{
                    typeSelect.value = 'photo';
                    previewBox.innerHTML = '<img src="' + url.trim() + '" alt="Post Image" class="post-media" />';
                    if (badge) badge.innerHTML = '<span class="badge-media badge-photo">📷 Photo Post</span>';
                }}
            }}

            function triggerRegenerateImage(draftId) {{
                if (!confirm('এই ড্রাফটটির জন্য নতুন একটি AI ছবি তৈরি করতে চান?')) return;
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/drafts/' + draftId + '/regenerate-image';
                document.body.appendChild(form);
                form.submit();
            }}

            function submitDraftForm(draftId, actionUrl) {{
                const form = document.getElementById('form_draft_' + draftId);
                form.action = actionUrl;
                form.submit();
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "facebook-ai-automation",
        "timezone": config.APP_TIMEZONE,
        "current_bst_time": get_current_bst_time_str(),
        "schedules": [
            f"{config.SCHEDULE_MORNING_HOUR:02d}:{config.SCHEDULE_MORNING_MINUTE:02d} BST (Morning)",
            f"{config.SCHEDULE_EVENING_HOUR:02d}:{config.SCHEDULE_EVENING_MINUTE:02d} BST (Night)",
        ],
        "active_google_sheet": bool(get_active_sheet_url()),
        "autonomous_agent": {
            "status": "active",
            "next_mode": get_next_mode(),
            "total_posts": get_agent_memory().get("total_posts_created", 0),
        },
    }


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Official Privacy Policy required by Meta Developer Platform for Live Mode."""
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Privacy Policy - NewGo Learn Auto</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }
            h1, h2 { color: #1e3a8a; }
            .card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <h1>Privacy Policy for NewGo Learn Auto</h1>
        <p><strong>Effective Date:</strong> September 2026</p>
        <p>NewGo Learn Auto ("we", "our", or "the App") respects your privacy and is committed to protecting the information of users who interact with our Facebook Page and Messenger assistant.</p>
        
        <h2>1. Information We Process</h2>
        <p>When you send a message to our Facebook Page via Messenger, we receive your publicly accessible Facebook User ID (PSID) and the content of your message to provide automated, helpful customer assistance.</p>

        <h2>2. How We Use the Information</h2>
        <ul>
            <li>To generate relevant, factual, and polite replies to your questions in real time.</li>
            <li>To provide customer support and educational assistance related to our page content.</li>
        </ul>

        <h2>3. Data Storage and Protection</h2>
        <p>We do not sell, rent, or trade user data to any third party. Transient conversation history is held temporarily in volatile memory solely to maintain conversational context and is automatically recycled.</p>

        <h2>4. Data Deletion Requests</h2>
        <p>Users can request deletion of any associated interaction data at any time by messaging our Facebook Page directly or emailing our administrative support team.</p>

        <h2>5. Contact Us</h2>
        <p>For any questions or concerns regarding this privacy policy, please contact our Facebook Page administrators via Meta Business Suite.</p>
    </body>
    </html>
    """)


@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service():
    """Terms of Service required by Meta Developer Platform."""
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Terms of Service - NewGo Learn Auto</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }
            h1, h2 { color: #1e3a8a; }
        </style>
    </head>
    <body>
        <h1>Terms of Service</h1>
        <p>By interacting with the NewGo Learn Auto Facebook Page and assistant, you agree that responses are generated to assist with educational and inquiry needs. You agree not to send spam, abusive language, or prohibited materials.</p>
    </body>
    </html>
    """)


# ==============================================================================
# 0. Autonomous AI Content Agent (Manual Trigger & Auto Shuffle)
# ==============================================================================
@app.post("/agent/run")
async def trigger_autonomous_agent(mode: str = Form("auto")):
    """
    Manually triggers the Autonomous AI News & Tips Agent.
    Supports auto-shuffle or forced 'news' / 'tips' mode.
    """
    forced_mode = None if mode == "auto" else mode.lower().strip()
    try:
        result = run_autonomous_content_agent(forced_mode=forced_mode)
        if result.get("success"):
            return RedirectResponse(url="/?msg=agent_success", status_code=303)
        else:
            return RedirectResponse(url="/?error=এজেন্ট পোস্ট তৈরি করতে ব্যর্থ হয়েছে", status_code=303)
    except Exception as e:
        logger.error(f"Error running autonomous agent endpoint: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


# ==============================================================================
# 1. Draft Actions (Generate 1 by 1, Import Sheet, Custom Upload, Approve, Delete)
# ==============================================================================
@app.post("/drafts/generate")
async def generate_single_draft(topic: str = Form("")):
    """Generates 1 new draft post and appends it to the draft queue."""
    target_topic = topic.strip() or config.DEFAULT_POST_TOPIC
    logger.info(f"Adding 1 new draft to queue for topic: '{target_topic}'")

    try:
        caption, keyword, visual_prompt = generate_page_post(target_topic)
        image_url = get_free_image_url(keyword, visual_prompt)
        add_draft(
            caption=caption,
            image_url=image_url,
            topic=target_topic,
            keyword=keyword,
            media_type="photo",
        )
        return RedirectResponse(url="/?msg=draft_created", status_code=303)
    except Exception as e:
        logger.error(f"Error generating draft: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


@app.post("/drafts/create-custom")
async def create_custom_draft(
    caption: str = Form(...),
    media_type: str = Form("photo"),
    media_file: Optional[UploadFile] = File(None),
):
    """
    Directly uploads photo or video from device, or text-only, and saves to drafts queue.
    """
    m_type = media_type.lower().strip()
    saved_local_path = ""
    saved_web_url = ""

    # Process uploaded media file
    if media_file and media_file.filename:
        safe_ext = Path(media_file.filename).suffix.lower()
        unique_name = f"{str(uuid.uuid4())[:8]}_{media_file.filename.replace(' ', '_')}"
        target_path = config.UPLOADS_DIR / unique_name
        
        try:
            with open(target_path, "wb") as buffer:
                shutil.copyfileobj(media_file.file, buffer)
            saved_local_path = str(target_path)
            saved_web_url = f"/uploads/{unique_name}"
            logger.info(f"Saved uploaded file to: {saved_local_path}")
            
            # Detect media type from extension if not set
            if safe_ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                m_type = "video"
            else:
                m_type = "photo"
        except Exception as e:
            logger.error(f"Error saving uploaded file: {e}")
            return RedirectResponse(url=f"/?error=Failed to upload file: {str(e)}", status_code=303)

    img_url = saved_web_url if m_type == "photo" else ""
    vid_url = saved_web_url if m_type == "video" else ""

    add_draft(
        caption=caption.strip(),
        image_url=img_url,
        video_url=vid_url,
        local_file_path=saved_local_path,
        media_type=m_type,
        topic="Device Upload Custom Post",
    )
    return RedirectResponse(url="/?msg=draft_created", status_code=303)


@app.post("/drafts/import-sheet")
async def import_from_sheet(
    sheet_url: str = Form(""),
    sheet_file: Optional[UploadFile] = File(None),
):
    """Imports content from Google Sheet URL or direct CSV file upload, and creates drafts."""
    # 1. If a direct CSV file was uploaded from device
    if sheet_file and sheet_file.filename:
        safe_filename = sheet_file.filename.lower()
        if not safe_filename.endswith(".csv"):
            return RedirectResponse(url="/?error=শুধুমাত্র .csv ফরম্যাটের ফাইল আপলোড করুন", status_code=303)
        temp_dest = config.BASE_DIR / "active_content_sheet.csv"
        try:
            with open(temp_dest, "wb") as buffer:
                shutil.copyfileobj(sheet_file.file, buffer)
            count, _, err_msg = import_drafts_from_csv_file(temp_dest, max_count=5)
            if count > 0:
                return RedirectResponse(url="/?msg=sheet_imported", status_code=303)
            else:
                return RedirectResponse(url=f"/?error={err_msg}", status_code=303)
        except Exception as e:
            logger.error(f"CSV file processing error: {e}")
            return RedirectResponse(url=f"/?error=CSV ফাইল প্রসেস করতে ব্যর্থ: {str(e)}", status_code=303)

    # 2. Otherwise use the Google Sheet URL
    target_url = sheet_url.strip() or get_active_sheet_url()
    if not target_url:
        return RedirectResponse(url="/?error=গুগল শিট লিংক দিন অথবা একটি CSV ফাইল আপলোড করুন", status_code=303)

    try:
        count, _, err_msg = import_drafts_from_google_sheet(target_url, max_count=5)
        if count > 0:
            return RedirectResponse(url="/?msg=sheet_imported", status_code=303)
        else:
            return RedirectResponse(url=f"/?error={err_msg}", status_code=303)
    except Exception as e:
        logger.error(f"Google Sheet import error: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


@app.post("/drafts/{draft_id}/approve")
async def approve_and_publish_draft(
    draft_id: str,
    caption: str = Form(...),
    media_type: str = Form("photo"),
    media_url: str = Form(""),
    local_file_path: str = Form(""),
    new_media_file: Optional[UploadFile] = File(None),
):
    """
    Human-in-the-Loop Action:
    User clicked 'Approve & Post'. Publishes Text, Photo, or Video directly to Facebook Page.
    Supports on-the-fly media file replacement.
    """
    draft = get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    m_type = media_type.lower().strip()
    file_path = local_file_path.strip() or (draft.get("local_file_path") or "")
    img_url = media_url.strip() if m_type == "photo" else (draft.get("image_url") or "")
    vid_url = media_url.strip() if m_type == "video" else (draft.get("video_url") or "")

    # If new file was selected directly inside the draft card
    if new_media_file and new_media_file.filename:
        safe_ext = Path(new_media_file.filename).suffix.lower()
        unique_name = f"{str(uuid.uuid4())[:8]}_{new_media_file.filename.replace(' ', '_')}"
        target_path = config.UPLOADS_DIR / unique_name
        try:
            with open(target_path, "wb") as buffer:
                shutil.copyfileobj(new_media_file.file, buffer)
            file_path = str(target_path)
            if safe_ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                m_type = "video"
                vid_url = f"/uploads/{unique_name}"
                img_url = ""
            else:
                m_type = "photo"
                img_url = f"/uploads/{unique_name}"
                vid_url = ""
            logger.info(f"Draft {draft_id} updated with new file for approval: {file_path}")
        except Exception as e:
            logger.error(f"Error saving replacement file in approve: {e}")

    if m_type == "text":
        img_url = ""
        vid_url = ""
        file_path = ""

    logger.info(f"User APPROVED draft ID {draft_id} (Type: {m_type}). Publishing to Facebook Page...")

    # Publish LIVE to Facebook
    result = publish_post_to_page(
        message=caption.strip(),
        image_url=img_url,
        video_url=vid_url,
        local_file_path=file_path,
        media_type=m_type,
        as_draft=False,
    )

    if result.get("success"):
        fb_id = result.get("data", {}).get("id", "") or result.get("data", {}).get("post_id", "")
        mark_draft_as_published(draft_id, fb_post_id=fb_id)
        return RedirectResponse(url="/?msg=published", status_code=303)
    else:
        err_msg = str(result.get("error", "Failed to publish to Facebook"))
        logger.error(f"Failed to publish approved draft: {err_msg}")
        return RedirectResponse(url=f"/?error={err_msg}", status_code=303)


@app.post("/drafts/{draft_id}/update")
async def update_existing_draft(
    draft_id: str,
    caption: str = Form(...),
    media_type: str = Form("photo"),
    media_url: str = Form(""),
    local_file_path: str = Form(""),
    new_media_file: Optional[UploadFile] = File(None),
):
    """
    Updates the draft in the queue (caption, photo, video, or text) without posting to Facebook.
    """
    draft = get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    m_type = media_type.lower().strip()
    file_path = local_file_path.strip() or (draft.get("local_file_path") or "")
    img_url = media_url.strip() if m_type == "photo" else (draft.get("image_url") or "")
    vid_url = media_url.strip() if m_type == "video" else (draft.get("video_url") or "")

    # If new file is uploaded
    if new_media_file and new_media_file.filename:
        safe_ext = Path(new_media_file.filename).suffix.lower()
        unique_name = f"{str(uuid.uuid4())[:8]}_{new_media_file.filename.replace(' ', '_')}"
        target_path = config.UPLOADS_DIR / unique_name
        try:
            with open(target_path, "wb") as buffer:
                shutil.copyfileobj(new_media_file.file, buffer)
            file_path = str(target_path)
            if safe_ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                m_type = "video"
                vid_url = f"/uploads/{unique_name}"
                img_url = ""
            else:
                m_type = "photo"
                img_url = f"/uploads/{unique_name}"
                vid_url = ""
            logger.info(f"Updated draft {draft_id} with file: {file_path}")
        except Exception as e:
            logger.error(f"Error saving uploaded file in update: {e}")
            return RedirectResponse(url=f"/?error=Failed to upload file: {str(e)}", status_code=303)
    elif media_url.strip():
        if m_type == "video":
            vid_url = media_url.strip()
            file_path = ""
        elif m_type == "photo":
            img_url = media_url.strip()
            file_path = ""
    elif m_type == "text":
        img_url = ""
        vid_url = ""
        file_path = ""

    update_draft(
        draft_id=draft_id,
        caption=caption.strip(),
        image_url=img_url,
        video_url=vid_url,
        local_file_path=file_path,
        media_type=m_type,
    )
    return RedirectResponse(url="/?msg=draft_updated", status_code=303)


@app.post("/drafts/{draft_id}/regenerate-image")
async def regenerate_image_for_draft(draft_id: str):
    """
    Regenerates a fresh AI image for an existing draft using its topic/keyword.
    """
    draft = get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    keyword = draft.get("keyword") or draft.get("topic") or config.DEFAULT_POST_TOPIC
    new_img_url = get_free_image_url(keyword, seed=random.randint(100, 999999))

    update_draft(
        draft_id=draft_id,
        image_url=new_img_url,
        video_url="",
        local_file_path="",
        media_type="photo",
    )
    logger.info(f"Regenerated AI image for draft {draft_id}: {new_img_url}")
    return RedirectResponse(url="/?msg=image_regenerated", status_code=303)


@app.post("/drafts/{draft_id}/delete")
async def remove_draft(draft_id: str):
    """Deletes a draft from the queue."""
    delete_draft(draft_id)
    return RedirectResponse(url="/?msg=deleted", status_code=303)


# ==============================================================================
# 2. Facebook Webhook Verification (GET /webhook)
# ==============================================================================
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == config.FB_VERIFY_TOKEN:
        logger.info("Facebook Webhook verified successfully!")
        return Response(content=challenge, media_type="text/plain")
    else:
        logger.warning(f"Webhook verification failed! Received token: {token}")
        raise HTTPException(status_code=403, detail="Verification token mismatch")


# ==============================================================================
# 3. Facebook Webhook Event Receiver (POST /webhook)
# ==============================================================================
async def process_incoming_message(sender_id: str, message_text: str):
    try:
        send_typing_indicator(sender_id, "typing_on")
        logger.info(f"Generating AI reply for sender {sender_id}: '{message_text}'")
        ai_reply = generate_chat_reply(sender_id, message_text)
        send_messenger_reply(sender_id, ai_reply)
        send_typing_indicator(sender_id, "typing_off")
    except Exception as e:
        logger.error(f"Error processing message for {sender_id}: {e}")


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
        logger.info(f"Incoming Webhook Payload: {payload}")
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return JSONResponse(content={"status": "invalid json"}, status_code=400)

    if payload.get("object") == "page":
        for entry in payload.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                if not sender_id:
                    continue

                user_text = ""
                message_id = ""

                # Case 1: Postback event (e.g., Get Started button or menu)
                if "postback" in messaging_event:
                    postback = messaging_event["postback"]
                    user_text = postback.get("title") or postback.get("payload") or "Get Started"
                    message_id = f"pb_{messaging_event.get('timestamp')}_{sender_id}"

                # Case 2: Standard message event (Text, Sticker/Thumbs up, or Attachment)
                elif "message" in messaging_event:
                    message = messaging_event["message"]
                    if message.get("is_echo"):
                        continue
                    message_id = message.get("mid", "")

                    if "text" in message and message["text"]:
                        user_text = message["text"].strip()
                    elif message.get("sticker_id"):
                        # User sent a sticker or Facebook thumbs up (like button)
                        user_text = "👍"
                    elif message.get("attachments"):
                        att_type = message["attachments"][0].get("type", "ফাইল")
                        user_text = f"[{att_type} পাঠিয়েছেন]"

                if not user_text:
                    continue

                if message_id and message_id in processed_message_ids:
                    logger.info(f"Duplicate message ignored: {message_id}")
                    continue
                if message_id:
                    processed_message_ids.append(message_id)

                logger.info(f"New incoming message from {sender_id}: {user_text}")
                background_tasks.add_task(
                    process_incoming_message, sender_id, user_text
                )

        return Response(content="EVENT_RECEIVED", status_code=200)

    return Response(content="NOT_A_PAGE_EVENT", status_code=404)
