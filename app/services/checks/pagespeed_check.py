import httpx
from app.config import get_settings

settings = get_settings()


async def check_pagespeed(url: str) -> dict:
    """Google PageSpeed Insights APIでパフォーマンススコアを取得する（任意）"""
    result = {"pagespeed_score": None}

    if not settings.PAGESPEED_API_KEY:
        return result

    try:
        api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        params = {
            "url": url,
            "key": settings.PAGESPEED_API_KEY,
            "strategy": "mobile",
            "category": "performance",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(api_url, params=params)
            data = resp.json()
            score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
            if score is not None:
                result["pagespeed_score"] = int(score * 100)
    except Exception:
        pass

    return result
