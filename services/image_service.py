import random
import urllib.parse
import logging
import requests
import config

logger = logging.getLogger(__name__)

def get_free_image_url(search_keyword: str, visual_prompt: str = "", seed: int = None) -> str:
    """
    Returns a high-quality, royalty-free image URL matching the topic.
    Supports Pollinations AI (100% free, no API key needed),
    Pexels API, and Unsplash API.
    """
    provider = config.IMAGE_PROVIDER.lower()

    # 1. Pexels API (if configured)
    if provider == "pexels" and config.PEXELS_API_KEY:
        try:
            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(search_keyword)}&orientation=landscape&per_page=1"
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
            url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(search_keyword)}&orientation=landscape&per_page=1&client_id={config.UNSPLASH_ACCESS_KEY}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("results") and len(data["results"]) > 0:
                    return data["results"][0]["urls"]["regular"]
        except Exception as e:
            logger.warning(f"Failed to fetch from Unsplash: {e}")

    # 3. Pollinations AI (Default: 100% Free, NO API key required)
    # Generates a realistic high-definition image on the fly based on the prompt
    prompt_to_use = visual_prompt if visual_prompt else f"{search_keyword}, peaceful, aesthetic, high quality, 4k"
    encoded_prompt = urllib.parse.quote(prompt_to_use)
    current_seed = seed if seed is not None else random.randint(100, 999999)
    pollinations_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=630&nologo=true&seed={current_seed}"
    
    logger.info(f"Using Pollinations AI image URL: {pollinations_url}")
    return pollinations_url
