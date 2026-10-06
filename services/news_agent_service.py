import hashlib
import json
import logging
import random
import re
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import requests

import config
from services.draft_store import add_draft
from services.gemini_service import get_gemini_client
from services.image_service import get_free_image_url
from google.genai import types

logger = logging.getLogger(__name__)

MEMORY_FILE = config.BASE_DIR / "agent_memory.json"

# Reliable RSS and Atom news feeds for AI and Technology
AI_NEWS_FEEDS = [
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "type": "atom",
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "type": "rss",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "type": "rss",
    },
]

# Curated library of real-world AI tips, prompts & productivity hacks (Strictly Abstract / Tech only)
CURATED_TIPS_TOPICS = [
    "ChatGPT Advanced Prompt Engineering: Few-shot prompting and Chain-of-Thought technique for accurate answers",
    "How to use Claude & Gemini to summarize long PDF research papers and extract key data tables in minutes",
    "Top 5 Free AI Tools for vector graphics, logo icons, and automated workflow diagrams in 2026",
    "Automating daily repetitive work using AI and Google Sheets/Excel: Best formulas and workflow tips",
    "How to generate high-converting technical documentation and copywriting with AI without repetitive phrasing",
    "AI automation for spreadsheets and data analysis: Formula generation, cleaning messy data, and trend mapping",
    "Midjourney and Flux prompt tricks: How to generate cinematic 3D abstract product renders, glowing circuits, and tech hardware (no humans)",
    "How to build custom automated workflows using Free open-source AI models for productivity",
    "Audio & Audio Spectrum AI tricks: Removing background noise, audio frequency enhancement, and clean sound synthesis",
    "Secret AI search tricks: How to use Perplexity and Gemini Search to find deep research data with citations",
    "Coding with AI: How beginners can debug code, build small web tools, and learn programming faster",
]


# ==============================================================================
# 1. Agent Memory & Shuffle State Management
# ==============================================================================
def get_agent_memory() -> Dict[str, Any]:
    """Reads agent state from agent_memory.json or initializes defaults."""
    default_memory = {
        "last_mode": "tips",  # Start with 'tips' so the next run defaults to 'news'
        "seen_news_hashes": [],
        "total_posts_created": 0,
        "history": [],
    }
    if not MEMORY_FILE.exists():
        save_agent_memory(default_memory)
        return default_memory
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading agent_memory.json: {e}")
        return default_memory


def save_agent_memory(memory: Dict[str, Any]) -> None:
    """Saves agent memory to agent_memory.json."""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving agent_memory.json: {e}")


def get_next_mode() -> str:
    """
    Determines the next mode based on alternating shuffle:
    'news' -> 'tips' -> 'news' -> 'tips'...
    """
    mem = get_agent_memory()
    last = mem.get("last_mode", "tips").lower()
    return "news" if last == "tips" else "tips"


