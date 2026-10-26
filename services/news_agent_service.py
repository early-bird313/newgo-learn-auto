import hashlib
import html
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
from services.image_service import get_free_image_url, fetch_and_save_image_locally
try:
    from google.genai import types
except ImportError:
    types = None

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

# Curated library of real-world AI teaching, exploring & project building topics (Strictly Abstract / Tech only)
CURATED_TIPS_TOPICS = [
    # 🎓 AI Teaching & Tutorials
    "AI Teaching: Prompt Engineering Mastery — How to use System Instructions, Role Prompting, and Few-shot examples for perfect outputs",
    "AI Teaching: How beginners can use Claude and ChatGPT to learn programming, debug code, and build working tools faster",
    "AI Teaching: How to use AI to analyze complex data tables, spreadsheets, and messy CSV files in seconds",
    "AI Teaching: 5 common prompt mistakes people make every day and how to fix them for 10x better responses",

    # 🔍 AI Exploring & Deep Dives
    "AI Exploring: Deep dive into open-source local LLMs (DeepSeek, Llama 3, Ollama) and how to run AI privately offline for free",
    "AI Exploring: Autonomous AI Agents vs Chatbots — Understanding how AI executes multi-step workflows and web tasks",
    "AI Exploring: Top free open-source AI tools for developers and creators in 2026",
    "AI Exploring: Secrets of multi-modal AI — Combining text, audio, and vision for powerful automated solutions",

    # 🛠️ AI Making & Project Building
    "AI Making: Step-by-step guide to building a custom automated AI agent that monitors news and writes summaries",
    "AI Making: How to build personal AI assistants connected to your own PDFs, notes, and documents using RAG workflows",
    "AI Making: Building powerful automated workflows using n8n, webhooks, and AI APIs without writing complex backend code",
    "AI Making: How to create an automated social media posting bot with Python and Free Gemini API",
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
    clean = html.unescape(clean)
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
আপনি এআই শিক্ষাদান, এক্সপ্লোরেশন ও মেকিং (AI Teaching, Exploring & Building) ভিত্তিক একটি ফেসবুক পেজের ক্রিয়েটর ও এআই শিক্ষক।
আপনার কাজ হলো আন্তর্জাতিক শীর্ষ এআই সংবাদ নিয়ে আপনার পেজের ফলোয়ারদের জন্য শুধুমাত্র বাংলায় একটি অত্যন্ত আকর্ষণীয়, সংক্ষিপ্ত, শিক্ষণীয় ও টু-দ্য-পয়েন্ট (To-The-Point) পোস্ট তৈরি করা।

কঠোর নিয়মাবলী:
১. শুধুমাত্র খাঁটি ও প্রমিত বাংলা (Sudhu Bangla): সম্পূর্ণ পোস্টটি সাবলীল বাংলায় হতে হবে। অপ্রয়োজনীয় ইংরেজি বাক্য বা জটিল মিশ্রণ পরিহার করুন।
২. টু-দ্য-পয়েন্ট ও সংক্ষিপ্ত (To-The-Point): পোস্টটির মোট দৈর্ঘ্য ৮০ থেকে ১০০ শব্দের মধ্যে সীমাবদ্ধ হতে হবে। অহেতুক লম্বা বা অপ্রয়োজনীয় ভূমিকা সম্পূর্ণ নিষিদ্ধ।
৩. ক্লিকবেইট ও নাটকীয়তা সম্পূর্ণ নিষিদ্ধ: কোনো অহেতুক ভীতিপ্রদর্শনকারী বা নাটকীয় প্রশ্ন করা সম্পূর্ণ নিষিদ্ধ। খবরটি হবে সম্পূর্ণ তথ্যবহুল, বাস্তবসম্মত ও শিক্ষণীয়।
৪. ফরম্যাট:
   - নজরকাড়া সংক্ষিপ্ত বাংলা হেডলাইন (১টি উপযুক্ত ইমোজি সহ যেমন ⚡, 🌐, 🚀)।
   - মূল খবরটি সংক্ষেপে ১-২টি বাক্যে সরাসরি তুলে ধরুন।
   - ৩টি সংক্ষিপ্ত বুলেট পয়েন্টে (👉 দিয়ে) মূল তথ্য/হাইলাইটস।
   - ১টি সংক্ষিপ্ত ইতিবাচক শিক্ষণীয় বা প্রয়োগযোগ্য কথা।
   - শেষে প্রাসঙ্গিক ৩-৪টি হ্যাশট্যাগ (#AITeaching #AIExploring #AIBuilder #ArtificialIntelligence #TechUpdates)।

⚠️ কঠোর ছবি নির্দেশিকা (STRICT IMAGE RULES - ABSOLUTELY NO HUMANS / NO FEMALES):
- ছবিতে কোনো মানুষ, নারী, পুরুষ, মুখমণ্ডল, হাত বা মানব অবয়ব থাকা সম্পূর্ণ নিষেধ (Strictly NO humans, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands)।
- ছবির প্রম্পট (visual_prompt) হতে হবে ক্যাপশনের বিষয়ের সাথে হুবহু সামঞ্জস্যপূর্ণ শুধুমাত্র বিমূর্ত প্রযুক্তি ও আধুনিক ইলেকট্রনিক্স: যেমন glowing AI neural network, futuristic circuit board, cybernetic microchip, server rack hardware, abstract 3D data visualization, glowing futuristic tech concepts (no humans, 8k render)।
- keyword হবে কেবল টেকনিক্যাল ইংরেজি শব্দ (যেমন: "abstract ai neural circuit", "futuristic server hardware")।

আউটপুটটি অবশ্যই কঠোরভাবে এই JSON ফরম্যাটে দিতে হবে:
{
  "caption": "সম্পূর্ণ বাংলা টু-দ্য-পয়েন্ট পোস্টটি এখানে থাকবে...",
  "keyword": "ছবির জন্য ২-৩ শব্দের ইংরেজি কি-ওয়ার্ড (যেমন: abstract ai neural circuit)",
  "visual_prompt": "ক্যাপশনের সাথে সামঞ্জস্যপূর্ণ ইংরেজি ভিজ্যুয়াল প্রম্পট (A futuristic glowing AI neural circuit board with luminous blue data streams, abstract cybernetic technology, strictly no humans, cinematic 8k)"
}
"""

    prompt = f"""
খবরের শিরোনাম: {title}
খবরের উৎস: {source}
খবরের সংক্ষিপ্ত বিবরণ: {summary}

অনুগ্রহ করে উপরের এআই খবরটি নিয়ে আমাদের পেজের জন্য শুধুমাত্র বাংলায় একটি তথ্যবহুল, শিক্ষণীয়, সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট বাংলা ফেসবুক পোস্ট তৈরি করুন।
"""

    fallback_caption = f"""⚡ এআই প্রযুক্তি সংবাদ: {title}

আন্তর্জাতিক প্রযুক্তি বিশ্বে সম্প্রতি এআই নিয়ে গুরুত্বপূর্ণ অগ্রগতি ঘটেছে। {summary[:120]}...

👉 প্রযুক্তির কার্যকারিতা ও নিরাপদ ব্যবহারের নতুন পদক্ষেপ।
👉 ব্যবহারকারীদের কাজের গতি বৃদ্ধি ও ডিজিটাল রূপান্তর।
👉 বিশ্বমানের নিরাপত্তা ও জবাবদিহিতা নিশ্চিতকরণ।

💡 নতুন প্রযুক্তির নিয়মিত আপডেট জানা ও গঠনমূলকভাবে তা প্রয়োগ করাই বর্তমান সময়ের সেরা দক্ষতা।

#AITeaching #AIExploring #AIBuilder #Technology #ArtificialIntelligence"""

    if not client:
        return fallback_caption, "abstract ai neural circuit", "futuristic glowing AI neural network technology circuit board hardware, no humans, cinematic 8k"

    candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", config.GEMINI_MODEL, "gemini-3.8-flash"]
    for m in candidate_models:
        if not m:
            continue
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
            kw = data.get("keyword", "abstract ai neural circuit")
            v_prompt = data.get("visual_prompt", "futuristic AI neural network technology circuit board, no humans, 8k")
            return caption, kw, v_prompt
        except Exception as e:
            logger.warning(f"Model {m} failed for news post: {e}. Trying next...")

    return fallback_caption, "abstract ai neural circuit", "futuristic artificial intelligence glowing technology concept, no humans, 8k"


def generate_ai_tips_post() -> Tuple[str, str, str]:
    """
    Generates an actionable, practical AI Tips & Tricks post in Bengali.
    Returns: (caption, image_keyword, visual_prompt)
    """
    client = get_gemini_client()
    selected_topic = random.choice(CURATED_TIPS_TOPICS)

    system_instruction = """
আপনি এআই শিক্ষাদান, এক্সপ্লোরেশন ও মেকিং (AI Teaching, Exploring & Building) পেজের একজন অভিজ্ঞ এআই শিক্ষক ও ক্রিয়েটর।
আপনার কাজ হলো শিক্ষার্থী ও ডেভেলপারদের জন্য বাস্তবসম্মত এআই টিপস, টিউটোরিয়াল ও মেকিং গাইড নিয়ে শুধুমাত্র বাংলায় একটি অত্যন্ত ব্যবহারিক, স্পষ্ট ও টু-দ্য-পয়েন্ট (To-The-Point) ফেসবুক পোস্ট তৈরি করা।

কঠোর নিয়মাবলী:
১. শুধুমাত্র খাঁটি বাংলা (Sudhu Bangla): সম্পূর্ণ পোস্টটি সহজবোধ্য ও সাবলীল বাংলায় হতে হবে। কোনো অপ্রয়োজনীয় জটিল ভাষা ব্যবহার করা যাবে না।
২. টু-দ্য-পয়েন্ট ও সংক্ষিপ্ত (To-The-Point): পোস্টটির মোট দৈর্ঘ্য ৮০ থেকে ১০০ শব্দের মধ্যে সীমাবদ্ধ হতে হবে। কোনো অহেতুক ভূমিকা ছাড়া সরাসরি কার্যকর টিপস ও নির্দেশনা দিন।
৩. ফরম্যাট:
   - আকর্ষণীয় বাংলা হেডলাইন (💡 বা ⚡ ইমোজি সহ)।
   - সমস্যার সমাধান এআই দিয়ে কীভাবে সহজে করা যায় বা নিজে কীভাবে তৈরি করা যায় (১টি ছোট বাক্যে)।
   - ৩টি ধাপে বা পয়েন্টে সরাসরি প্র্যাকটিক্যাল গাইড (👉 দিয়ে)।
   - ১টি কার্যকর বাস্তব প্রম্পট বা বাস্তব উদাহরণ (যদি প্রযোজ্য হয়)।
   - শেষে প্রাসঙ্গিক ৩-৪টি হ্যাশট্যাগ (#AITeaching #AIBuilder #AIExploring #ArtificialIntelligence #LearnAI)।

⚠️ কঠোর ছবি নির্দেশিকা (STRICT IMAGE RULES - ABSOLUTELY NO HUMANS / NO FEMALES):
- ছবিতে কোনো মানুষ, নারী, পুরুষ, অবয়ব, মুখমণ্ডল, হাত বা প্রতিকৃতি থাকা সম্পূর্ণ নিষেধ (Strictly NO humans, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands)।
- ছবির প্রম্পট (visual_prompt) হতে হবে ক্যাপশনের বিষয়ের সাথে হুবহু সামঞ্জস্যপূর্ণ শুধুমাত্র বিমূর্ত প্রযুক্তি: যেমন glowing holographic code lines, abstract 3D geometric AI nodes, cybernetic data stream, futuristic minimalist workstation with empty chair and glowing code monitors (strictly no people)।
- keyword হবে কেবল টেকনিক্যাল শব্দ (যেমন: "abstract ai productivity interface", "futuristic neural code visualization")।

আউটপুটটি অবশ্যই কঠোরভাবে এই JSON ফরম্যাটে দিতে হবে:
{
  "caption": "সম্পূর্ণ বাংলা টু-দ্য-পয়েন্ট পোস্টটি এখানে থাকবে...",
  "keyword": "ছবির জন্য ২-৩ শব্দের ইংরেজি কি-ওয়ার্ড (যেমন: abstract ai code interface)",
  "visual_prompt": "ক্যাপশনের সাথে সামঞ্জস্যপূর্ণ ইংরেজি প্রম্পট (An abstract 3D visualization of glowing AI algorithms and glowing holographic neural networks on a futuristic dark background, no humans, cinematic 8k)"
}
"""

    prompt = f"টপিক: {selected_topic}\nঅনুগ্রহ করে এই বিষয়ের ওপর শুধুমাত্র বাংলায় একটি অত্যন্ত ব্যবহারিক, শিক্ষণীয় ও টু-দ্য-পয়েন্ট বাংলা টিপস/টিউটোরিয়াল পোস্ট তৈরি করুন।"

    fallback_caption = f"""💡 এআই শেখা ও তৈরির কৌশল: {selected_topic}

কাজের গতি বাড়াতে এবং এআই দিয়ে নতুন প্রজেক্ট বানাতে এই নিয়মগুলো মেনে চলুন:

👉 স্পষ্ট ও নির্দিষ্ট নির্দেশনা দিন: এআইকে সাধারণ নির্দেশ না দিয়ে নির্দিষ্ট ভূমিকা ও প্রেক্ষাপট বুঝিয়ে দিন।
👉 নমুনা ফলাফল যুক্ত করুন: আপনি ঠিক যেমন আউটপুট চান, তার একটি ছোট উদাহরণ প্রম্পটে দিন।
👉 ধাপে ধাপে তৈরি করুন: একবারে সম্পূর্ণ কাজ না চেয়ে ছোট ছোট ধাপে ফলাফল নিখুঁত করুন।

💡 সঠিক প্রম্পটিং ও এআই টুলস আয়ত্ত করতে পারলে যেকোনো কাজের গতি বহুগুণ বাড়ানো সম্ভব।

#AITeaching #AIBuilder #AIExploring #Productivity #LearnAI"""

    if not client:
        return fallback_caption, "ai productivity tips", "futuristic holographic artificial intelligence assistant workspace, no humans, 8k"

    candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", config.GEMINI_MODEL, "gemini-3.8-flash"]
    for m in candidate_models:
        if not m:
            continue
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
            kw = data.get("keyword", "abstract ai code interface")
            v_prompt = data.get("visual_prompt", "futuristic workspace with glowing AI productivity holographic display, no humans, 8k")
            return caption, kw, v_prompt
        except Exception as e:
            logger.warning(f"Model {m} failed for tips post: {e}. Trying next...")

    return fallback_caption, "abstract ai code interface", "futuristic holographic workspace with artificial intelligence, no humans, 8k"


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

    # Generate matching visual synchronized with caption via image_service
    image_url = get_free_image_url(
        search_keyword=keyword,
        visual_prompt=visual_prompt,
        seed=random.randint(100, 999999),
        caption=caption,
    )

    # Cache image locally to prevent browser rate limits and Pollinations yellow banners
    local_path, web_url = fetch_and_save_image_locally(image_url, filename_prefix="agent")

    # Save to Draft Store
    draft = add_draft(
        caption=caption,
        image_url=web_url or image_url,
        local_file_path=local_path,
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
