"""Yahoo!ショッピング コレクター（httpxのみ、SSR）"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import SEARCH_KEYWORDS, RATE_LIMIT_SEC, random_ua
from .extractors import extract_emails, extract_company, extract_address, is_kansai, is_excluded

log = logging.getLogger("pipeline.yahoo")


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


async def collect(seen_emails: set[str], on_progress=None) -> list[CollectedLead]:
    """Yahoo!ショッピングからリード収集"""
    log.info("Yahoo!ショッピング収集開始")
    leads: list[CollectedLead] = []
    shop_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Step 1: 検索してshop_idを収集
        total_kw = len(SEARCH_KEYWORDS)
        for i, (keyword, industry) in enumerate(SEARCH_KEYWORDS):
            if on_progress:
                on_progress(f"Yahoo! 検索中 ({i+1}/{total_kw})")

            for page in range(1, 3):
                try:
                    url = f"https://shopping.yahoo.co.jp/search?p={keyword.replace(' ', '+')}&page={page}"
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=re.compile(r"store\.shopping\.yahoo\.co\.jp/([a-z0-9_-]+)/", re.I)):
                        m = re.search(r"store\.shopping\.yahoo\.co\.jp/([a-z0-9_-]+)/", a["href"])
                        if m:
                            shop_ids.add(m.group(1))
                except Exception:
                    pass
                await asyncio.sleep(RATE_LIMIT_SEC)

        log.info(f"Yahoo! 店舗ID: {len(shop_ids)}件")

        # Step 2: 特商法ページ取得
        checked = 0
        total = len(shop_ids)
        for shop_id in shop_ids:
            checked += 1
            if checked % 20 == 0:
                log.info(f"Yahoo! 進捗: {checked}/{total} (取得: {len(leads)}件)")
                if on_progress:
                    on_progress(f"Yahoo! 特商法取得 ({checked}/{total})")

            for url in [
                f"https://store.shopping.yahoo.co.jp/{shop_id}/info.html",
                f"https://shopping.geocities.jp/{shop_id}/info.html",
            ]:
                try:
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code != 200:
                        continue
                    text = BeautifulSoup(resp.text, "html.parser").get_text()

                    if not is_kansai(text):
                        break

                    emails = extract_emails(text)
                    if not emails:
                        continue
                    if emails[0].lower() in seen_emails:
                        break

                    company = extract_company(text)
                    if is_excluded(company):
                        break

                    address = extract_address(text)

                    leads.append(CollectedLead(
                        email=emails[0],
                        company=company or shop_id,
                        industry="",
                        location=address,
                        website=f"https://store.shopping.yahoo.co.jp/{shop_id}/",
                        platform="Yahoo!ショッピング",
                        ec_status="Yahoo!出店中",
                        source="yahoo",
                        shop_code=shop_id,
                    ))
                    seen_emails.add(emails[0].lower())
                    break
                except Exception:
                    pass

            await asyncio.sleep(RATE_LIMIT_SEC)

    log.info(f"Yahoo! 結果: {len(leads)}件")
    return leads
