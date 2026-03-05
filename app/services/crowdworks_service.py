import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 検索URL（新着順・カテゴリ別）
# Vue SPAのdata属性からJSON取得する方式（2026-03対応）
SEARCH_URLS = [
    "https://crowdworks.jp/public/jobs/search?order=new&category_id=6",   # Web制作
    "https://crowdworks.jp/public/jobs/search?order=new&category_id=7",   # Webデザイン
    "https://crowdworks.jp/public/jobs/search?order=new&category_id=28",  # HP制作
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}


async def fetch_new_jobs(known_external_ids: set[str], known_titles: set[str] | None = None) -> list[dict]:
    """CrowdWorksから新着案件を取得（Vue SSRデータ方式）"""
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set(known_titles or set())

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for search_url in SEARCH_URLS:
            try:
                resp = await client.get(search_url)
                resp.raise_for_status()
                page_jobs = _parse_vue_data(resp.text, known_external_ids | seen_ids, seen_titles)
                for pj in page_jobs:
                    seen_ids.add(pj["external_id"])
                    seen_titles.add(pj["title"])
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


def _parse_vue_data(html: str, known_ids: set[str], seen_titles: set[str] | None = None) -> list[dict]:
    """Vue containerのdata属性からJSON案件データをパース"""
    soup = BeautifulSoup(html, "lxml")
    vue = soup.find(id="vue-container")
    if not vue or not vue.get("data"):
        logger.warning("CW: Vue containerまたはdata属性が見つかりません")
        return []

    try:
        data = json.loads(vue["data"])
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"CW: Vue dataのJSONパース失敗: {e}")
        return []

    job_offers = data.get("searchResult", {}).get("job_offers", [])
    jobs = []

    for item in job_offers:
        jo = item.get("job_offer", {})
        if not jo:
            continue

        try:
            cw_id = str(jo.get("id", ""))
            if not cw_id:
                continue
            external_id = f"cw_{cw_id}"
            if external_id in known_ids:
                continue

            title = jo.get("title", "")
            if seen_titles and title in seen_titles:
                continue
            url = f"https://crowdworks.jp/public/jobs/{cw_id}"
            description = jo.get("description_digest", "")

            deadline = None
            expired_on = jo.get("expired_on")
            if expired_on:
                deadline = _parse_deadline(expired_on)

            jobs.append({
                "platform": "crowdworks",
                "external_id": external_id,
                "url": url,
                "title": title,
                "description": description,
                "category": _classify_category(title),
                "budget_min": None,
                "budget_max": None,
                "budget_type": None,
                "deadline": deadline,
                "client_name": None,
                "client_rating": None,
                "client_review_count": None,
            })
        except Exception as e:
            logger.debug(f"CWパースエラー: {e}")
            continue

    return jobs


def _enrich_job_detail(job: dict, html: str) -> None:
    """詳細ページからdescription/client/budget情報を追加"""
    soup = BeautifulSoup(html, "lxml")

    # Vue dataから詳細情報を取得
    vue = soup.find(id="vue-container")
    if vue and vue.get("data"):
        try:
            data = json.loads(vue["data"])
            jo = data.get("jobOffer", {})
            if jo:
                desc = jo.get("description", "")
                if desc:
                    job["description"] = desc[:3000]

                client = jo.get("client", {})
                if client:
                    job["client_name"] = client.get("name", "")[:50]
                    job["client_rating"] = client.get("rating")

                price = jo.get("price", {})
                if price:
                    bmin, bmax, btype = _parse_budget_from_detail(price)
                    if bmin:
                        job["budget_min"] = bmin
                        job["budget_max"] = bmax
                        job["budget_type"] = btype
                return
        except (json.JSONDecodeError, TypeError):
            pass

    # フォールバック: 従来のHTMLパース
    for sel in [".job_offer_detail_description", ".job-detail__description", "[class*='description']"]:
        desc_el = soup.select_one(sel)
        if desc_el and len(desc_el.get_text(strip=True)) > 30:
            job["description"] = desc_el.get_text(strip=True)[:3000]
            break

    for sel in [".client-info__name", ".employer-info__name"]:
        client_el = soup.select_one(sel)
        if client_el:
            job["client_name"] = client_el.get_text(strip=True)[:50]
            break

    for sel in [".client-info__rating", ".rating-score"]:
        rating_el = soup.select_one(sel)
        if rating_el:
            try:
                job["client_rating"] = float(
                    re.search(r'[\d.]+', rating_el.get_text()).group()
                )
            except (AttributeError, ValueError):
                pass
            break


def _parse_budget_from_detail(price: dict) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """詳細ページのprice辞書から予算をパース"""
    budget_type = "hourly" if price.get("type") == "hourly" else "fixed"
    bmin = price.get("min") or price.get("amount")
    bmax = price.get("max") or bmin
    if bmin:
        try:
            return int(bmin), int(bmax), budget_type
        except (ValueError, TypeError):
            pass
    return None, None, budget_type


def _parse_deadline(text: str) -> Optional[datetime]:
    """期限テキストをパース（ISO形式 or 日本語）"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00").replace("+00:00", ""))
    except (ValueError, TypeError):
        pass
    match = re.search(r'(\d{4})[/年](\d{1,2})[/月](\d{1,2})', text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
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
