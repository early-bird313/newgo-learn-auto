import logging
import random
import re
import urllib.parse
import requests

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


def get_free_image_url(search_keyword: str, visual_prompt: str = "", seed: int = None) -> str:
    """
    Returns a high-quality, royalty-free image URL matching the topic.
    Strictly enforces NO human beings, NO faces, and NO female representations.
    All images are guaranteed to be abstract technology, circuits, servers, or 3D digital concepts.
    """
    provider = config.IMAGE_PROVIDER.lower()

    # Clean search keyword for external stock photo APIs
    safe_search_keyword = DISALLOWED_TERMS_PATTERN.sub("technology", search_keyword).strip()
    if not safe_search_keyword:
        safe_search_keyword = "futuristic technology circuit"
    else:
        safe_search_keyword = f"{safe_search_keyword} abstract technology circuit"

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

    # 3. Pollinations AI (Default: 100% Free, NO API key required)
    # Enforces strict no-humans & no-females prompt structure
    raw_prompt = visual_prompt.strip() if visual_prompt else safe_search_keyword
    safe_visual_prompt = sanitize_prompt_for_no_humans(raw_prompt)

    encoded_prompt = urllib.parse.quote(safe_visual_prompt)
    current_seed = seed if seed is not None else random.randint(100, 999999)
    pollinations_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=630&nologo=true&seed={current_seed}"
    )

    logger.info(f"Using Pollinations AI image URL (strictly no humans/females): {pollinations_url}")
    return pollinations_url