# ==============================================================================
# 2. News Scraper & Feed Hunter
# ==============================================================================
def clean_html(text: str) -> str:
    """Strips basic HTML tags and unescapes entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def parse_atom_feed(xml_content: str, source_name: str) -> List[Dict[str, str]]:
    """Parses Atom XML feed (e.g. The Verge)."""
    items = []
    try:
        root = ET.fromstring(xml_content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        for entry in entries:
            title_el = entry.find("atom:title", ns) or entry.find("title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            summary_el = (
                entry.find("atom:summary", ns)
                or entry.find("summary")
                or entry.find("atom:content", ns)
                or entry.find("content")
            )
            summary = clean_html(summary_el.text) if summary_el is not None and summary_el.text else ""

            link_el = entry.find("atom:link", ns) or entry.find("link")
            link = ""
            if link_el is not None:
                link = link_el.attrib.get("href", "") or (link_el.text or "").strip()

            if title:
                items.append({
                    "title": title,
                    "summary": summary[:600],
                    "link": link,
                    "source": source_name,
                })
    except Exception as e:
        logger.debug(f"Atom parse error for {source_name}: {e}")
    return items


def parse_rss_feed(xml_content: str, source_name: str) -> List[Dict[str, str]]:
    """Parses standard RSS 2.0 XML feed (e.g. TechCrunch, VentureBeat)."""
    items = []
    try:
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        item_nodes = channel.findall("item") if channel is not None else root.findall("item")
        for it in item_nodes:
            title_el = it.find("title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            desc_el = it.find("description")
            desc = clean_html(desc_el.text) if desc_el is not None and desc_el.text else ""

            link_el = it.find("link")
            link = link_el.text.strip() if link_el is not None and link_el.text else ""

            if title:
                items.append({
                    "title": title,
                    "summary": desc[:600],
                    "link": link,
                    "source": source_name,
                })
    except Exception as e:
        logger.debug(f"RSS parse error for {source_name}: {e}")
    return items


def fetch_latest_ai_news() -> List[Dict[str, str]]:
    """
    Fetches real-time AI news items from our list of trusted feeds.
    Returns parsed list of candidate news stories.
    """
    all_articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml, */*",
    }

    for feed in AI_NEWS_FEEDS:
        try:
            resp = requests.get(feed["url"], headers=headers, timeout=10)
            if resp.status_code == 200 and resp.text:
                if feed["type"] == "atom" or "<feed" in resp.text[:300]:
                    items = parse_atom_feed(resp.text, feed["name"])
                else:
                    items = parse_rss_feed(resp.text, feed["name"])
                logger.info(f"Fetched {len(items)} items from {feed['name']}")
                all_articles.extend(items)
        except Exception as e:
            logger.warning(f"Failed to fetch feed {feed['name']}: {e}")

    return all_articles


def get_fresh_news_article() -> Optional[Dict[str, str]]:
    """
    Selects a fresh, unseen news article.
    Filters out previously posted stories using hash tracking.
    """
    articles = fetch_latest_ai_news()
    if not articles:
        return None

    mem = get_agent_memory()
    seen_hashes = set(mem.get("seen_news_hashes", []))

    for art in articles:
        h = hashlib.md5(art["title"].lower().encode("utf-8")).hexdigest()
        if h not in seen_hashes:
            art["hash"] = h
            return art

    # If all current feed items have been seen, return the latest one with new timestamp
    latest = articles[0]
    latest["hash"] = hashlib.md5(latest["title"].lower().encode("utf-8")).hexdigest()
    return latest


# ==============================================================================
# 3. Gemini Post Generators (News & Tips)
# ==============================================================================
def generate_ai_news_post(article: Dict[str, str]) -> Tuple[str, str, str]:
    """
    Turns an English AI news article into an engaging Bengali Facebook post.
    Returns: (caption, image_keyword, visual_prompt)
    """
    client = get_gemini_client()
    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "Tech News")

    system_instruction = """
আপনি 'NewGo Learn' টেক ও এআই ফেসবুক পেজের একজন দক্ষ ও জনপ্রিয় টেক জার্নালিস্ট এবং সোশ্যাল মিডিয়া কন্টেন্ট ক্রিয়েটর।
আপনার কাজ হলো আন্তর্জাতিক শীর্ষ এআই ও প্রযুক্তি সংবাদকে সাধারণ ফেসবুক পাঠকদের জন্য অত্যন্ত আকর্ষণীয়, প্রাঞ্জল ও সহজে বোধগম্য বাংলায় একটি ভাইরাল পোস্ট তৈরি করা।

