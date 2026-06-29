import asyncio
import httpx
from app.config import get_settings

settings = get_settings()

# 除外するドメイン（大手ポータル・SNS・求人・企業DB・地域メディア等）
# ＝事業者本体サイトではなく、メールが取れず営業対象にならない先
EXCLUDE_DOMAINS = {
    # SNS / 大手プラットフォーム
    "google.com", "google.co.jp", "youtube.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com", "linkedin.com", "wikipedia.org",
    "amazon.co.jp", "amazon.com", "rakuten.co.jp", "yahoo.co.jp",
    "pinterest.com", "note.com", "ameblo.jp", "ameba.jp", "fc2.com",
    "livedoor.com", "hatenablog.com", "hatena.ne.jp", "goo.ne.jp",
    "wordpress.com", "blogspot.com", "tumblr.com", "threads.net", "tiktok.com",
    # グルメ・予約・口コミ
    "tabelog.com", "hotpepper.jp", "jalan.net", "booking.com", "gnavi.co.jp",
    "retty.me", "ikyu.com", "epark.jp", "ozmall.co.jp", "beauty.hotpepper.jp",
    # 求人
    "indeed.com", "mynavi.jp", "rikunabi.com", "en-gage.net", "en-japan.com",
    "townwork.net", "baitoru.com", "doda.jp", "type.jp", "wantedly.com",
    "shigoto100.com", "job-medley.com", "guppy.jp",
    # 電話帳・地図・企業DB・比較
    "itp.ne.jp", "ekiten.jp", "mapion.co.jp", "navitime.co.jp", "its-mo.com",
    "mapfan.com", "baseconnect.in", "buffett-code.com", "alarmbox.jp",
    "kakaku.com", "prtimes.jp", "value-press.com", "atpress.ne.jp",
    "ourly.jp", "salesnow.jp", "musubu.in",
    # 業種別ポータル・予約・求人（事業者本体ではなく運営会社のサイト）
    "beauty-park.jp", "mitsuraku.jp", "relax-job.com", "salon-de-job.com",
    "esthe-de-job", "beauty-navi.com", "rejob.me", "minimodel.jp",
    "monodukuri-kyoto.jp",
    # 公的・教育（TLDセグメントで限定。.co.jp 等の事業者は除外しない）
    ".go.jp", ".lg.jp", ".ac.jp", ".ed.jp",
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
    seen = set()
    per_page = 20  # 1呼び出しあたりの取得数（API節約）
    # 取りこぼし対策で余裕を持って多めにページを回す（除外で減るため）
    max_pages = max(3, (num_results // per_page) * 2 + 3)
    calls_used = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(max_pages):
            start = page * per_page
            params = {
                "engine": "google",
                "q": query,
                "api_key": settings.SERPAPI_KEY,
                "num": per_page,
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
                if url and url not in seen and not _is_excluded(url):
                    seen.add(url)
                    results.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })

            # 終了条件: 目標到達 or organicが本当に尽きた(空)時のみ。
            # （Googleは強調スニペット等で1ページ<件数 を返すため、件数<per_page では止めない）
            if len(results) >= num_results or len(organic) == 0:
                break

            await asyncio.sleep(0.4)

    return results[:num_results], calls_used
