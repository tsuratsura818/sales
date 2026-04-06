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

from .config import SEARCH_KEYWORDS, RATE_LIMIT_RAKUTEN, random_ua
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
    shop_codes: dict[str, str] = {}  # shop_code → industry
    consecutive_errors = 0
    skip_codes = {"search", "event", "category", "ranking", "coupon", "help", "mypage", "basket", "purchase", "card", "goldlicense"}

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
                    if resp.status_code == 403 or resp.status_code == 429:
                        consecutive_errors += 1
                        log.warning(f"楽天 {resp.status_code} - BAN/レート制限の可能性 ({consecutive_errors}回連続)")
                        if consecutive_errors >= 5:
                            log.error("楽天 連続エラー5回、収集中断")
                            return leads
                        await asyncio.sleep(RATE_LIMIT_RAKUTEN * 3)
                        break
                    if resp.status_code != 200:
                        break
                    consecutive_errors = 0
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=re.compile(r"(?:www|item)\.rakuten\.co\.jp/([a-z0-9_-]+)/", re.I)):
                        m = re.search(r"(?:www|item)\.rakuten\.co\.jp/([a-z0-9_-]+)/", a["href"])
                        if m:
                            code = m.group(1)
                            if code not in skip_codes and code not in shop_codes:
                                shop_codes[code] = industry
                except httpx.TimeoutException:
                    log.debug(f"楽天 検索タイムアウト: {keyword}")
                except Exception as e:
                    log.debug(f"楽天 検索エラー: {e}")
                await asyncio.sleep(RATE_LIMIT_RAKUTEN)

        log.info(f"楽天 店舗ID: {len(shop_codes)}件")

        # Step 2: 特商法ページをhttpxで取得
        checked = 0
        total = len(shop_codes)
        for shop_code, industry in shop_codes.items():
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

            found = False
            for url in urls:
                try:
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code == 403 or resp.status_code == 429:
                        consecutive_errors += 1
                        if consecutive_errors >= 5:
                            log.error("楽天 連続エラー5回、収集中断")
                            return leads
                        await asyncio.sleep(RATE_LIMIT_RAKUTEN * 3)
                        break
                    if resp.status_code != 200:
                        continue
                    consecutive_errors = 0
                    html = resp.text
                    text = BeautifulSoup(html, "html.parser").get_text()

                    emails = extract_emails(text)
                    if not emails:
                        continue
                    if emails[0].lower() in seen_emails:
                        found = True
                        break

                    if not is_kansai(text):
                        found = True
                        break

                    company = extract_company(text)
                    if is_excluded(company):
                        found = True
                        break

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
                        industry=industry,
                        location=address,
                        website=f"https://www.rakuten.co.jp/{shop_code}/",
                        platform="楽天市場",
                        ec_status="楽天出店中",
                        source="rakuten",
                        shop_code=shop_code,
                    ))
                    seen_emails.add(emails[0].lower())
                    found = True
                    break
                except httpx.TimeoutException:
                    log.debug(f"楽天 特商法タイムアウト: {shop_code}")
                except Exception as e:
                    log.debug(f"楽天 特商法エラー: {e}")

            await asyncio.sleep(RATE_LIMIT_RAKUTEN)

    log.info(f"楽天 結果: {len(leads)}件")
    return leads