পোস্টের ফরম্যাট অবশ্যই নিচের মতো হতে হবে:
১. আকর্ষণীয় ও নজরকাড়া বাংলা হেডলাইন (উপযুক্ত ইমোজি সহ যেমন 🔥, 🚨, 🌐)
২. মূল খবরটির সহজ ও আকর্ষণীয় বিবরণ (১-২ প্যারাগ্রাফে সাধারণ মানুষের বোধগম্য ভাষায়)
৩. ৩-৪টি বুলেট পয়েন্টে মূল হাইলাইটস ও গুরুত্বপূর্ণ তথ্য (👉 বা • দিয়ে)
৪. এই খবরটি থেকে সাধারণ মানুষ বা তরুণদের জন্য কী শেখার বা সতর্ক হওয়ার আছে
৫. পাঠকদের সাথে এনগেজমেন্ট বাড়ানোর জন্য ১টি প্রশ্ন (যেমন: "এ বিষয়ে আপনার মতামত কি? কমেন্টে জানান!")
৬. খবরের সোর্স ক্রেডিট (যেমন: সূত্র: TechCrunch / The Verge)
৭. প্রাসঙ্গিক ৪-৫টি ট্রেন্ডিং হ্যাশট্যাগ (#AINews #NewGoLearn #TechUpdates #ArtificialIntelligence)

⚠️ কঠোর ছবি নির্দেশিকা (STRICT IMAGE RULES - ABSOLUTELY NO HUMANS / NO FEMALES):
- ছবিতে কোনো মানুষ, নারী, পুরুষ, মুখমণ্ডল, হাত বা মানব অবয়ব থাকা সম্পূর্ণ নিষেধ (Strictly NO humans, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands)।
- ছবির প্রম্পট (visual_prompt) হতে হবে শুধুমাত্র বিমূর্ত প্রযুক্তি ও আধুনিক ইলেকট্রনিক্স: যেমন glowing AI neural network, futuristic circuit board, cybernetic microchip, server rack hardware, abstract 3D data visualization, glowing code on sleek futuristic monitors।
- keyword হবে কেবল টেকনিক্যাল শব্দ (যেমন: "abstract ai neural circuit", "futuristic server hardware", "microchip technology")।

আউটপুটটি অবশ্যই কঠোরভাবে এই JSON ফরম্যাটে দিতে হবে:
{
  "caption": "সম্পূর্ণ ফেসবুক পোস্টটি এখানে থাকবে...",
  "keyword": "ছবির জন্য ২-৩ শব্দের ইংরেজি কি-ওয়ার্ড (যেমন: abstract ai neural circuit)",
  "visual_prompt": "ছবি তৈরির জন্য বিস্তারিত ইংরেজি প্রম্পট (যেমন: A futuristic glowing AI neural circuit board with luminous blue and gold data streams, abstract cybernetic technology, no humans, cinematic 8k)"
}
"""

    prompt = f"""
খবরের শিরোনাম: {title}
খবরের উৎস: {source}
খবরের সংক্ষিপ্ত বিবরণ: {summary}

অনুগ্রহ করে উপরের এআই খবরটি নিয়ে 'NewGo Learn' পেজের জন্য একটি তথ্যবহুল ও আকর্ষণীয় বাংলা ফেসবুক পোস্ট তৈরি করুন।
"""

    fallback_caption = f"""🔥 ব্রেকিং এআই আপডেট: {title}

আন্তর্জাতিক প্রযুক্তি বিশ্বে সম্প্রতি এআই নিয়ে বড় একটি পরিবর্তন এসেছে। {summary[:250]}...

📌 মূল বিষয়গুলো:
👉 নতুন প্রযুক্তির দ্রুত অগ্রগতি ও বিশ্বব্যাপী প্রভাব
👉 সাধারণ ব্যবহারকারী ও প্রফেশনালদের কাজের গতি বাড়ানোর সুযোগ
👉 ভবিষ্যতের কৃত্রিম বুদ্ধিমত্তার নতুন দিগন্ত

💡 আপনার ভাবনা কী? এই নতুন পরিবর্তন নিয়ে আপনি কী মনে করেন? কমেন্টে আপনার মতামত জানান!

সূত্র: {source}
#AINews #NewGoLearn #ArtificialIntelligence #TechUpdates #TechTrend"""

    if not client:
        return fallback_caption, "abstract ai neural circuit", "futuristic glowing AI neural network technology circuit board hardware, no humans, cinematic 8k"

    candidate_models = [config.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"]
    for m in candidate_models:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.7,
                ),
            )
            raw = (resp.text or "").strip()
            data = json.loads(raw)
            caption = data.get("caption", "").strip() or fallback_caption
            kw = data.get("keyword", "artificial intelligence tech")
            v_prompt = data.get("visual_prompt", "futuristic AI neural network technology")
            return caption, kw, v_prompt
        except Exception as e:
            logger.warning(f"Model {m} failed for news post: {e}. Trying next...")

    return fallback_caption, "artificial intelligence news", "futuristic artificial intelligence glowing technology concept"


