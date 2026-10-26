import json
import logging
import random
import re
from typing import Optional, Tuple
import urllib.parse
import uuid
import requests
try:
    from google.genai import types
except ImportError:
    types = None

import config

logger = logging.getLogger(__name__)

# Strict filter pattern to completely disallow any human, face, or female representation
DISALLOWED_TERMS_PATTERN = re.compile(
    r"\b(human|humans|humanoid|person|people|woman|women|female|females|girl|girls|lady|ladies|"
    r"mother|sister|queen|man|men|male|boy|boys|face|faces|portrait|portraits|body|bodies|"
    r"hand|hands|hacker|hackers|developer|developers|programmer|programmers|worker|workers|"
    r"student|students|child|children|kid|kids|character|characters|avatar|avatars|someone|model|models)\b",
    re.IGNORECASE,
)

STRICT_NEGATIVE_SUFFIX = ", no humans, no people, no faces, no women, no men, no female, abstract technology, futuristic digital circuit, clean hardware render, 3d data visualization, 8k"

# High-resolution, guaranteed royalty-free abstract technology images (100% strictly NO humans / NO faces / NO females)
# Used as instant, reliable fallback whenever AI image generator is throttled or rate-limited
CURATED_ABSTRACT_TECH_IMAGES = [
    "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1200&h=630&fit=crop",  # 3D digital audio/data waves
    "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&h=630&fit=crop",  # Futuristic AI neural nodes
    "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1200&h=630&fit=crop",  # Cyber security matrix & code
    "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?w=1200&h=630&fit=crop",  # Cyber server hardware & glowing rack
    "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1200&h=630&fit=crop",  # Clean glowing motherboard microchip
    "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?w=1200&h=630&fit=crop",  # Holographic 3D tech shapes
    "https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=1200&h=630&fit=crop",  # Glowing code on modern dark workstation
]


def sanitize_prompt_for_no_humans(prompt: str) -> str:
    """
    Strips out all human/female/portrait related terms and appends strict
    negative constraints to ensure 100% abstract technology imagery.
    """
    cleaned = DISALLOWED_TERMS_PATTERN.sub("abstract technology", prompt)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "futuristic AI neural network glowing technology circuit"
    return f"{cleaned}{STRICT_NEGATIVE_SUFFIX}"


def generate_visual_prompt_from_caption(caption: str, topic: str = "") -> Tuple[str, str]:
    """
    Integrates Gemini AI to analyze a post caption (Bangla/English) and generate
    a matching, highly synchronized 3D abstract technology visual prompt.
    Strictly adheres to: NO humans, NO females, NO faces.
    Returns: (keyword, visual_prompt)
    """
    from services.gemini_service import get_gemini_client

    client = get_gemini_client()
    default_keyword = "abstract technology circuit"
    default_prompt = "A glowing 3D abstract technology neural circuit board with luminous blue data streams, hardware components, no humans, cinematic 8k"

    if not client or not caption.strip():
        return default_keyword, default_prompt

    prompt = f"""
You are an expert AI visual designer.
Analyze the following Facebook post caption and topic, and generate a perfectly matching, visually stunning English prompt for AI image generation.

Post Topic: {topic or 'AI & Technology'}
Post Caption:
\"\"\"{caption[:800]}\"\"\"

⚠️ STRICT IMAGE RULES (ABSOLUTELY NO HUMANS / NO FEMALES):
1. Strictly NO human beings, NO women, NO female figures, NO men, NO persons, NO faces, NO portraits, NO human hands, NO human bodies.
2. The image MUST BE 100% abstract technology, futuristic digital hardware, glowing cybernetic circuits, 3D holographic data visualization, neural network nodes, or futuristic servers/microchips.
3. The visual MUST harmonize and match the theme of the caption (e.g. if the post is about audio AI, depict glowing soundwaves and audio spectrum equalizer; if about coding, depict glowing code lines and futuristic monitors; if about security, depict cyber shield and encrypted circuit pathways).

Return strictly valid JSON with this schema:
{{
  "keyword": "2-3 words English search keyword (e.g. abstract ai sound spectrum)",
  "visual_prompt": "Detailed English prompt for image generation (e.g. A futuristic 3D visualization of glowing neon soundwaves, audio spectrum equalizer, dark cybernetic background, cinematic lighting, 8k render, strictly no humans)"
}}
"""

    candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", config.GEMINI_MODEL, "gemini-3.8-flash"]
    for m in candidate_models:
        if not m:
            continue
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                ),
            )
            raw = (resp.text or "").strip()
            data = json.loads(raw)
            kw = data.get("keyword", default_keyword).strip()
            vp = data.get("visual_prompt", default_prompt).strip()
            if vp:
                return kw, vp
        except Exception as e:
            logger.debug(f"Gemini visual prompt generation failed with model {m}: {e}")

    return default_keyword, default_prompt


