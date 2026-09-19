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
from services.image_service import get_free_image_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fb_automation")

# Track recent message IDs to prevent duplicate webhook processing
processed_message_ids = deque(maxlen=500)

# Background scheduler for preparing daily draft posts
scheduler = AsyncIOScheduler()


async def scheduled_daily_post():
    """
    Scheduled task to generate a daily draft post for the approval dashboard.
    NOTE: Stored in draft_store for user approval before publishing to Facebook.
    """
    logger.info("Preparing scheduled daily DRAFT post for user review...")
    try:
        caption, keyword, visual_prompt = generate_page_post(config.DEFAULT_POST_TOPIC)
        image_url = get_free_image_url(keyword, visual_prompt)
        # Add to local draft store waiting for human approval
        draft = add_draft(caption, image_url, topic=config.DEFAULT_POST_TOPIC, keyword=keyword)
        logger.info(f"Daily draft prepared successfully! Draft ID: {draft['id']}")
    except Exception as e:
        logger.error(f"Error preparing scheduled daily draft post: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start APScheduler to prepare drafts
    logger.info("Starting background scheduler for daily draft posts...")
    trigger = CronTrigger(
        hour=config.POST_SCHEDULE_HOUR,
        minute=config.POST_SCHEDULE_MINUTE,
    )
    scheduler.add_job(
        scheduled_daily_post,
        trigger=trigger,
        id="daily_facebook_draft_post",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started! Drafts prepared daily at {config.POST_SCHEDULE_HOUR:02d}:{config.POST_SCHEDULE_MINUTE:02d} (Human Approval Mode: Enabled)"
    )
    yield
    # Shutdown: Stop scheduler
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


app = FastAPI(
    title="NewGo Learn Auto - Facebook AI Approval Dashboard",
    description="One-Click Post Approval Dashboard and AI Messenger Customer Service Bot.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def home(msg: Optional[str] = None, error: Optional[str] = None):
    """Modern, intuitive Post Approval Dashboard."""
    is_gemini_configured = bool(config.GEMINI_API_KEY and config.GEMINI_API_KEY != "your_gemini_api_key_here")
    is_fb_configured = bool(config.FB_PAGE_ACCESS_TOKEN and config.FB_PAGE_ACCESS_TOKEN != "your_page_access_token_here")
    
    pending_drafts = get_pending_drafts()
    published_drafts = get_published_drafts(limit=5)

    alert_html = ""
    if msg == "draft_created":
        alert_html = '<div class="alert alert-success">✨ নতুন পোস্টের খসড়া তৈরি হয়েছে! নিচে দেখে অনুমোদন দিন।</div>'
    elif msg == "published":
        alert_html = '<div class="alert alert-success">🎉 পোস্টটি সফলভাবে আপনার ফেসবুক পেজে পাবলিশ হয়েছে!</div>'
    elif msg == "deleted":
        alert_html = '<div class="alert alert-info">🗑️ ড্রাফটটি সফলভাবে ডিলিট করা হয়েছে।</div>'
    elif error:
        alert_html = f'<div class="alert alert-error">❌ এরর: {html.escape(error)}</div>'

    # Build Pending Draft Cards HTML
    pending_cards_html = ""
    if not pending_drafts:
        pending_cards_html = """
        <div class="empty-state">
            <p>বর্তমানে অনুমোদনের অপেক্ষায় কোনো পোস্ট নেই।</p>
            <p style="color: #94a3b8; font-size: 0.9rem;">নিচের বাটনে ক্লিক করে এখনই একটি নতুন পোস্ট জেনারেট করুন অথবা প্রতিদিন নির্ধারিত সময়ে এআই স্বয়ংক্রিয়ভাবে নতুন ড্রাফট তৈরি করে রাখবে।</p>
        </div>
        """
    else:
        for d in pending_drafts:
            safe_caption = html.escape(d.get("caption", ""))
            safe_img = html.escape(d.get("image_url", ""))
            safe_topic = html.escape(d.get("topic", ""))
            draft_id = d["id"]
            created_at = d.get("created_time_str", "Today")

            pending_cards_html += f"""
            <div class="card post-card">
                <div class="post-header">
                    <span class="badge-pending">⏳ অনুমোদনের অপেক্ষায় (Pending Approval)</span>
                    <span class="post-time">{created_at}</span>
                </div>
                <div class="post-body">
                    <div class="img-preview-col">
                        <img src="{safe_img}" alt="Generated Image" class="post-img" loading="lazy" />
                        <span class="topic-tag">টপিক: {safe_topic}</span>
                    </div>
                    <div class="caption-col">
                        <form action="/drafts/{draft_id}/approve" method="post" class="caption-form">
                            <label class="form-label">পোস্টের ক্যাপশন (প্রয়োজনে এডিট করুন):</label>
                            <textarea name="caption" class="caption-textarea" rows="8">{safe_caption}</textarea>
                            <div class="card-actions">
                                <button type="submit" class="btn btn-approve">🚀 ফেসবুকে পোস্ট করুন (Approve & Post)</button>
                            </div>
                        </form>
                        <form action="/drafts/{draft_id}/delete" method="post" style="margin-top: 0.5rem;">
                            <button type="submit" class="btn btn-delete" onclick="return confirm('এই ড্রাফটটি ডিলিট করতে চান?');">🗑️ ড্রাফট ডিলিট করুন</button>
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
            snippet = html.escape(p.get("caption", "")[:100] + "...")
            fb_id = p.get("fb_post_id", "")
            published_list_html += f"""
            <div class="pub-item">
                <div>
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
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--bg); color: var(--text); padding: 1.5rem; margin: 0; }}
            .container {{ max-width: 950px; margin: 0 auto; }}
            header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }}
            h1 {{ margin: 0; color: #38bdf8; font-size: 1.6rem; }}
            .badge-safe {{ background: #065f46; color: #34d399; padding: 0.4rem 0.9rem; border-radius: 20px; font-size: 0.85rem; font-weight: bold; }}
            
            .alert {{ padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; font-weight: 500; }}
            .alert-success {{ background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }}
            .alert-info {{ background: #1e3a8a; color: #bfdbfe; border: 1px solid #3b82f6; }}
            .alert-error {{ background: #7f1d1d; color: #fecaca; border: 1px solid #dc2626; }}

            .section-title {{ color: #e2e8f0; font-size: 1.25rem; margin: 1.5rem 0 1rem; display: flex; align-items: center; justify-content: space-between; }}
            
            .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
            
            /* Generator Form */
            .gen-form {{ display: flex; gap: 0.8rem; flex-wrap: wrap; }}
            .gen-input {{ flex: 1; min-width: 250px; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.75rem 1rem; border-radius: 8px; font-size: 0.95rem; }}
            .gen-input:focus {{ outline: none; border-color: #38bdf8; }}
            
            /* Post Cards */
            .post-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.6rem; }}
            .badge-pending {{ background: #854d0e; color: #fef08a; padding: 0.25rem 0.6rem; border-radius: 12px; font-size: 0.8rem; font-weight: bold; }}
            .post-time {{ color: #94a3b8; font-size: 0.85rem; }}
            .post-body {{ display: grid; grid-template-columns: 320px 1fr; gap: 1.5rem; }}
            @media (max-width: 768px) {{ .post-body {{ grid-template-columns: 1fr; }} }}
            
            .post-img {{ width: 100%; border-radius: 8px; object-fit: cover; aspect-ratio: 16/9; border: 1px solid var(--border); }}
            .topic-tag {{ display: block; color: #94a3b8; font-size: 0.8rem; margin-top: 0.5rem; word-break: break-word; }}
            
            .form-label {{ display: block; color: #cbd5e1; font-weight: 500; font-size: 0.9rem; margin-bottom: 0.5rem; }}
            .caption-textarea {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid var(--border); color: #fff; padding: 0.75rem; border-radius: 8px; font-size: 0.95rem; font-family: inherit; line-height: 1.5; resize: vertical; }}
            .caption-textarea:focus {{ outline: none; border-color: #38bdf8; }}
            
            .card-actions {{ margin-top: 1rem; display: flex; gap: 0.8rem; }}
            .btn {{ padding: 0.75rem 1.2rem; border-radius: 8px; font-weight: bold; font-size: 0.95rem; border: none; cursor: pointer; transition: all 0.2s; }}
            .btn-primary {{ background: var(--primary); color: #fff; }}
            .btn-primary:hover {{ background: var(--primary-hover); }}
            .btn-approve {{ background: var(--success); color: #fff; flex: 1; }}
            .btn-approve:hover {{ background: var(--success-hover); }}
            .btn-delete {{ background: transparent; color: #f87171; border: 1px solid #ef4444; font-size: 0.85rem; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; }}
            .btn-delete:hover {{ background: rgba(239,68,68,0.1); }}

            .empty-state {{ text-align: center; padding: 2.5rem 1rem; color: #94a3b8; background: var(--card-bg); border-radius: 12px; border: 1px dashed var(--border); }}

            /* Published list */
            .pub-item {{ display: flex; justify-content: space-between; align-items: center; padding: 0.8rem 0; border-bottom: 1px solid var(--border); }}
            .pub-item:last-child {{ border-bottom: none; }}
            .badge-pub {{ background: #064e3b; color: #34d399; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 10px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1>🚀 NewGo Learn Auto</h1>
                    <span style="color: #94a3b8; font-size: 0.9rem;">পোস্ট অনুমোদন ড্যাশবোর্ড (One-Click Post Approval Dashboard)</span>
                </div>
                <span class="badge-safe">🛡️ আপনার অনুমতি ছাড়া কোনো পোস্ট হবে না</span>
            </header>

            {alert_html}

            <!-- Post Generator Section -->
            <div class="card">
                <h3 style="margin-top: 0; color: #38bdf8;">✨ নতুন পোস্টের খসড়া তৈরি করুন (Generate New Draft)</h3>
                <p style="color: #cbd5e1; font-size: 0.9rem; margin-top: 0;">এআই দিয়ে একটি আকর্ষণীয় ক্যাপশন এবং ছবি তৈরি করে নিচে প্রিভিউ দেখুন:</p>
                <form action="/drafts/generate" method="post" class="gen-form">
                    <input type="text" name="topic" class="gen-input" placeholder="টপিক লিখুন (যেমন: ChatGPT দিয়ে কাজ দ্রুত করার উপায়) অথবা খালি রাখুন..." />
                    <button type="submit" class="btn btn-primary">⚡ নতুন ড্রাফট তৈরি করুন</button>
                </form>
            </div>

            <!-- Pending Approval Section -->
            <div class="section-title">
                <span>⏳ অনুমোদনের অপেক্ষায় খসড়া পোস্টসমূহ ({len(pending_drafts)})</span>
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
    return {"status": "ok", "service": "facebook-ai-automation", "mode": "approval_dashboard"}


# ==============================================================================
# 1. Draft Actions (Generate, Approve, Delete)
# ==============================================================================
@app.post("/drafts/generate")
async def generate_new_draft(topic: str = Form("")):
    """Generates an AI post with caption & image and saves as pending draft."""
    target_topic = topic.strip() or config.DEFAULT_POST_TOPIC
    logger.info(f"User requested manual draft generation for topic: '{target_topic}'")
    try:
        caption, keyword, visual_prompt = generate_page_post(target_topic)
        image_url = get_free_image_url(keyword, visual_prompt)
        add_draft(caption, image_url, topic=target_topic, keyword=keyword)
        return RedirectResponse(url="/?msg=draft_created", status_code=303)
    except Exception as e:
        logger.error(f"Error generating draft: {e}")
        return RedirectResponse(url=f"/?error={str(e)}", status_code=303)


@app.post("/drafts/{draft_id}/approve")
async def approve_and_publish_draft(draft_id: str, caption: str = Form(...)):
    """
    Human-in-the-Loop Action:
    User clicked 'Approve & Post'. Publishes to Facebook Page and marks draft as published.
    """
    draft = get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    image_url = draft.get("image_url", "")
    logger.info(f"User APPROVED draft ID {draft_id}. Publishing to Facebook Page...")

    # Publish LIVE to Facebook (as_draft=False because human explicitly approved it)
    result = publish_post_to_page(message=caption.strip(), image_url=image_url, as_draft=False)

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
