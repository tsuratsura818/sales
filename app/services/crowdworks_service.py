import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# CSSセレクター（サイト構造変更時はここだけ修正）
CW_SELECTORS = {
    "job_list_item": ".job_listing, .job-list-item, .job_search_results_item",
    "job_link": "a[href*='/jobs/']",
    "price": ".job_listing__price, .job-list-item__price, .payment",
    "description": ".job_offer_detail_description, .job-detail__description",
    "client_name": ".client-info__name, .employer-info__name",
    "client_rating": ".client-info__rating, .rating-score",
    "deadline": ".job-detail__deadline, .deadline",
}

# 検索URL（新着順・公開ページ）
SEARCH_URLS = [
    "https://crowdworks.jp/public/jobs/group/web_production?order=new",
    "https://crowdworks.jp/public/jobs/group/web_design?order=new",
    "https://crowdworks.jp/public/jobs/group/hp?order=new",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}


async def fetch_new_jobs(known_external_ids: set[str]) -> list[dict]:
    """CrowdWorksから新着案件をスクレイピング（httpx版）"""
    jobs: list[dict] = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for search_url in SEARCH_URLS:
            try:
                resp = await client.get(search_url)
                resp.raise_for_status()
                page_jobs = _parse_job_list(resp.text, known_external_ids)
                jobs.extend(page_jobs)
            except Exception as e:
                logger.error(f"CWスクレイプエラー ({search_url}): {e}")
            await asyncio.sleep(2)

        # 各案件の詳細ページを取得
        for job in jobs:
            try:
                resp = await client.get(job["url"])
                resp.raise_for_status()
                _enrich_job_detail(job, resp.text)
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"CW詳細取得エラー ({job['url']}): {e}")

    return jobs


def _parse_job_list(html: str, known_ids: set[str]) -> list[dict]:
    """案件一覧ページHTMLをパース"""
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    for item in soup.select(CW_SELECTORS["job_list_item"]):
        try:
            link = item.select_one(CW_SELECTORS["job_link"])
            if not link:
                continue
            href = link.get("href", "")
            id_match = re.search(r'/jobs/(\d+)', href)
            if not id_match:
                continue
            external_id = f"cw_{id_match.group(1)}"

            if external_id in known_ids:
                continue

            title = link.get_text(strip=True)
            url = f"https://crowdworks.jp{href}" if href.startswith("/") else href

            budget_el = item.select_one(CW_SELECTORS["price"])
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget_min, budget_max, budget_type = _parse_budget(budget_text)

            jobs.append({
                "platform": "crowdworks",
                "external_id": external_id,
                "url": url,
                "title": title,
                "description": "",
                "category": _classify_category(title),
                "budget_min": budget_min,
                "budget_max": budget_max,
                "budget_type": budget_type,
                "deadline": None,
                "client_name": None,
                "client_rating": None,
                "client_review_count": None,
            })
        except Exception as e:
            logger.debug(f"CWパースエラー: {e}")
            continue

    return jobs


def _enrich_job_detail(job: dict, html: str) -> None:
    """詳細ページからdescription/client情報を追加"""
    soup = BeautifulSoup(html, "lxml")

    desc_el = soup.select_one(CW_SELECTORS["description"])
    if desc_el:
        job["description"] = desc_el.get_text(strip=True)[:3000]

    client_el = soup.select_one(CW_SELECTORS["client_name"])
    if client_el:
        job["client_name"] = client_el.get_text(strip=True)

    rating_el = soup.select_one(CW_SELECTORS["client_rating"])
    if rating_el:
        try:
            job["client_rating"] = float(
                re.search(r'[\d.]+', rating_el.get_text()).group()
            )
        except (AttributeError, ValueError):
            pass

    deadline_el = soup.select_one(CW_SELECTORS["deadline"])
    if deadline_el:
        job["deadline"] = _parse_deadline(deadline_el.get_text(strip=True))


def _parse_budget(text: str) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """予算テキストをパース"""
    if not text:
        return None, None, None
    text = text.replace(",", "").replace("，", "")
    budget_type = "hourly" if "時間" in text else "fixed"
    numbers = re.findall(r'(\d+)', text)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), budget_type
    elif len(numbers) == 1:
        return int(numbers[0]), int(numbers[0]), budget_type
    return None, None, budget_type


def _parse_deadline(text: str) -> Optional[datetime]:
    """日本語の期限テキストをパース"""
    match = re.search(r'(\d{4})[/年](\d{1,2})[/月](\d{1,2})', text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)),
                            int(match.group(3)))
        except ValueError:
            pass
    return None


def _classify_category(title: str) -> str:
    """タイトルからカテゴリを推定"""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["ec", "ショップ", "ネットショップ", "shopify", "通販"]):
        return "ec_site"
    if any(kw in title_lower for kw in ["seo", "マーケ", "広告", "集客", "リスティング"]):
        return "seo_marketing"
    return "web_development"


async def submit_application(
    job_url: str, proposal_text: str, proposed_budget: Optional[int] = None
) -> bool:
    """応募送信（Playwright除去により無効化）"""
    logger.warning("CrowdWorks応募送信はPlaywright除去により無効化されています")
    return False
