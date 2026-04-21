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

        # Step 2: 特商法ページ取得（最大150店舗、5並列で高速化）
        MAX_SHOPS = 150
        shop_items = list(shop_ids.items())[:MAX_SHOPS]
        total = len(shop_items)
        sem = asyncio.Semaphore(5)
        progress_counter = [0]
        error_counter = [0]
        stopped = [False]
        lock = asyncio.Lock()

        async def _fetch_shop(shop_id: str, industry: str):
            if stopped[0]:
                return
            async with sem:
                if stopped[0]:
                    return
                url = f"https://store.shopping.yahoo.co.jp/{shop_id}/info.html"
                try:
                    resp = await client.get(url, headers=random_ua())
                    if resp.status_code in (403, 429):
                        async with lock:
                            error_counter[0] += 1
                            if error_counter[0] >= 5:
                                stopped[0] = True
                                log.error("Yahoo! 連続エラー5回、収集中断")
                                return
                        await asyncio.sleep(RATE_LIMIT_YAHOO * 3)
                        return
                    if resp.status_code != 200:
                        return
                    async with lock:
                        error_counter[0] = 0

                    text = BeautifulSoup(resp.text, "html.parser").get_text()
                    if not is_kansai(text):
                        return
                    emails = extract_emails(text)
                    if not emails:
                        return
                    email_lower = emails[0].lower()
                    async with lock:
                        if email_lower in seen_emails:
                            return
                        seen_emails.add(email_lower)

                    company = extract_company(text)
                    if is_excluded(company):
                        return
                    address = extract_address(text)

                    async with lock:
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
                except httpx.TimeoutException:
                    log.debug(f"Yahoo! 特商法タイムアウト: {shop_id}")
                except Exception as e:
                    log.debug(f"Yahoo! 特商法エラー: {e}")
                finally:
                    async with lock:
                        progress_counter[0] += 1
                        if progress_counter[0] % 20 == 0:
                            log.info(f"Yahoo! 進捗: {progress_counter[0]}/{total} (取得: {len(leads)}件)")
                            if on_progress:
                                on_progress(f"Yahoo! 特商法取得 ({progress_counter[0]}/{total})")
                    await asyncio.sleep(RATE_LIMIT_YAHOO)

        await asyncio.gather(*[_fetch_shop(sid, ind) for sid, ind in shop_items])

    log.info(f"Yahoo! 結果: {len(leads)}件")
    return leads
