"""Google検索コレクター（httpx + SerpAPI版 — Playwright不要）

SerpAPIを使ってGoogle検索結果を取得し、特商法ページからリードを抽出。
SerpAPIキーがない場合はスキップ。
"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from .config import RATE_LIMIT_SEC, random_ua
from .extractors import extract_emails, extract_company, extract_address, is_kansai, is_excluded

log = logging.getLogger("pipeline.google")
settings = get_settings()

# 特商法ページ検索クエリ（SerpAPI用）
SEARCH_QUERIES = [
    # カラーミー
    '"特定商取引法に基づく表記" "大阪府" site:shop-pro.jp',
    '"特定商取引法に基づく表記" "京都府" site:shop-pro.jp',
    '"特定商取引法に基づく表記" "兵庫県" site:shop-pro.jp',
    '"特定商取引法に基づく表記" "奈良県" site:shop-pro.jp',
    # BASE
    '"特定商取引法" "大阪" site:thebase.in',
    '"特定商取引法" "京都" site:thebase.in',
    '"特定商取引法" "兵庫" site:thebase.in',
    '"特定商取引法" "大阪" site:base.shop',
    # STORES
    '"特定商取引法" "大阪" site:stores.jp',
    '"特定商取引法" "京都" site:stores.jp',
    # 独立系EC
    '"特定商取引法に基づく表記" "大阪府" "メール" -rakuten -amazon -yahoo',
    '"特定商取引法に基づく表記" "京都府" "info@" -rakuten -amazon -yahoo',
    '"特定商取引法に基づく表記" "兵庫県" "@" -rakuten -amazon -yahoo',
    '"特定商取引法に基づく表記" "奈良県" "@" -rakuten -amazon -yahoo',
]


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


async def _search_serpapi(client: httpx.AsyncClient, query: str) -> list[str]:
    """SerpAPIでGoogle検索し、結果URLを返す"""
    try:
        resp = await client.get(
            "https://serpapi.com/search.json",
            params={"q": query, "num": 20, "hl": "ja", "gl": "jp", "api_key": settings.SERPAPI_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [r["link"] for r in data.get("organic_results", []) if "link" in r]
    except Exception as e:
        log.debug(f"SerpAPI error: {e}")
        return []


async def collect(seen_emails: set[str], on_progress=None) -> list[CollectedLead]:
    """Google検索（SerpAPI）でリード収集"""
    if not settings.SERPAPI_KEY:
        log.info("SerpAPIキーなし、Google収集スキップ")
        return []

    log.info("Google検索（SerpAPI）収集開始")
    leads: list[CollectedLead] = []
    checked_urls: set[str] = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        total = len(SEARCH_QUERIES)
        for i, query in enumerate(SEARCH_QUERIES):
            if on_progress:
                on_progress(f"Google 検索中 ({i+1}/{total})")
            log.info(f"Google [{i+1}/{total}] {query[:50]}...")

            result_urls = await _search_serpapi(client, query)
            log.info(f"  結果URL: {len(result_urls)}件")

            for url in result_urls:
                if url in checked_urls:
                    continue
                checked_urls.add(url)

                try:
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code != 200:
                        continue
                    html = resp.text
                except Exception:
                    continue

                text = BeautifulSoup(html, "html.parser").get_text()

                if not is_kansai(text):
                    continue

                emails = extract_emails(text)
                if not emails:
                    continue
                if emails[0].lower() in seen_emails:
                    continue

                company = extract_company(text)
                if is_excluded(company):
                    continue

                address = extract_address(text)

                # プラットフォーム判定
                platform = "独立系EC"
                ec_status = "自社ECあり"
                if "shop-pro.jp" in url:
                    platform = "カラーミー"
                    ec_status = "カラーミー利用中"
                elif "thebase.in" in url or "base.shop" in url:
                    platform = "BASE"
                    ec_status = "BASE利用中"
                elif "stores.jp" in url:
                    platform = "STORES"
                    ec_status = "STORES利用中"

                leads.append(CollectedLead(
                    email=emails[0],
                    company=company,
                    industry="",
                    location=address,
                    website=url,
                    platform=platform,
                    ec_status=ec_status,
                    source="google",
                ))
                seen_emails.add(emails[0].lower())

                await asyncio.sleep(0.5)

            await asyncio.sleep(RATE_LIMIT_SEC)

    log.info(f"Google 結果: {len(leads)}件")
    return leads
