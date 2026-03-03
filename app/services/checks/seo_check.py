import httpx
from urllib.parse import urlparse


async def check_seo(url: str, client: httpx.AsyncClient) -> dict:
    """sitemap.xml と robots.txt の有無を確認する"""
    result = {
        "has_sitemap": None,
        "has_robots_txt": None,
    }

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        resp = await client.get(f"{base}/robots.txt", follow_redirects=True, timeout=8)
        result["has_robots_txt"] = (
            resp.status_code == 200
            and "user-agent" in resp.text.lower()
        )
    except Exception:
        result["has_robots_txt"] = False

    try:
        resp = await client.get(f"{base}/sitemap.xml", follow_redirects=True, timeout=8)
        result["has_sitemap"] = (
            resp.status_code == 200
            and ("</urlset>" in resp.text or "</sitemapindex>" in resp.text)
        )
    except Exception:
        result["has_sitemap"] = False

    return result