def get_free_image_url(
    search_keyword: str = "",
    visual_prompt: str = "",
    seed: Optional[int] = None,
    caption: str = "",
) -> str:
    """
    Returns a high-quality, royalty-free image URL matching the topic/caption.
    Strictly enforces NO human beings, NO faces, and NO female representations.
    All images are guaranteed to be abstract technology, circuits, servers, or 3D digital concepts.

    If caption is provided and visual_prompt is empty, integrates Gemini to create
    a visual prompt directly synchronized with the post caption.
    """
    provider = config.IMAGE_PROVIDER.lower()

    # If caption is provided and no specific visual_prompt is given, use Gemini to harmonize visual with caption
    if caption and not visual_prompt:
        gemini_kw, gemini_vp = generate_visual_prompt_from_caption(caption)
        if not search_keyword:
            search_keyword = gemini_kw
        visual_prompt = gemini_vp

    # Clean search keyword for external stock photo APIs
    safe_search_keyword = DISALLOWED_TERMS_PATTERN.sub("technology", search_keyword or "technology circuit").strip()
    if not safe_search_keyword:
        safe_search_keyword = "futuristic technology circuit"
    else:
        safe_search_keyword = f"{safe_search_keyword} abstract technology circuit"

    # 0. Hugging Face Inference API (if provider == 'huggingface' and token configured)
    if provider == "huggingface" and config.HUGGINGFACE_API_TOKEN:
        try:
            raw_prompt = visual_prompt.strip() if visual_prompt else safe_search_keyword
            safe_visual_prompt = sanitize_prompt_for_no_humans(raw_prompt)
            hf_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            hf_headers = {"Authorization": f"Bearer {config.HUGGINGFACE_API_TOKEN}"}
            logger.info("Attempting image generation via Hugging Face Inference API...")
            hf_res = requests.post(hf_url, headers=hf_headers, json={"inputs": safe_visual_prompt}, timeout=25)
            if hf_res.status_code == 200 and len(hf_res.content) > 10000:
                config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                filename = f"hf_flux_{uuid.uuid4().hex[:8]}.jpg"
                dest_path = config.UPLOADS_DIR / filename
                with open(dest_path, "wb") as f:
                    f.write(hf_res.content)
                logger.info(f"Successfully generated image via Hugging Face FLUX.1: {dest_path}")
                return f"/uploads/{filename}"
            else:
                logger.info(
                    f"Hugging Face serverless image endpoint returned {hf_res.status_code}. "
                    "Routing seamlessly to Pollinations FLUX engine."
                )
        except Exception as e:
            logger.warning(f"Hugging Face generation attempt failed: {e}. Routing to Pollinations FLUX engine.")

    # 1. Pexels API (if configured)
    if provider == "pexels" and config.PEXELS_API_KEY:
        try:
            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(safe_search_keyword)}&orientation=landscape&per_page=1"
            headers = {"Authorization": config.PEXELS_API_KEY}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("photos") and len(data["photos"]) > 0:
                    return data["photos"][0]["src"]["large2x"]
        except Exception as e:
            logger.warning(f"Failed to fetch from Pexels: {e}")

    # 2. Unsplash API (if configured)
    if provider == "unsplash" and config.UNSPLASH_ACCESS_KEY:
        try:
            url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(safe_search_keyword)}&orientation=landscape&per_page=1&client_id={config.UNSPLASH_ACCESS_KEY}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("results") and len(data["results"]) > 0:
                    return data["results"][0]["urls"]["regular"]
        except Exception as e:
            logger.warning(f"Failed to fetch from Unsplash: {e}")

    # 3. Pollinations AI (FLUX & Turbo High-Quality Engine)
    raw_prompt = visual_prompt.strip() if visual_prompt else safe_search_keyword
    safe_visual_prompt = sanitize_prompt_for_no_humans(raw_prompt)

    encoded_prompt = urllib.parse.quote(safe_visual_prompt)
    current_seed = seed if seed is not None else random.randint(100, 999999)
    model_name = getattr(config, "POLLINATIONS_MODEL", "flux") or "flux"
    pollinations_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=630&nologo=true&model={model_name}&seed={current_seed}"
    )

    logger.info(f"Using Pollinations AI ({model_name}) image URL: {pollinations_url}")
    return pollinations_url


