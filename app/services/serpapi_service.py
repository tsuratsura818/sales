import asyncio
import httpx
from app.config import get_settings

settings = get_settings()

# 除外するドメイン（大手ポータル・SNS等）
EXCLUDE_DOMAINS = {
    "google.com", "google.co.jp", "youtube.com", "facebook.com",
    "twitter.com", "instagram.com", "linkedin.com", "wikipedia.org",
    "amazon.co.jp", "amazon.com", "rakuten.co.jp", "yahoo.co.jp",
    "tabelog.com", "hotpepper.jp", "jalan.net", "booking.com",
    "indeed.com", "mynavi.jp", "rikunabi.com",
}


def _is_excluded(url: str) -> bool:
    for domain in EXCLUDE_DOMAINS:
        if domain in url:
            return True
    return False


def build_query(base_query: str, region: str | None = None, industry: str | None = None) -> str:
    """検索クエリを最適化（地域・業界付加 + 除外ドメイン演算子）"""
    parts = [base_query]
    if region:
        parts.append(region)
    if industry:
        parts.append(industry)
    # 主要ポータルをGoogle検索レベルで除外（API節約）
    top_excludes = ["tabelog.com", "hotpepper.jp", "jalan.net", "booking.com",
                    "amazon.co.jp", "rakuten.co.jp", "yahoo.co.jp",
                    "indeed.com", "mynavi.jp", "rikunabi.com"]
    for domain in top_excludes:
        parts.append(f"-site:{domain}")
    return " ".join(parts)


async def fetch_one_page(
    query: str, start: int = 0, hl: str = "ja", gl: str = "jp"
) -> tuple[list[dict], bool]:
    """SerpAPI で1ページ(10件)取得 → (結果リスト, 次ページあり)"""
    async with httpx.AsyncClient(timeout=30) as client:
        params = {
            "engine": "google",
            "q": query,
            "api_key": settings.SERPAPI_KEY,
            "num": 10,
            "start": start,
            "hl": hl,
            "gl": gl,
        }
        try:
            resp = await client.get("https://serpapi.com/search.json", params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                await asyncio.sleep(5)
                return [], True  # レートリミット→リトライ可能
            raise

    organic = data.get("organic_results", [])
    results = []
    for item in organic:
        url = item.get("link", "")
        if url and not _is_excluded(url):
            results.append({
                "url": url,
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            })

    # organicが0件なら完全に枯渇、1件以上あれば次ページも試す
    has_next = len(organic) > 0
    return results, has_next


async def fetch_urls(query: str, num_results: int = 100, hl: str = "ja", gl: str = "jp") -> tuple[list[dict], int]:
    """SerpAPIでGoogle検索を実行し、(URLリスト, 使用API呼び出し回数) を返す"""
    results = []
    pages_needed = (num_results + 9) // 10
    calls_used = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(pages_needed):
            start = page * 10
            params = {
                "engine": "google",
                "q": query,
                "api_key": settings.SERPAPI_KEY,
                "num": 10,
                "start": start,
                "hl": hl,
                "gl": gl,
            }
            try:
                resp = await client.get("https://serpapi.com/search.json", params=params)
                resp.raise_for_status()
                calls_used += 1
                data = resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await asyncio.sleep(5)
                    continue
                raise

            organic = data.get("organic_results", [])
            for item in organic:
                url = item.get("link", "")
                if url and not _is_excluded(url):
                    results.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })
                if len(results) >= num_results:
                    break

            if len(results) >= num_results or len(organic) < 10:
                break

            await asyncio.sleep(0.5)

    return results[:num_results], calls_used
