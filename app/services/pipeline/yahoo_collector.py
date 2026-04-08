"""Yahoo!ショッピング コレクター（httpxのみ、SSR）"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import SEARCH_KEYWORDS, RATE_LIMIT_YAHOO, random_ua
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


async def collect(
    seen_emails: set[str],
    on_progress=None,
    keywords: list[tuple[str, str]] | None = None,
) -> list[CollectedLead]:
    """Yahoo!ショッピングからリード収集"""
    log.info("Yahoo!ショッピング収集開始")
    leads: list[CollectedLead] = []
    shop_ids: dict[str, str] = {}  # shop_id → industry
    consecutive_errors = 0
    kw_list = keywords or SEARCH_KEYWORDS

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Step 1: 検索してshop_idを収集
        total_kw = len(kw_list)
        for i, (keyword, industry) in enumerate(kw_list):
            if on_progress:
                on_progress(f"Yahoo! 検索中 ({i+1}/{total_kw})")

            for page in range(1, 2):  # 1ページのみ（キーワード数でカバー）
                try:
                    url = f"https://shopping.yahoo.co.jp/search?p={keyword.replace(' ', '+')}&page={page}"
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code == 403 or resp.status_code == 429:
                        consecutive_errors += 1
                        log.warning(f"Yahoo! {resp.status_code} - BAN/レート制限の可能性 ({consecutive_errors}回連続)")
                        if consecutive_errors >= 5:
                            log.error("Yahoo! 連続エラー5回、収集中断")
                            return leads
                        await asyncio.sleep(RATE_LIMIT_YAHOO * 3)
                        break
                    if resp.status_code != 200:
                        break
                    consecutive_errors = 0
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=re.compile(r"store\.shopping\.yahoo\.co\.jp/([a-z0-9_-]+)/", re.I)):
                        m = re.search(r"store\.shopping\.yahoo\.co\.jp/([a-z0-9_-]+)/", a["href"])
                        if m and m.group(1) not in shop_ids:
                            shop_ids[m.group(1)] = industry
                except httpx.TimeoutException:
                    log.debug(f"Yahoo! 検索タイムアウト: {keyword}")
                except Exception as e:
                    log.debug(f"Yahoo! 検索エラー: {e}")
                await asyncio.sleep(RATE_LIMIT_YAHOO)

        log.info(f"Yahoo! 店舗ID: {len(shop_ids)}件")

        # Step 2: 特商法ページ取得（最大150店舗）
        MAX_SHOPS = 150
        checked = 0
        shop_items = list(shop_ids.items())[:MAX_SHOPS]
        total = len(shop_items)
        for shop_id, industry in shop_items:
            checked += 1
            if checked % 20 == 0:
                log.info(f"Yahoo! 進捗: {checked}/{total} (取得: {len(leads)}件)")
                if on_progress:
                    on_progress(f"Yahoo! 特商法取得 ({checked}/{total})")

            url = f"https://store.shopping.yahoo.co.jp/{shop_id}/info.html"
            try:
                resp = await client.get(url, headers=random_ua())
                if resp.status_code == 403 or resp.status_code == 429:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        log.error("Yahoo! 連続エラー5回、収集中断")
                        break
                    await asyncio.sleep(RATE_LIMIT_YAHOO * 3)
                    continue
                if resp.status_code != 200:
                    continue
                consecutive_errors = 0
                text = BeautifulSoup(resp.text, "html.parser").get_text()

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

                leads.append(CollectedLead(
                    email=emails[0],
                    company=company or shop_id,
                    industry=industry,
                    location=address,
                    website=f"https://store.shopping.yahoo.co.jp/{shop_id}/",
                    platform="Yahoo!ショッピング",
                    ec_status="Yahoo!出店中",
                    source="yahoo",
                    shop_code=shop_id,
                ))
                seen_emails.add(emails[0].lower())
            except httpx.TimeoutException:
                log.debug(f"Yahoo! 特商法タイムアウト: {shop_id}")
            except Exception as e:
                log.debug(f"Yahoo! 特商法エラー: {e}")

            await asyncio.sleep(RATE_LIMIT_YAHOO)

    log.info(f"Yahoo! 結果: {len(leads)}件")
    return leads