def generate_ai_tips_post() -> Tuple[str, str, str]:
    """
    Generates an actionable, practical AI Tips & Tricks post in Bengali.
    Returns: (caption, image_keyword, visual_prompt)
    """
    client = get_gemini_client()
    selected_topic = random.choice(CURATED_TIPS_TOPICS)

    system_instruction = """
আপনি 'NewGo Learn' টেক পেজের একজন অভিজ্ঞ এআই ট্রেইনার এবং প্রফেশনাল কন্টেন্ট ক্রিয়েটর।
আপনার কাজ হলো সাধারণ শিক্ষার্থী, ফ্রিল্যান্সার ও পেশাজীবীদের জন্য অত্যন্ত কাজের ও ব্যবহারিক একটি "AI Tips & Tricks" পোস্ট বাংলায় তৈরি করা।

পোস্টের ফরম্যাট:
১. চোখ ধাঁধানো ক্যাপচি হেডলাইন (যেমন: 💡 ChatGPT সিক্রেট ট্রিকস: কাজের গতি দ্বিগুণ করার সহজ উপায়!)
২. সমস্যার বিবরণ ও কীভাবে এআই দিয়ে এটি ৫ মিনিটে সমাধান করা যায়
৩. স্টেপ-বাই-স্টেপ প্র্যাকটিক্যাল গাইড (১, ২, ৩ বা বুলেট পয়েন্টে)
৪. বাস্তবসম্মত ১টি প্রম্পট উদাহরণ (Prompt Template) কোটেশন দিয়ে তুলে ধরা
৫. শেষভাগে উৎসাহমূলক আহ্বান ও প্রশ্ন (যেমন: "আজই ট্রাই করে দেখুন! আপনার প্রিয় এআই টুল কোনটি?")
৬. প্রাসঙ্গিক ৫টি ট্রেন্ডিং হ্যাশট্যাগ (#AITips #NewGoLearn #ChatGPTTricks #ProductivityHacks #TechTips)

⚠️ কঠোর ছবি নির্দেশিকা (STRICT IMAGE RULES - ABSOLUTELY NO HUMANS / NO FEMALES):
- ছবিতে কোনো মানুষ, নারী, পুরুষ, অবয়ব, মুখমণ্ডল, হাত বা প্রতিকৃতি থাকা সম্পূর্ণ নিষেধ (Strictly NO humans, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands)।
- ছবির প্রম্পট (visual_prompt) হতে হবে শুধুমাত্র বিমূর্ত প্রযুক্তি ও আধুনিক ইলেকট্রনিক্স: যেমন glowing holographic code lines, abstract 3D geometric AI nodes, cybernetic data stream, futuristic minimalist workstation with empty chair and glowing code monitors (strictly no people)।
- keyword হবে কেবল টেকনিক্যাল শব্দ (যেমন: "abstract ai productivity interface", "futuristic neural code visualization")।

আউটপুটটি অবশ্যই কঠোরভাবে এই JSON ফরম্যাটে দিতে হবে:
{
  "caption": "সম্পূর্ণ ফেসবুক পোস্টটি এখানে থাকবে...",
  "keyword": "ছবির জন্য ২-৩ শব্দের ইংরেজি কি-ওয়ার্ড (যেমন: abstract ai code interface)",
  "visual_prompt": "ছবি তৈরির জন্য ইংরেজি প্রম্পট (যেমন: An abstract 3D visualization of glowing AI algorithms and glowing holographic neural networks on a futuristic dark background, no humans, cinematic 8k)"
}
"""

    prompt = f"টপিক: {selected_topic}\nঅনুগ্রহ করে এই বিষয়ের ওপর ব্যবহারিক ও সহজে কাজে লাগানোর মতো একটি চমৎকার বাংলা টিপস অ্যান্ড ট্রিকস পোস্ট তৈরি করুন।"

    fallback_caption = f"""💡 এআই টিপস অ্যান্ড ট্রিকস: {selected_topic}

কাজের গতি কয়েকগুণ বাড়িয়ে নিতে কৃত্রিম বুদ্ধিমত্তা (AI) এখন সবচেয়ে বড় হাতিয়ার! নিচে দেওয়া সহজ ট্রিকটি ব্যবহার করে আপনার প্রতিদিনের ঘণ্টার পর ঘণ্টা সময় বাঁচাতে পারেন:

📌 প্র্যাকটিক্যাল স্টেপসমূহ:
১. পরিষ্কার ও স্পষ্ট নির্দেশনা দিন: এআইকে কোনো সাধারণ নির্দেশ না দিয়ে конкретный রোল দিন।
২. উদাহরণ যুক্ত করুন: আপনি ঠিক যেমন আউটপুট চান, তার একটি ছোট নমুনা দিন।
৩. আউটপুট যাচাই করে স্টেপ-বাই-স্টেপ আরও উন্নত করুন।

💬 আপনি কি নিয়মিত এআই টুল ব্যবহার করছেন? আপনার পছন্দের ট্রিক কোনটি? কমেন্টে জানান!

#AITips #NewGoLearn #Productivity #ChatGPTTricks #AIHacks"""

    if not client:
        return fallback_caption, "ai productivity tips", "futuristic holographic artificial intelligence assistant workspace"

    candidate_models = [config.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"]
    for m in candidate_models:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.7,
                ),
            )
            raw = (resp.text or "").strip()
            data = json.loads(raw)
            caption = data.get("caption", "").strip() or fallback_caption
            kw = data.get("keyword", "ai productivity tips")
            v_prompt = data.get("visual_prompt", "futuristic workspace with glowing AI productivity holographic display")
            return caption, kw, v_prompt
        except Exception as e:
            logger.warning(f"Model {m} failed for tips post: {e}. Trying next...")

    return fallback_caption, "ai productivity tips", "futuristic holographic workspace with artificial intelligence"


