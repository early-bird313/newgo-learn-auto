import asyncio
from collections import deque
from contextlib import asynccontextmanager
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

import config
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
    Scheduled task to generate a daily draft post for the Facebook Page.
    NOTE: Saved as a DRAFT in Meta Business Suite for user approval before publishing.
    """
    logger.info("Preparing scheduled daily DRAFT post for user review...")
    try:
        caption, keyword, visual_prompt = generate_page_post(config.DEFAULT_POST_TOPIC)
        image_url = get_free_image_url(keyword, visual_prompt)
        # Always create as draft so nothing is published without user's approval
        result = publish_post_to_page(caption, image_url, as_draft=True)
        logger.info(f"Scheduled draft post result: {result}")
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
        f"Scheduler started! Drafts prepared daily at {config.POST_SCHEDULE_HOUR:02d}:{config.POST_SCHEDULE_MINUTE:02d} (Draft Mode: Enabled)"
    )
    yield
    # Shutdown: Stop scheduler
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


app = FastAPI(
    title="Facebook Page Automation & AI Chatbot",
    description="Intelligent Messenger replies and automated draft post generation with full user approval.",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def home():
    """Attractive, informative status dashboard."""
    is_gemini_configured = bool(config.GEMINI_API_KEY and config.GEMINI_API_KEY != "your_gemini_api_key_here")
    is_fb_configured = bool(config.FB_PAGE_ACCESS_TOKEN and config.FB_PAGE_ACCESS_TOKEN != "your_page_access_token_here")
    is_page_id_set = bool(config.FB_PAGE_ID and config.FB_PAGE_ID != "your_facebook_page_id_here")

    def badge(status: bool) -> str:
        if status:
            return '<span style="color: #10b981; font-weight: bold;">✔ Active / Configured</span>'
        return '<span style="color: #ef4444; font-weight: bold;">✖ Missing / Not Configured</span>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NewGo Learn Auto - Facebook AI Dashboard</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; margin: 0; }}
            .container {{ max-width: 800px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
            h1 {{ color: #38bdf8; margin-top: 0; }}
            .badge-safe {{ display: inline-block; background: #065f46; color: #34d399; padding: 0.3rem 0.8rem; border-radius: 20px; font-size: 0.85rem; font-weight: bold; margin-bottom: 1rem; }}
            .card {{ background: #334155; padding: 1.2rem; border-radius: 8px; margin-bottom: 1.5rem; }}
            .status-item {{ display: flex; justify-content: space-between; padding: 0.6rem 0; border-bottom: 1px solid #475569; }}
            .status-item:last-child {{ border-bottom: none; }}
            .btn {{ display: inline-block; background: #0284c7; color: white; padding: 0.8rem 1.5rem; border-radius: 6px; text-decoration: none; font-weight: bold; border: none; cursor: pointer; transition: background 0.2s; }}
            .btn:hover {{ background: #0369a1; }}
            code {{ background: #0f172a; padding: 0.2rem 0.5rem; border-radius: 4px; color: #f43f5e; font-family: Consolas, monospace; }}
            .info-box {{ background: #1e3a8a; border-left: 4px solid #60a5fa; padding: 1rem; border-radius: 4px; margin-bottom: 1.5rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <span class="badge-safe">🛡️ ড্রাফট মোড সক্রিয় (Draft Mode - 100% User Permission Required)</span>
            <h1>🚀 NewGo Learn Auto Dashboard</h1>
            <p>আপনার ফেসবুক পেজের এআই মেসেঞ্জার চ্যাটবট এবং ড্রাফট পোস্ট অটোমেশন সার্ভার সক্রিয় রয়েছে।</p>
            
            <div class="info-box">
                <strong>📌 পোস্টিং পলিসি:</strong> এআই আপনার অনুমতি ছাড়া কোনো পোস্ট পেজের ওয়ালে লাইভ করবে না। সকল পোস্ট আপনার ফেসবুক পেজের <strong>Meta Business Suite &rarr; Content &rarr; Drafts (খসড়া)</strong> সেকশনে জমা হবে। আপনি প্রিভিউ দেখে <em>"Publish"</em> বাটনে ক্লিক করলেই কেবল পোস্টটি সবার জন্য দৃশ্যমান হবে।
            </div>

            <div class="card">
                <h3>সার্ভার স্ট্যাটাস:</h3>
                <div class="status-item">
                    <span>গুগল জেমিনি এআই মডেল:</span>
                    <span style="color: #38bdf8; font-weight: bold;">{config.GEMINI_MODEL} (Auto-fallback enabled)</span>
                </div>
                <div class="status-item">
                    <span>পেজ কানেকশন:</span>
                    <span>{badge(is_fb_configured)}</span>
                </div>
                <div class="status-item">
                    <span>ফেসবুক পেজ আইডি:</span>
                    <span><code>{config.FB_PAGE_ID if is_page_id_set else 'Not Configured'}</code></span>
                </div>
                <div class="status-item">
                    <span>পোস্ট মোড:</span>
                    <span style="color: #fbbf24; font-weight: bold;">Draft Only (খসড়া তৈরি)</span>
                </div>
            </div>

            <div class="card">
                <h3>টেস্ট ও ড্রাফট জেনারেটর:</h3>
                <p>নিচের বাটনে ক্লিক করলে এআই একটি নতুন পোস্ট এবং আকর্ষণীয় ছবি তৈরি করে আপনার ফেসবুক পেজের ড্রাফট সেকশনে জমা করবে:</p>
                <form action="/trigger-post" method="post" style="display: inline;">
                    <button type="submit" class="btn">📝 নতুন ড্রাফট পোস্ট তৈরি করুন (Generate Draft)</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "facebook-ai-automation", "mode": "draft_enabled"}


# ==============================================================================
# 1. Facebook Webhook Verification (GET /webhook)
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
# 2. Facebook Webhook Event Receiver (POST /webhook)
# ==============================================================================
async def process_incoming_message(sender_id: str, message_text: str):
    """Background task to generate Gemini response and send reply via Facebook Send API."""
    try:
        # Show typing indicator to customer
        send_typing_indicator(sender_id, "typing_on")

        # Generate intelligent response via Gemini + Knowledge Base
        logger.info(f"Generating AI reply for sender {sender_id}: '{message_text}'")
        ai_reply = generate_chat_reply(sender_id, message_text)

        # Send response back to Messenger
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

                # Handle normal user text messages
                if message and "text" in message:
                    message_id = message.get("mid")
                    # Ignore echoes (messages sent by our own page)
                    if message.get("is_echo"):
                        continue

                    # Deduplication check
                    if message_id in processed_message_ids:
                        logger.info(f"Skipping already processed message {message_id}")
                        continue
                    if message_id:
                        processed_message_ids.append(message_id)

                    user_text = message.get("text", "").strip()
                    logger.info(f"New incoming message from {sender_id}: {user_text}")

                    # Dispatch AI response in background task
                    background_tasks.add_task(
                        process_incoming_message, sender_id, user_text
                    )

        return Response(content="EVENT_RECEIVED", status_code=200)

    return Response(content="NOT_A_PAGE_EVENT", status_code=404)


# ==============================================================================
# 3. Post Trigger API (POST /trigger-post) -> ALWAYS SAVED AS DRAFT
# ==============================================================================
@app.post("/trigger-post")
@app.get("/trigger-post")
async def trigger_post(
    topic: Optional[str] = Query(None, description="Optional custom topic for the post"),
    as_draft: bool = Query(True, description="Always create as unpublished draft for review"),
):
    """
    Creates an unpublished DRAFT post for user review in Meta Business Suite.
    """
    target_topic = topic or config.DEFAULT_POST_TOPIC
    logger.info(f"Generating draft post with topic: '{target_topic}'")

    caption, keyword, visual_prompt = generate_page_post(target_topic)
    image_url = get_free_image_url(keyword, visual_prompt)

    # By default, as_draft is True
    publish_result = publish_post_to_page(caption, image_url, as_draft=as_draft)

    return {
        "success": publish_result.get("success", False),
        "mode": "draft" if as_draft else "live",
        "topic": target_topic,
        "image_keyword": keyword,
        "image_url": image_url,
        "caption": caption,
        "facebook_response": publish_result,
        "note": "This post was created as a DRAFT. Review and publish it from Facebook Page -> Meta Business Suite -> Content -> Drafts.",
    }
