"""楽天市場コレクター（httpxのみ版 — Playwright不要）

楽天の特商法ページはSSR部分が多いため、httpxで取得可能な範囲で収集。
JS必須のページはスキップ（取得率は下がるが、依存関係なしで動作）
"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import SEARCH_KEYWORDS, RATE_LIMIT_SEC, random_ua
from .extractors import extract_emails, extract_company, extract_address, is_kansai, is_excluded

log = logging.getLogger("pipeline.rakuten")


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
    """楽天市場からリード収集（httpxのみ）"""
    log.info("楽天市場収集開始")
    leads: list[CollectedLead] = []
    shop_codes: set[str] = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Step 1: 楽天検索ページからshopCodeを収集（SSR）
        total_kw = len(SEARCH_KEYWORDS)
        for i, (keyword, industry) in enumerate(SEARCH_KEYWORDS):
            if on_progress:
                on_progress(f"楽天 検索中 ({i+1}/{total_kw})")

            for page in range(1, 3):
                try:
                    url = f"https://search.rakuten.co.jp/search/mall/{keyword.replace(' ', '+')}/?p={page}"
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    skip_codes = {"search", "event", "category", "ranking", "coupon", "help", "mypage", "basket", "purchase", "card", "goldlicense"}
                    for a in soup.find_all("a", href=re.compile(r"(?:www|item)\.rakuten\.co\.jp/([a-z0-9_-]+)/", re.I)):
                        m = re.search(r"(?:www|item)\.rakuten\.co\.jp/([a-z0-9_-]+)/", a["href"])
                        if m:
                            code = m.group(1)
                            if code not in skip_codes:
                                shop_codes.add(code)
                except Exception:
                    pass
                await asyncio.sleep(RATE_LIMIT_SEC)

        log.info(f"楽天 店舗ID: {len(shop_codes)}件")

        # Step 2: 特商法ページをhttpxで取得
        checked = 0
        total = len(shop_codes)
        for shop_code in shop_codes:
            checked += 1
            if checked % 20 == 0:
                log.info(f"楽天 進捗: {checked}/{total} (取得: {len(leads)}件)")
                if on_progress:
                    on_progress(f"楽天 特商法取得 ({checked}/{total})")

            urls = [
                f"https://www.rakuten.co.jp/{shop_code}/info.html",
                f"https://www.rakuten.ne.jp/gold/{shop_code}/info.html",
                f"https://www.rakuten.ne.jp/gold/{shop_code}/company.html",
            ]

            for url in urls:
                try:
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code != 200:
                        continue
                    html = resp.text
                    text = BeautifulSoup(html, "html.parser").get_text()

                    emails = extract_emails(text)
                    if not emails:
                        continue
                    if emails[0].lower() in seen_emails:
                        break

                    if not is_kansai(text):
                        break

                    company = extract_company(text)
                    if is_excluded(company):
                        break

                    # タイトルタグからショップ名取得（フォールバック）
                    if not company:
                        soup = BeautifulSoup(html, "html.parser")
                        title = soup.find("title")
                        if title:
                            name = title.get_text().replace("【楽天市場】", "").split("|")[0].split("｜")[0].strip()
                            if name and re.search(r"[ぁ-んァ-ヶ亜-熙]", name):
                                company = name

                    address = extract_address(text)

                    leads.append(CollectedLead(
                        email=emails[0],
                        company=company or shop_code,
                        industry="",
                        location=address,
                        website=f"https://www.rakuten.co.jp/{shop_code}/",
                        platform="楽天市場",
                        ec_status="楽天出店中",
                        source="rakuten",
                        shop_code=shop_code,
                    ))
                    seen_emails.add(emails[0].lower())
                    break
                except Exception:
                    pass

            await asyncio.sleep(RATE_LIMIT_SEC)

    log.info(f"楽天 結果: {len(leads)}件")
    return leads
