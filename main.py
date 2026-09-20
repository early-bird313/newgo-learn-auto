import asyncio
from collections import deque
from contextlib import asynccontextmanager
import html
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import config
from services.draft_store import (
    add_draft,
    delete_draft,
    get_current_bst_time_str,
    get_draft_by_id,
    get_pending_drafts,
    get_published_drafts,
    mark_draft_as_published,
)
from services.facebook_service import (
    publish_post_to_page,
    send_messenger_reply,
    send_typing_indicator,
)
from services.gemini_service import generate_chat_reply, generate_page_post
from services.google_sheets_service import import_drafts_from_google_sheet
from services.image_service import get_free_image_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fb_automation")

# Track recent message IDs to prevent duplicate webhook processing
processed_message_ids = deque(maxlen=500)

# Background scheduler for morning and evening draft generation
scheduler = AsyncIOScheduler()


async def scheduled_daily_post():
    """
    Scheduled task to prepare a draft post (sakal 9:00 AM & shondha 6:00 PM BST).
    Checks Google Sheet first if configured, else uses Gemini AI topic.
    NOTE: Stored in draft_store for user review and approval before posting to Facebook.
    """
    logger.info("Executing scheduled draft creation (Bangladesh Timezone)...")
    try:
        # 1. Try importing an unused topic from Google Sheet if configured
        if config.GOOGLE_SHEET_CSV_URL:
            count, _ = import_drafts_from_google_sheet(config.GOOGLE_SHEET_CSV_URL, max_count=1)
            if count > 0:
                logger.info("Successfully created scheduled draft from Google Sheet!")
                return

        # 2. Otherwise generate via Gemini AI
        caption, keyword, visual_prompt = generate_page_post(config.DEFAULT_POST_TOPIC)
        image_url = get_free_image_url(keyword, visual_prompt)
        draft = add_draft(
            caption=caption,
            image_url=image_url,
            topic=config.DEFAULT_POST_TOPIC,
            keyword=keyword,
            media_type="photo",
        )
        logger.info(f"Scheduled draft prepared successfully! Draft ID: {draft['id']}")
    except Exception as e:
        logger.error(f"Error preparing scheduled draft post: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Register Morning 9:00 AM and Evening 6:00 PM schedules (Asia/Dhaka)
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

    # Evening: 6:00 PM BST (18:00)
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
    yield
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


app = FastAPI(
    title="NewGo Learn Auto - Facebook AI Approval Dashboard",
    description="One-Click Post Approval Dashboard, Media Support (Text/Photo/Video), Google Sheets Sync, and AI Messenger Bot.",
    version="2.5.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def home(msg: Optional[str] = None, error: Optional[str] = None):
    """Modern, full-featured Post Approval Dashboard."""
    pending_drafts = get_pending_drafts()
    published_drafts = get_published_drafts(limit=10)
    current_time = get_current_bst_time_str()

    alert_html = ""
    if msg == "draft_created":
        alert_html = '<div class="alert alert-success">✨ নতুন পোস্টের ড্রাফট তৈরি হয়েছে! নিচে দেখে অনুমোদন দিন।</div>'
    elif msg == "published":
        alert_html = '<div class="alert alert-success">🎉 পোস্টটি সফলভাবে আপনার ফেসবুক পেজে লাইভ হয়েছে!</div>'
    elif msg == "deleted":
        alert_html = '<div class="alert alert-info">🗑️ ড্রাফটটি সফলভাবে মুছে ফেলা হয়েছে।</div>'
    elif msg == "sheet_imported":
        alert_html = '<div class="alert alert-success">📊 গুগল শিট থেকে সফলভাবে কনটেন্ট ইমপোর্ট করে ড্রাফট তৈরি করা হয়েছে!</div>'
    elif error:
        alert_html = f'<div class="alert alert-error">❌ এরর: {html.escape(error)}</div>'

    # Build Pending Draft Cards HTML
    pending_cards_html = ""
    if not pending_drafts:
        pending_cards_html = """
        <div class="empty-state">
            <p style="font-size: 1.1rem; color: #cbd5e1; margin-bottom: 0.4rem;">বর্তমানে অনুমোদনের অপেক্ষায় কোনো পোস্ট নেই।</p>
            <p style="color: #94a3b8; font-size: 0.9rem; margin: 0;">নিচের অপশনগুলো দিয়ে নতুন ড্রাফট তৈরি করুন অথবা প্রতিদিন সকাল ৯টা ও সন্ধ্যা ৬টায় এআই স্বয়ংক্রিয়ভাবে নতুন ড্রাফট বানিয়ে রাখবে।</p>
        </div>
        """
    else:
        for d in pending_drafts:
            safe_caption = html.escape(d.get("caption", ""))
            safe_img = html.escape(d.get("image_url", ""))
            safe_video = html.escape(d.get("video_url", ""))
            safe_topic = html.escape(d.get("topic", ""))
            media_type = d.get("media_type", "photo").lower()
            draft_id = d["id"]
            created_at = d.get("created_time_str", "Today")

            # Media preview element
            media_preview = ""
            media_badge = ""
            if media_type == "video" and safe_video:
                media_badge = '<span class="badge-media badge-video">🎥 Video Post</span>'
                media_preview = f"""
                <div class="video-container">
                    <video src="{safe_video}" controls class="post-media" preload="metadata">আপনার ব্রাউজারে ভিডিও সাপোর্ট করছে না</video>
                </div>
                <div class="media-url-snippet">URL: <a href="{safe_video}" target="_blank" style="color: #38bdf8;">{safe_video[:35]}...</a></div>
                """
            elif media_type == "photo" and safe_img:
                media_badge = '<span class="badge-media badge-photo">📷 Photo Post</span>'
                media_preview = f'<img src="{safe_img}" alt="Generated Image" class="post-media" loading="lazy" />'
            else:
                media_badge = '<span class="badge-media badge-text">📝 Text-Only Post</span>'
                media_preview = """
                <div class="text-only-box">
                    <span>📄 শুধুমাত্র টেক্সট পোস্ট (কোনো ছবি বা ভিডিও যুক্ত নেই)</span>
                </div>
                """

            pending_cards_html += f"""
            <div class="card post-card">
                <div class="post-header">
                    <div>
                        {media_badge}
                        <span class="badge-pending">⏳ অনুমোদনের অপেক্ষায়</span>
                    </div>
                    <span class="post-time">🕒 {created_at}</span>
                </div>
                <div class="post-body">
                    <div class="media-col">
                        {media_preview}
                        <span class="topic-tag">📌 টপিক: {safe_topic}</span>
                    </div>
                    <div class="caption-col">
                        <form action="/drafts/{draft_id}/approve" method="post">
                            <label class="form-label">পোস্টের ক্যাপশন (প্রয়োজনে এডিট করুন):</label>
                            <textarea name="caption" class="caption-textarea" rows="8">{safe_caption}</textarea>
                            
                            <div class="media-inputs">
                                <label class="form-label" style="margin-top: 0.5rem;">মিডিয়া লিংক পরিবর্তন করুন (ঐচ্ছিক):</label>
                                <input type="text" name="media_url" value="{safe_video if media_type == 'video' else safe_img}" class="input-text" placeholder="ছবির বা ভিডিওর সরাসরি লিঙ্ক (http...)" />
                                <div style="display: flex; gap: 1rem; margin-top: 0.5rem;">
                                    <label><input type="radio" name="media_type" value="photo" {'checked' if media_type == 'photo' else ''}> ছবি (Photo)</label>
                                    <label><input type="radio" name="media_type" value="video" {'checked' if media_type == 'video' else ''}> ভিডিও (Video)</label>
                                    <label><input type="radio" name="media_type" value="text" {'checked' if media_type == 'text' else ''}> শুধু টেক্সট</label>
                                </div>
                            </div>

                            <div class="card-actions">
                                <button type="submit" class="btn btn-approve">🚀 ফেসবুকে পোস্ট করুন (Approve & Post)</button>
                            </div>
                        </form>
                        <form action="/drafts/{draft_id}/delete" method="post" style="margin-top: 0.5rem;">
                            <button type="submit" class="btn btn-delete" onclick="return confirm('এই ড্রাফটটি মুছে ফেলতে চান?');">🗑️ ড্রাফট মুছুন</button>
                        </form>
                    </div>
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
        published_list_html = "<p style='color: #94a3b8; font-size: 0.9rem;'>এখনো কোনো পোস্ট অ্যাপ্রুভ করে পাবলিশ করা হয়নি।</p>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NewGo Learn Auto - Post Approval Dashboard</title>
        <style>
            :root {{
                --bg: #0f172a;
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
            .container {{ max-width: 1000px; margin: 0 auto; }}
            header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }}
            h1 {{ margin: 0; color: #38bdf8; font-size: 1.6rem; }}
            .header-badges {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
            .badge-safe {{ background: #065f46; color: #34d399; padding: 0.35rem 0.8rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
            .badge-tz {{ background: #1e3a8a; color: #93c5fd; padding: 0.35rem 0.8rem; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
            
            .alert {{ padding: 0.9rem 1.2rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 500; }}
            .alert-success {{ background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }}
            .alert-info {{ background: #1e3a8a; color: #bfdbfe; border: 1px solid #3b82f6; }}
            .alert-error {{ background: #7f1d1d; color: #fecaca; border: 1px solid #dc2626; }}

            .section-title {{ color: #e2e8f0; font-size: 1.2rem; margin: 1.8rem 0 0.8rem; display: flex; align-items: center; justify-content: space-between; }}
            .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
            
            /* Tabs / Grid for Creation Options */
            .creation-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; margin-bottom: 1.5rem; }}
            @media (max-width: 768px) {{ .creation-grid {{ grid-template-columns: 1fr; }} }}

            .input-text {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.65rem 0.85rem; border-radius: 6px; font-size: 0.9rem; }}
            .input-text:focus {{ outline: none; border-color: #38bdf8; }}
            .select-box {{ background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.65rem 0.85rem; border-radius: 6px; font-size: 0.9rem; }}

            /* Post Cards */
            .post-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
            .badge-pending {{ background: #854d0e; color: #fef08a; padding: 0.2rem 0.5rem; border-radius: 10px; font-size: 0.75rem; font-weight: bold; margin-left: 0.4rem; }}
            .badge-media {{ padding: 0.2rem 0.5rem; border-radius: 10px; font-size: 0.75rem; font-weight: bold; }}
            .badge-photo {{ background: #0369a1; color: #bae6fd; }}
            .badge-video {{ background: #701a75; color: #f5d0fe; }}
            .badge-text {{ background: #334155; color: #e2e8f0; }}
            .post-time {{ color: #94a3b8; font-size: 0.85rem; font-weight: 500; }}

            .post-body {{ display: grid; grid-template-columns: 320px 1fr; gap: 1.5rem; }}
            @media (max-width: 768px) {{ .post-body {{ grid-template-columns: 1fr; }} }}
            
            .post-media {{ width: 100%; border-radius: 8px; object-fit: cover; aspect-ratio: 16/9; border: 1px solid var(--border); }}
            .text-only-box {{ display: flex; align-items: center; justify-content: center; background: #0f172a; border: 1px dashed var(--border); border-radius: 8px; aspect-ratio: 16/9; color: #94a3b8; font-size: 0.85rem; text-align: center; padding: 1rem; box-sizing: border-box; }}
            .media-url-snippet {{ font-size: 0.75rem; color: #94a3b8; margin-top: 0.4rem; word-break: break-all; }}
            .topic-tag {{ display: block; color: #94a3b8; font-size: 0.8rem; margin-top: 0.5rem; word-break: break-word; }}

            .form-label {{ display: block; color: #cbd5e1; font-weight: 500; font-size: 0.85rem; margin-bottom: 0.4rem; }}
            .caption-textarea {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.75rem; border-radius: 8px; font-size: 0.95rem; font-family: inherit; line-height: 1.5; resize: vertical; }}
            .caption-textarea:focus {{ outline: none; border-color: #38bdf8; }}
            
            .card-actions {{ margin-top: 1rem; display: flex; gap: 0.8rem; }}
            .btn {{ padding: 0.65rem 1.1rem; border-radius: 6px; font-weight: bold; font-size: 0.9rem; border: none; cursor: pointer; transition: all 0.2s; }}
            .btn-primary {{ background: var(--primary); color: #fff; }}
            .btn-primary:hover {{ background: var(--primary-hover); }}
            .btn-approve {{ background: var(--success); color: #fff; flex: 1; }}
            .btn-approve:hover {{ background: var(--success-hover); }}
            .btn-delete {{ background: transparent; color: #f87171; border: 1px solid #ef4444; font-size: 0.8rem; padding: 0.35rem 0.7rem; border-radius: 6px; cursor: pointer; }}
            .btn-delete:hover {{ background: rgba(239,68,68,0.1); }}

            .empty-state {{ text-align: center; padding: 2.5rem 1rem; background: var(--card-bg); border-radius: 12px; border: 1px dashed var(--border); }}
            .pub-item {{ display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 0; border-bottom: 1px solid var(--border); }}
            .pub-item:last-child {{ border-bottom: none; }}
            .badge-pub {{ background: #064e3b; color: #34d399; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 10px; font-weight: bold; }}
            
            .helper-text {{ font-size: 0.8rem; color: #94a3b8; margin-top: 0.3rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1>🚀 NewGo Learn Auto</h1>
                    <span style="color: #94a3b8; font-size: 0.9rem;">পোস্ট অনুমোদন ও কন্টেন্ট ম্যানেজমেন্ট ড্যাশবোর্ড</span>
                </div>
                <div class="header-badges">
                    <span class="badge-tz">🕒 {current_time}</span>
                    <span class="badge-safe">🛡️ অনুমোদনের পর পোস্ট লাইভ হবে</span>
                </div>
            </header>

            {alert_html}

            <!-- Creation Grid: AI Multi-Draft + Google Sheets Sync -->
            <div class="creation-grid">
                <!-- Box 1: AI Multi-Draft Generator -->
                <div class="card" style="margin-bottom: 0;">
                    <h3 style="margin-top: 0; color: #38bdf8; font-size: 1.1rem;">✨ এআই দিয়ে একাধিক ড্রাফট তৈরি (Multi-Draft)</h3>
                    <p class="helper-text">এআই দিয়ে এক ক্লিকে ১টি, ৩টি বা ৫টি পোস্টের ড্রাফট তৈরি করে রাখুন:</p>
                    <form action="/drafts/generate" method="post" style="display: flex; flex-direction: column; gap: 0.7rem;">
                        <input type="text" name="topic" class="input-text" placeholder="টপিক (যেমন: Top 5 AI Tools) অথবা খালি রাখুন..." />
                        <div style="display: flex; gap: 0.6rem; align-items: center;">
                            <label class="form-label" style="margin: 0; white-space: nowrap;">কয়টি ড্রাফট?</label>
                            <select name="count" class="select-box">
                                <option value="1">১টি ড্রাফট</option>
                                <option value="3" selected>৩টি ড্রাফট (Recommended)</option>
                                <option value="5">৫টি ড্রাফট</option>
                            </select>
                            <button type="submit" class="btn btn-primary" style="flex: 1;">⚡ তৈরি করুন</button>
                        </div>
                    </form>
                </div>

                <!-- Box 2: Google Sheets Sync -->
                <div class="card" style="margin-bottom: 0;">
                    <h3 style="margin-top: 0; color: #34d399; font-size: 1.1rem;">📊 গুগল শিট থেকে কন্টেন্ট ইমপোর্ট (Google Sheet)</h3>
                    <p class="helper-text">আপনার গুগল শিটের শেয়ারেবল লিংক দিন (কলাম: Topic, Caption, Media_Type, Media_URL):</p>
                    <form action="/drafts/import-sheet" method="post" style="display: flex; flex-direction: column; gap: 0.7rem;">
                        <input type="text" name="sheet_url" class="input-text" value="{html.escape(config.GOOGLE_SHEET_CSV_URL)}" placeholder="গুগল শিট লিংক পেস্ট করুন..." required />
                        <button type="submit" class="btn btn-primary" style="background: #059669;">📥 শিট থেকে ড্রাফট ইমপোর্ট করুন</button>
                    </form>
                </div>
            </div>

            <!-- Box 3: Custom Post Creator (Photo / Video / Text) -->
            <div class="card">
                <h3 style="margin-top: 0; color: #e2e8f0; font-size: 1.1rem;">✍️ নিজে কাস্টম পোস্ট তৈরি করুন (Text / Photo / Video)</h3>
                <form action="/drafts/create-custom" method="post" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div style="grid-column: 1 / -1;">
                        <label class="form-label">পোস্টের ক্যাপশন ও হ্যাশট্যাগ:</label>
                        <textarea name="caption" class="caption-textarea" rows="4" placeholder="আপনার পোস্টের বিস্তারিত বার্তা লিখুন..." required></textarea>
                    </div>
                    <div>
                        <label class="form-label">মিডিয়ার ধরন (Media Type):</label>
                        <select name="media_type" class="select-box" style="width: 100%;">
                            <option value="photo">📷 ছবি (Photo Post)</option>
                            <option value="video">🎥 ভিডিও (Video Post)</option>
                            <option value="text">📝 শুধুমাত্র টেক্সট (Text Only)</option>
                        </select>
                    </div>
                    <div>
                        <label class="form-label">ছবি বা ভিডিও লিংক (ঐচ্ছিক):</label>
                        <input type="text" name="media_url" class="input-text" placeholder="সরাসরি ছবির বা ভিডিওর URL..." />
                    </div>
                    <div style="grid-column: 1 / -1;">
                        <button type="submit" class="btn btn-primary" style="background: #475569;">➕ ড্রাফটে যুক্ত করুন</button>
                    </div>
                </form>
            </div>

            <!-- Pending Approval Section -->
            <div class="section-title">
                <span>⏳ অনুমোদনের অপেক্ষায় খসড়া পোস্টসমূহ ({len(pending_drafts)})</span>
                <span style="font-size: 0.85rem; color: #94a3b8;">দৈনিক শিডিউল: সকাল ৯:০০ ও সন্ধ্যা ৬:০০ (BST)</span>
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
            f"{config.SCHEDULE_EVENING_HOUR:02d}:{config.SCHEDULE_EVENING_MINUTE:02d} BST (Evening)",
        ],
    }


# ==============================================================================
# 1. Draft Actions (Generate Multi-Drafts, Import Sheet, Custom Post, Approve, Delete)
# ==============================================================================
@app.post("/drafts/generate")
async def generate_new_drafts(topic: str = Form(""), count: int = Form(1)):
    """Generates 1 or multiple AI drafts with captions & images."""
    target_topic = topic.strip() or config.DEFAULT_POST_TOPIC
    valid_count = max(1, min(count, 5))  # Limit between 1 and 5
    logger.info(f"Generating {valid_count} drafts for topic: '{target_topic}'")

    try:
        for i in range(valid_count):
            topic_variant = f"{target_topic} (আইডিয়া {i+1})" if valid_count > 1 else target_topic
            caption, keyword, visual_prompt = generate_page_post(topic_variant)
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
        logger.error(f"Error generating drafts: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


@app.post("/drafts/import-sheet")
async def import_from_sheet(sheet_url: str = Form("")):
    """Imports content from a Google Sheet and creates drafts."""
    target_url = sheet_url.strip() or config.GOOGLE_SHEET_CSV_URL
    if not target_url:
        return RedirectResponse(url="/?error=Google Sheet URL is empty", status_code=303)

    try:
        count, _ = import_drafts_from_google_sheet(target_url, max_count=5)
        if count > 0:
            return RedirectResponse(url="/?msg=sheet_imported", status_code=303)
        else:
            return RedirectResponse(url="/?error=No unused or valid rows found in Google Sheet", status_code=303)
    except Exception as e:
        logger.error(f"Google Sheet import error: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


@app.post("/drafts/create-custom")
async def create_custom_draft(
    caption: str = Form(...),
    media_type: str = Form("photo"),
    media_url: str = Form(""),
):
    """Manually creates a custom draft (Text, Photo, or Video)."""
    m_type = media_type.lower().strip()
    img_url = media_url.strip() if m_type == "photo" else ""
    vid_url = media_url.strip() if m_type == "video" else ""

    add_draft(
        caption=caption.strip(),
        image_url=img_url,
        video_url=vid_url,
        media_type=m_type,
        topic="Custom Manual Post",
    )
    return RedirectResponse(url="/?msg=draft_created", status_code=303)


@app.post("/drafts/{draft_id}/approve")
async def approve_and_publish_draft(
    draft_id: str,
    caption: str = Form(...),
    media_type: str = Form("photo"),
    media_url: str = Form(""),
):
    """
    Human-in-the-Loop Action:
    User clicked 'Approve & Post'. Publishes Text, Photo, or Video to Facebook Page.
    """
    draft = get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    m_type = media_type.lower().strip()
    img_url = media_url.strip() if m_type == "photo" else (draft.get("image_url") or "")
    vid_url = media_url.strip() if m_type == "video" else (draft.get("video_url") or "")

    logger.info(f"User APPROVED draft ID {draft_id} (Type: {m_type}). Publishing to Facebook Page...")

    # Publish LIVE to Facebook
    result = publish_post_to_page(
        message=caption.strip(),
        image_url=img_url,
        video_url=vid_url,
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
    except Exception as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return JSONResponse(content={"status": "invalid json"}, status_code=400)

    if payload.get("object") == "page":
        for entry in payload.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                message = messaging_event.get("message")

                if message and "text" in message:
                    message_id = message.get("mid")
                    if message.get("is_echo"):
                        continue
                    if message_id in processed_message_ids:
                        continue
                    if message_id:
                        processed_message_ids.append(message_id)

                    user_text = message.get("text", "").strip()
                    logger.info(f"New incoming message from {sender_id}: {user_text}")
                    background_tasks.add_task(
                        process_incoming_message, sender_id, user_text
                    )

        return Response(content="EVENT_RECEIVED", status_code=200)

    return Response(content="NOT_A_PAGE_EVENT", status_code=404)
