"""ローカル検索サービス: DuckDuckGo HTML版で無料検索 → リードURL取得（SerpAPI不要）"""

import asyncio
import random
import re
from urllib.parse import urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

# 除外ドメイン（serpapi_serviceと共通）
EXCLUDE_DOMAINS = {
    "google.com", "google.co.jp", "youtube.com", "facebook.com",
    "twitter.com", "instagram.com", "linkedin.com", "wikipedia.org",
    "amazon.co.jp", "amazon.com", "rakuten.co.jp", "yahoo.co.jp",
    "tabelog.com", "hotpepper.jp", "jalan.net", "booking.com",
    "indeed.com", "mynavi.jp", "rikunabi.com",
    "duckduckgo.com",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# リクエスト間の待機時間（秒）
MIN_DELAY = 1.5
MAX_DELAY = 3.0


def _is_excluded(url: str) -> bool:
    for domain in EXCLUDE_DOMAINS:
        if domain in url:
            return True
    return False


def _extract_ddg_url(href: str) -> str | None:
    """DuckDuckGoのリダイレクトURLから実際のURLを抽出"""
    if not href:
        return None
    # //duckduckgo.com/l/?uddg=<encoded_url>&... 形式
    if "uddg=" in href:
        parsed = parse_qs(urlparse(href).query)
        urls = parsed.get("uddg", [])
        if urls:
            return unquote(urls[0])
    # 直接URL
    if href.startswith("http"):
        return href
    return None


def build_query(base_query: str, region: str | None = None, industry: str | None = None) -> str:
    """検索クエリを構築（serpapi_serviceと同じインターフェース）"""
    parts = [base_query]
    if region:
        parts.append(region)
    if industry:
        parts.append(industry)
    return " ".join(parts)


async def _fetch_ddg_html(
    query: str, page_token: str | None = None
) -> tuple[list[dict], str | None]:
    """DuckDuckGo HTML版を1ページ取得 → (結果リスト, 次ページトークン)"""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://html.duckduckgo.com/",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if page_token:
            # 次ページはPOSTで取得
            data = {
                "q": query,
                "kl": "jp-jp",
                "s": page_token,
                "nextParams": "",
                "v": "l",
                "o": "json",
                "dc": page_token,
                "api": "d.js",
            }
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data=data,
                headers=headers,
            )
        else:
            params = {"q": query, "kl": "jp-jp"}
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params=params,
                headers=headers,
            )

        if resp.status_code != 200:
            return [], None

        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    results = []
    seen_domains = set()

    for result in soup.select(".result"):
        a_tag = result.select_one(".result__a")
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        url = _extract_ddg_url(href)
        if not url or not url.startswith("http"):
            continue

        if _is_excluded(url):
            continue

        domain = urlparse(url).netloc
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        title = a_tag.get_text(strip=True)

        snippet_el = result.select_one(".result__snippet")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        results.append({
            "url": url,
            "title": title,
            "snippet": snippet,
        })

    # 次ページトークンを取得
    next_token = None
    next_form = soup.select_one("form.nav-link input[name='s']")
    if next_form:
        next_token = next_form.get("value")

    return results, next_token


# ページングキャッシュ: {query: [(results, next_token), ...]}
_page_cache: dict[str, list[tuple[list[dict], str | None]]] = {}


async def fetch_one_page(
    query: str, start: int = 0, hl: str = "ja", gl: str = "jp"
) -> tuple[list[dict], bool]:
    """DuckDuckGo HTML版で検索結果を取得（serpapi_serviceと同じインターフェース）"""
    page_num = start // 10

    # キャッシュにあればそこから返す
    cached = _page_cache.get(query, [])
    if page_num < len(cached):
        results, next_token = cached[page_num]
        return results, next_token is not None

    # 新規取得
    if page_num == 0:
        results, next_token = await _fetch_ddg_html(query)
        _page_cache[query] = [(results, next_token)]
        return results, next_token is not None
    else:
        # 前ページのトークンが必要
        if not cached:
            return [], False
        prev_results, prev_token = cached[-1]
        if not prev_token:
            return [], False

        # 足りないページを順次取得
        current_token = prev_token
        for _ in range(page_num - len(cached) + 1):
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            await asyncio.sleep(delay)
            results, next_token = await _fetch_ddg_html(query, current_token)
            _page_cache.setdefault(query, []).append((results, next_token))
            if not next_token or not results:
                return results, False
            current_token = next_token

        last_results, last_token = _page_cache[query][-1]
        return last_results, last_token is not None


async def fetch_urls(
    query: str, num_results: int = 100, hl: str = "ja", gl: str = "jp"
) -> tuple[list[dict], int]:
    """DuckDuckGo HTML版で検索を実行し、(URLリスト, ページ数) を返す"""
    all_results: list[dict] = []
    seen_urls: set[str] = set()
    pages_fetched = 0
    max_pages = min((num_results + 9) // 10, 20)
    token: str | None = None

    for page in range(max_pages):
        if page == 0:
            results, token = await _fetch_ddg_html(query)
        else:
            if not token:
                break
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            await asyncio.sleep(delay)
            results, token = await _fetch_ddg_html(query, token)

        pages_fetched += 1

        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
            if len(all_results) >= num_results:
                break

        if len(all_results) >= num_results or not results:
            break

    return all_results[:num_results], pages_fetched