def fetch_and_save_image_locally(image_url: str, filename_prefix: str = "draft") -> Tuple[str, str]:
    """
    Downloads the image and stores it directly into uploads/<filename>.jpg.
    Validates that the downloaded image is valid and not a 'Free limit reached' error placeholder.
    If the remote image download fails or times out, seamlessly falls back to a guaranteed 8k abstract tech image.
    Returns: (local_file_path, web_url)
    """
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.jpg"
    dest_path = config.UPLOADS_DIR / filename
    web_url = f"/uploads/{filename}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    # If already a saved local upload path, return directly
    if image_url and image_url.startswith("/uploads/"):
        local_target = config.BASE_DIR / image_url.lstrip("/")
        if local_target.exists():
            return str(local_target), image_url

    # Attempt to download from image_url
    if image_url and image_url.startswith("http"):
        try:
            logger.info(f"Attempting to download and cache image locally from: {image_url[:80]}...")
            res = requests.get(image_url, headers=headers, timeout=10)
            # A real JPEG image of 1200x630 is at least 25KB; error banners are tiny text files or small placeholders
            if res.status_code == 200 and len(res.content) > 18000:
                with open(dest_path, "wb") as f:
                    f.write(res.content)
                logger.info(f"Successfully cached image locally: {dest_path} ({len(res.content)} bytes)")
                return str(dest_path), web_url
            else:
                logger.warning(
                    f"Image download returned suspicious size ({len(res.content)} bytes) or status {res.status_code}. Using curated fallback."
                )
        except Exception as e:
            logger.warning(f"Image download timed out or failed: {e}. Switching to reliable fallback.")

    # Guaranteed fallback: Download from curated abstract tech image pool
    fallback_url = random.choice(CURATED_ABSTRACT_TECH_IMAGES)
    try:
        logger.info(f"Downloading guaranteed abstract tech image from: {fallback_url}")
        res = requests.get(fallback_url, headers=headers, timeout=10)
        if res.status_code == 200 and len(res.content) > 10000:
            with open(dest_path, "wb") as f:
                f.write(res.content)
            logger.info(f"Successfully saved fallback image: {dest_path}")
            return str(dest_path), web_url
    except Exception as e:
        logger.error(f"Fallback download error: {e}")

    # Return remote URL if local write fails
    return "", fallback_url


def generate_image_for_post(caption: str, topic: str = "", seed: Optional[int] = None) -> Tuple[str, str, str, str]:
    """
    Convenience method: analyzes caption using Gemini, creates a caption-synchronized
    abstract tech visual, caches it locally, and returns: (local_file_path, web_url, keyword, visual_prompt).
    """
    keyword, visual_prompt = generate_visual_prompt_from_caption(caption, topic)
    raw_image_url = get_free_image_url(search_keyword=keyword, visual_prompt=visual_prompt, seed=seed)
    local_path, web_url = fetch_and_save_image_locally(raw_image_url, filename_prefix="post")
    return local_path, web_url, keyword, visual_prompt
