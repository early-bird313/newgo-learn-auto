import json
import logging
from typing import Any, Dict, List, Optional, Tuple
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
import config

logger = logging.getLogger(__name__)

# Simple in-memory conversation memory for active Messenger users (sender_id -> messages list)
_conversation_history: Dict[str, List[Dict[str, str]]] = {}
MAX_HISTORY_PER_USER = 6


def get_gemini_client() -> Any:
    """Returns an initialized Gemini Client if API key is present."""
    if not genai:
        return None
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.warning("GEMINI_API_KEY is not configured.")
        return None
    try:
        return genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Error initializing Gemini client: {e}")
        return None


def read_knowledge_base() -> str:
    """Reads the knowledge base file dynamically."""
    if config.KNOWLEDGE_BASE_FILE.exists():
        try:
            with open(config.KNOWLEDGE_BASE_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Failed to read knowledge base file: {e}")
    return "ফেসবুক পেজ অফিসিয়াল সাপোর্ট।"


def generate_chat_reply(sender_id: str, user_message: str) -> str:
    """
    Generates a personalized, context-aware reply for a Facebook Messenger message.
    Uses knowledge_base.txt as the factual grounding.
    """
    client = get_gemini_client()
    if not client:
        return "আসসালামু আলাইকুম। আমাদের সাথে যোগাযোগ করার জন্য ধন্যবাদ। এই মুহূর্তে আমাদের এআই সার্ভারে সংযোগ হচ্ছে না। আমাদের এডমিন প্রতিনিধি খুব শীঘ্রই আপনার মেসেজের উত্তর দিবেন।"

    knowledge = read_knowledge_base()
    system_instruction = f"""
আপনি এই ফেসবুক পেজের একজন অত্যন্ত বিনয়ী, দক্ষ ও প্রফেশনাল এআই কাস্টমার সাপোর্ট অ্যাসিস্ট্যান্ট।
নিচে আপনার পেজ ও প্রতিষ্ঠানের নলেজবেস (Knowledge Base) দেওয়া হলো:

=== নলেজবেস শুরু ===
{knowledge}
=== নলেজবেস শেষ ===

নিয়মাবলী:
১. সবসময় সুন্দর, মার্জিত এবং আন্তরিক ভাষায় বাংলায় কথা বলবেন।
২. আপনার উত্তরের ভিত্তি হতে হবে উপরের নলেজবেস।
৩. যদি কোনো তথ্য বা প্রশ্নের উত্তর এই নলেজবেসে না থাকে, তবে কাল্পনিক কিছু বানিয়ে বলবেন না। বরং বিনয়ের সাথে বলবেন: "ধন্যবাদ আপনার বার্তার জন্য। এই বিষয়ে বিস্তারিত তথ্যের জন্য আমাদের এডমিন প্রতিনিধি খুব শীঘ্রই আপনার সাথে যোগাযোগ করবেন। অনুগ্রহ করে একটু অপেক্ষা করুন।"
৪. উত্তর সংক্ষিপ্ত, স্পষ্ট ও টু-দ্য-পয়েন্ট রাখবেন।
"""

    # Retrieve and update user conversation history
    history = _conversation_history.get(sender_id, [])
    
    # Build contents payload
    contents = []
    for turn in history:
        role = "user" if turn["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=turn["text"])]))
    
    # Add current user message
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    # List of candidate models to try in order
    candidate_models = []
    for m in ["gemini-3.5-flash", "gemini-3.5-flash-lite", config.GEMINI_MODEL, "gemini-3.8-flash"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    reply_text = None
    for model_name in candidate_models:
        try:
            logger.info(f"Trying Gemini model '{model_name}' for chat reply...")
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=600,
                ),
            )
            if response.text and response.text.strip():
                reply_text = response.text.strip()
                break
        except Exception as e:
            logger.warning(f"Model '{model_name}' failed with error: {e}. Trying next candidate...")

    if reply_text:
        # Save to history
        history.append({"role": "user", "text": user_message})
        history.append({"role": "model", "text": reply_text})
        if len(history) > MAX_HISTORY_PER_USER * 2:
            history = history[-(MAX_HISTORY_PER_USER * 2):]
        _conversation_history[sender_id] = history
        return reply_text

    logger.error("All candidate Gemini models failed for chat reply.")
    return "আসসালামু আলাইকুম। আপনার মেসেজের জন্য ধন্যবাদ। আমাদের প্রতিনিধি শীঘ্রই আপনার সাথে যোগাযোগ করবেন।"


def generate_page_post(topic_hint: str = "") -> Tuple[str, str, str]:
    """
    Generates an engaging Facebook post caption, an image search keyword,
    and a visual prompt for image generation.
    Returns: (caption, image_keyword, visual_prompt)
    """
    client = get_gemini_client()
    topic = topic_hint or config.DEFAULT_POST_TOPIC

    if not client:
        # Fallback post if Gemini key is not set
        caption = f"আসসালামু আলাইকুম! 🚀\n\nপ্রযুক্তির যুগে নিজেকে একধাপ এগিয়ে রাখতে প্রতিদিন নতুন নতুন ডিজিটাল স্কিলস ও এআই টুলস শিখুন। স্মার্ট কাজই আপনাকে সফল করে তুলবে।\n\n#AITools #Automation #Productivity #NewGoLearn"
        return caption, "abstract futuristic ai technology circuit", "A glowing abstract futuristic AI neural network circuit board, digital data stream, no humans, cinematic 8k"

    prompt = f"""
তুমি একজন দক্ষ সোশ্যাল মিডিয়া কনটেন্ট ক্রিয়েটর।
নিচের বিষয়ের ওপর ভিত্তি করে ফেসবুক পেজের জন্য শুধুমাত্র বাংলায় একটি অত্যন্ত আকর্ষণীয়, সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট (To-The-Point) পোস্ট তৈরি করো:
বিষয়: "{topic}"

কঠোর ক্যাপশন নির্দেশিকা (STRICT RULES):
১. শুধুমাত্র খাঁটি বাংলা (Sudhu Bangla): সম্পূর্ণ ক্যাপশনটি সাবলীল ও সহজবোধ্য বাংলায় হতে হবে। অপ্রয়োজনীয় ইংরেজি বাক্য ব্যবহার করা যাবে না।
২. টু-দ্য-পয়েন্ট ও সংক্ষিপ্ত (To-The-Point): অহেতুক ভূমিকা বা বাড়তি বাক্য ছাড়া সরাসরি মূল তথ্য ও টিপস তুলে ধরতে হবে।
৩. ফরম্যাট:
   - নজরকাড়া একটি বাংলা হেডলাইন (উপযুক্ত ইমোজি সহ যেমন 🚀, 💡, ⚡)।
   - মূল বিষয়টি সংক্ষেপে ১-২টি বাক্যে উপস্থাপন।
   - ২-৩টি বুলেট পয়েন্টে (👉 দিয়ে) সরাসরি মূল বিষয়গুলো।
   - শেষে প্রাসঙ্গিক ৩টি হ্যাশট্যাগ (#AITools #Automation #Productivity ইত্যাদি)।

⚠️ কঠোর ছবি নির্দেশিকা (STRICT IMAGE RULES - ABSOLUTELY NO HUMANS / NO FEMALES):
- ছবিতে কোনো মানুষ, নারী, পুরুষ, অবয়ব, মুখমণ্ডল, হাত বা প্রতিকৃতি থাকবে না (Strictly NO humans, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands)।
- ছবির প্রম্পট (visual_prompt) হতে হবে ক্যাপশনের বিষয়ের সাথে হুবহু সামঞ্জস্যপূর্ণ শুধুমাত্র বিমূর্ত প্রযুক্তি: যেমন glowing AI neural circuits, futuristic cybernetic hardware, data visualization, minimalist futuristic technology, no humans, cinematic 8k।
- keyword হবে টেকনিক্যাল ইংরেজি শব্দ (যেমন: 'abstract ai circuit board technology', 'futuristic data server')।

আউটপুটটি অবশ্যই সম্পূর্ণ ভ্যালিড JSON ফরম্যাটে হতে হবে (অন্য কোনো অতিরিক্ত টেক্সট বা মার্কডাউন ছাড়া)।
JSON স্কিমা:
{{
  "caption": "সম্পূর্ণ বাংলা টু-দ্য-পয়েন্ট পোস্টের ক্যাপশন...",
  "image_keyword": "ছবি সার্চ করার জন্য ২-৪ শব্দের ইংরেজি কিওয়ার্ড (যেমন: 'abstract ai circuit board technology')",
  "visual_prompt": "ক্যাপশনের সাথে সামঞ্জস্যপূর্ণ বিস্তারিত ইংরেজি প্রম্পট (যেমন: 'A modern glowing abstract cybernetic circuit board, neon data streams, minimalist tech hardware, no humans, cinematic lighting, 8k')"
}}
"""

    candidate_models = []
    for m in ["gemini-3.5-flash", "gemini-3.5-flash-lite", config.GEMINI_MODEL, "gemini-3.8-flash"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    for model_name in candidate_models:
        try:
            logger.info(f"Trying Gemini model '{model_name}' for page post...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            caption = data.get("caption", "").strip()
            keyword = data.get("image_keyword", "futuristic artificial intelligence workspace technology").strip()
            visual_prompt = data.get("visual_prompt", keyword).strip()
            if caption:
                return caption, keyword, visual_prompt
        except Exception as e:
            logger.warning(f"Model '{model_name}' failed for post generation: {e}")

    fallback_caption = f"আসসালামু আলাইকুম! 🚀\n\nপ্রযুক্তির যুগে নিজেকে একধাপ এগিয়ে রাখতে প্রতিদিন নতুন নতুন ডিজিটাল স্কিলস ও এআই টুলস শিখুন। স্মার্ট কাজই আপনাকে সফল করে তুলবে।\n\n#AITools #Automation #Productivity #NewGoLearn"
    return fallback_caption, "futuristic artificial intelligence workspace technology", "A modern futuristic workspace with glowing artificial intelligence holographic screens, high-tech aesthetic, 8k"
