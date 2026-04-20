"""DuckDuckGoコレクター（無料・APIキー不要）

DuckDuckGo検索で特商法ページを探し、httpxでスクレイピングしてリード抽出。
list_generator v3.1 から移植したロジックをベースに、SellBuddyの
CollectedLead / extractors 仕様に合わせて統合。
"""
import asyncio
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import RATE_LIMIT_SEC, random_ua
from .extractors import (
    extract_emails, extract_company, extract_address,
    is_kansai, is_excluded, detect_ec_platform,
)

log = logging.getLogger("pipeline.ddg")

# DuckDuckGo 用 特商法ページ検索クエリ（関西特化）
# site: 演算子が使えるのはGoogleと同様
SEARCH_QUERIES = [
    # カラーミー
    '特定商取引法 大阪 site:shop-pro.jp',
    '特定商取引法 京都 site:shop-pro.jp',
    '特定商取引法 兵庫 site:shop-pro.jp',
    '特定商取引法 奈良 site:shop-pro.jp',
    # BASE
    '特定商取引法 大阪 site:thebase.in',
    '特定商取引法 京都 site:thebase.in',
    '特定商取引法 兵庫 site:thebase.in',
    '特定商取引法 大阪 site:base.shop',
    '特定商取引法 京都 site:base.shop',
    # STORES
    '特定商取引法 大阪 site:stores.jp',
    '特定商取引法 京都 site:stores.jp',
    '特定商取引法 兵庫 site:stores.jp',
    # Makeshop
    '特定商取引法 大阪 site:makeshop.jp',
    # 独立系EC（site指定なし）
    '"特定商取引法に基づく表記" 大阪府 info@',
    '"特定商取引法に基づく表記" 京都府 info@',
    '"特定商取引法に基づく表記" 兵庫県 info@',
    '"特定商取引法に基づく表記" 奈良県 info@',
    '"特定商取引法に基づく表記" 大阪 通販 お菓子',
    '"特定商取引法に基づく表記" 京都 通販 和菓子',
    '"特定商取引法" 大阪 化粧品 通販',
    '"特定商取引法" 京都 雑貨 通販',
    '"特定商取引法" 兵庫 アパレル 通販',
]

# 除外ドメイン（ポータル・まとめ等）
EXCLUDED_DOMAINS = {
    "hotpepper.jp", "tabelog.com", "retty.me", "gnavi.co.jp",
    "rakuten.co.jp", "amazon.co.jp", "yahoo.co.jp",
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "wikipedia.org", "note.com", "ameblo.jp", "hatenablog.com",
    "prtimes.jp", "biglobe.ne.jp",
}


@dataclass
class CollectedLead:
    email: str = ""
    company: str = ""
    industry: str = ""
    location: str = ""
    website: str = ""
    platform: str = ""
    ec_status: str = ""
    source: str = ""
    shop_code: str = ""


def _search_ddg_sync(query: str, max_results: int = 15) -> list[str]:
    """DuckDuckGo検索（同期）- asyncio.to_thread 経由で呼ぶ"""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, region="jp-jp", max_results=max_results))
        return [r.get("href", "") for r in raw if r.get("href")]
    except Exception as e:
        log.debug(f"DDG search error [{query[:30]}]: {e}")
        return []


async def _search_ddg(query: str, max_results: int = 15) -> list[str]:
    """DuckDuckGo検索を非同期で実行"""
    last_exc = None
    for attempt in range(3):
        try:
            return await asyncio.to_thread(_search_ddg_sync, query, max_results)
        except Exception as e:
            last_exc = e
            err = str(e).lower()
            wait = 2 ** attempt * (3 if "ratelimit" in err or "429" in err else 1)
            log.warning(f"DDG リトライ {attempt+1}/3 ({wait}秒): {e}")
            await asyncio.sleep(wait)
    log.error(f"DDG 全リトライ失敗 [{query[:30]}]: {last_exc}")
    return []


def _is_excluded_url(url: str) -> bool:
    """除外ドメイン判定"""
    url_lower = url.lower()
    for d in EXCLUDED_DOMAINS:
        if d in url_lower:
            return True
    # 記事・まとめ系URLパターン
    for p in ["/article/", "/articles/", "/ranking/", "/matome/", "/column/", "/magazine/"]:
        if p in url_lower:
            return True
    return False


def _detect_platform_from_url(url: str) -> tuple[str, str]:
    """URL から (platform, ec_status) を推定"""
    u = url.lower()
    if "shop-pro.jp" in u:
        return "カラーミー", "カラーミー利用中"
    if "thebase.in" in u or "base.shop" in u:
        return "BASE", "BASE利用中"
    if "stores.jp" in u:
        return "STORES", "STORES利用中"
    if "makeshop.jp" in u:
        return "MakeShop", "MakeShop利用中"
    return "独立系EC", "自社ECあり"


async def collect(
    seen_emails: set[str],
    on_progress=None,
    keywords: list[tuple[str, str]] | None = None,
) -> list[CollectedLead]:
    """DuckDuckGo検索でリード収集（関西特化）"""
    log.info("DuckDuckGo 収集開始")
    leads: list[CollectedLead] = []
    checked_urls: set[str] = set()

    # キーワードが指定されていれば、それも検索クエリに追加
    queries = list(SEARCH_QUERIES)
    if keywords:
        for kw, industry in keywords[:20]:  # 最大20キーワード
            queries.append(f'"特定商取引法" {kw}')

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        total = len(queries)
        for i, query in enumerate(queries, 1):
            if on_progress:
                on_progress(f"DuckDuckGo 検索中 ({i}/{total})")
            log.info(f"DDG [{i}/{total}] {query[:60]}")

            urls = await _search_ddg(query, max_results=15)
            if not urls:
                await asyncio.sleep(RATE_LIMIT_SEC)
                continue

            for url in urls:
                if url in checked_urls or _is_excluded_url(url):
                    continue
                checked_urls.add(url)

                try:
                    resp = await client.get(url, headers=random_ua(), timeout=12)
                    if resp.status_code != 200:
                        continue
                    html = resp.text
                except (httpx.TimeoutException, httpx.ConnectError):
                    continue
                except Exception as e:
                    log.debug(f"DDG fetch エラー {url[:40]}: {e}")
                    continue

                text = BeautifulSoup(html, "html.parser").get_text()

                # 関西フィルタ
                if not is_kansai(text):
                    continue

                # メール抽出
                emails = extract_emails(text)
                if not emails:
                    continue
                if emails[0].lower() in seen_emails:
                    continue

                # 会社名
                company = extract_company(text)
                if is_excluded(company):
                    continue

                # 住所
                address = extract_address(text)

                # プラットフォーム（URLとHTMLの両方から判定）
                platform, ec_status = _detect_platform_from_url(url)
                detected = detect_ec_platform(html)
                if detected == "Shopify構築済み":
                    # Shopify構築済みは営業対象外（runner側でもフィルタされる）
                    ec_status = "Shopify構築済み"
                    platform = "Shopify"

                leads.append(CollectedLead(
                    email=emails[0],
                    company=company,
                    industry="",
                    location=address,
                    website=url,
                    platform=platform,
                    ec_status=ec_status,
                    source="duckduckgo",
                ))
                seen_emails.add(emails[0].lower())

                await asyncio.sleep(0.3)

            await asyncio.sleep(RATE_LIMIT_SEC)

    log.info(f"DuckDuckGo 結果: {len(leads)}件")
    return leads
