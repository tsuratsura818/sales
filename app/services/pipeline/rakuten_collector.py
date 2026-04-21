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


async def collect(
    seen_emails: set[str],
    on_progress=None,
    keywords: list[tuple[str, str]] | None = None,
) -> list[CollectedLead]:
    """楽天市場からリード収集（httpxのみ）"""
    log.info("楽天市場収集開始")
    leads: list[CollectedLead] = []
    shop_codes: dict[str, str] = {}  # shop_code → industry
    kw_list = keywords or SEARCH_KEYWORDS
    consecutive_errors = 0
    skip_codes = {"search", "event", "category", "ranking", "coupon", "help", "mypage", "basket", "purchase", "card", "goldlicense"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Step 1: 楽天検索ページからshopCodeを収集（SSR）
        total_kw = len(kw_list)
        for i, (keyword, industry) in enumerate(kw_list):
            if on_progress:
                on_progress(f"楽天 検索中 ({i+1}/{total_kw})")

            for page in range(1, 2):  # 1ページのみ（キーワード数でカバー）
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

        # Step 2: 特商法ページ取得(5並列で高速化)
        MAX_SHOPS = 150
        shop_items = list(shop_codes.items())[:MAX_SHOPS]
        total = len(shop_items)
        sem = asyncio.Semaphore(5)
        progress_counter = [0]
        error_counter = [0]
        stopped = [False]
        lock = asyncio.Lock()

        async def _fetch_shop(shop_code: str, industry: str):
            if stopped[0]:
                return
            async with sem:
                if stopped[0]:
                    return
                urls = [
                    f"https://www.rakuten.co.jp/{shop_code}/info.html",
                    f"https://www.rakuten.ne.jp/gold/{shop_code}/info.html",
                    f"https://www.rakuten.ne.jp/gold/{shop_code}/company.html",
                ]
                for url in urls:
                    try:
                        resp = await client.get(url, headers=random_ua())
                        if resp.status_code in (403, 429):
                            async with lock:
                                error_counter[0] += 1
                                if error_counter[0] >= 5:
                                    stopped[0] = True
                                    log.error("楽天 連続エラー5回、収集中断")
                                    return
                            await asyncio.sleep(RATE_LIMIT_RAKUTEN * 3)
                            return
                        if resp.status_code != 200:
                            continue
                        async with lock:
                            error_counter[0] = 0

                        html = resp.text
                        text = BeautifulSoup(html, "html.parser").get_text()
                        emails = extract_emails(text)
                        if not emails:
                            continue
                        email_lower = emails[0].lower()
                        async with lock:
                            if email_lower in seen_emails:
                                return
                        if not is_kansai(text):
                            return
                        company = extract_company(text)
                        if is_excluded(company):
                            return
                        if not company:
                            soup = BeautifulSoup(html, "html.parser")
                            title = soup.find("title")
                            if title:
                                name = title.get_text().replace("【楽天市場】", "").split("|")[0].split("｜")[0].strip()
                                if name and re.search(r"[ぁ-んァ-ヶ亜-熙]", name):
                                    company = name
                        address = extract_address(text)

                        async with lock:
                            if email_lower in seen_emails:
                                return
                            seen_emails.add(email_lower)
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
                        return
                    except httpx.TimeoutException:
                        log.debug(f"楽天 特商法タイムアウト: {shop_code}")
                    except Exception as e:
                        log.debug(f"楽天 特商法エラー: {e}")

                async with lock:
                    progress_counter[0] += 1
                    if progress_counter[0] % 20 == 0:
                        log.info(f"楽天 進捗: {progress_counter[0]}/{total} (取得: {len(leads)}件)")
                        if on_progress:
                            on_progress(f"楽天 特商法取得 ({progress_counter[0]}/{total})")
                await asyncio.sleep(RATE_LIMIT_RAKUTEN)

        await asyncio.gather(*[_fetch_shop(sc, ind) for sc, ind in shop_items])

    log.info(f"楽天 結果: {len(leads)}件")
    return leads