# ==============================================================================
# 4. Main Autonomous Agent Execution Cycle
# ==============================================================================
def run_autonomous_content_agent(forced_mode: Optional[str] = None) -> Dict[str, Any]:
    """
    Main entry point for the Autonomous Content Agent.
    1. Determines mode: 'news' vs 'tips' (auto-shuffled or forced).
    2. Gathers content from live feeds or curated library.
    3. Crafts engaging Bengali copy via Gemini AI.
    4. Generates matching visual AI image.
    5. Saves as a draft in draft_store.
    6. Updates agent memory and switches mode for the next cycle.
    """
    mem = get_agent_memory()
    target_mode = (forced_mode or get_next_mode()).lower().strip()
    if target_mode not in ["news", "tips"]:
        target_mode = "news"

    logger.info(f"🤖 Running Autonomous Agent in mode: '{target_mode.upper()}'")

    article_info = None
    if target_mode == "news":
        article_info = get_fresh_news_article()
        if article_info:
            caption, keyword, visual_prompt = generate_ai_news_post(article_info)
            topic_label = f"📰 AI News: {article_info['title']}"
            news_hash = article_info.get("hash")
        else:
            logger.warning("No fresh news available; falling back to AI Tips & Tricks mode.")
            target_mode = "tips"
            caption, keyword, visual_prompt = generate_ai_tips_post()
            topic_label = "💡 AI Tips & Tricks"
            news_hash = None
    else:
        caption, keyword, visual_prompt = generate_ai_tips_post()
        topic_label = "💡 AI Tips & Tricks"
        news_hash = None

    # Generate matching visual
    image_url = get_free_image_url(keyword, visual_prompt, seed=random.randint(100, 999999))

    # Save to Draft Store
    draft = add_draft(
        caption=caption,
        image_url=image_url,
        topic=topic_label,
        keyword=keyword,
        media_type="photo",
    )

    # Update Agent Memory
    mem["last_mode"] = target_mode
    mem["total_posts_created"] = mem.get("total_posts_created", 0) + 1
    if news_hash:
        seen = mem.get("seen_news_hashes", [])
        if news_hash not in seen:
            seen.append(news_hash)
            mem["seen_news_hashes"] = seen[-200:]  # Keep last 200 hashes

    mem["last_run_title"] = topic_label
    save_agent_memory(mem)

    logger.info(
        f"🤖 Agent successfully created draft #{draft['id']} (Mode: {target_mode}). Next mode will be: '{get_next_mode().upper()}'"
    )

    return {
        "success": True,
        "mode": target_mode,
        "next_mode": get_next_mode(),
        "topic": topic_label,
        "draft_id": draft["id"],
        "draft": draft,
    }
