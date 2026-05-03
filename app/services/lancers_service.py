import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# CSSセレクター（サイト構造変更時はここだけ修正）
LC_SELECTORS = {
    "job_list_item": ".c-search-result__item, .p-search-job__item, .c-media",
    "job_link": "a[href*='/work/detail/']",
    "price": ".p-search-job-media__price, .c-media__price, .price",
    "description": "dd.c-definition-list__description, .p-work-detail-lancer__postscript-description",
    "detail_price": ".price-block",
    "client_name": ".client_name, .p-work-detail-sub-heading__client",
    "client_rating_good": ".p-work-detail-client-box-feedback-info__number-good",
    "client_rating_bad": ".p-work-detail-client-box-feedback-info__number-bad",
    "client_order_rate": ".p-work-detail-client-box-feedback-info__percent",
}

# 検索URL（新着順、カテゴリ別）
SEARCH_URLS = [
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=80",
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=90",
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=100",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}


async def fetch_new_jobs(known_external_ids: set[str], known_titles: set[str] | None = None) -> list[dict]:
    """Lancersから新着案件をスクレイピング（httpx版）"""
    from app.services.settings_service import get_monitor_settings
    ms = get_monitor_settings()
    search_urls = [
        f"https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D={cat_id}"
        for cat_id in ms.lc_categories
    ]

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set(known_titles or set())

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for search_url in search_urls:
            try:
                resp = await client.get(search_url)
                resp.raise_for_status()
                page_jobs = _parse_job_list(resp.text, known_external_ids | seen_ids, seen_titles)
                for pj in page_jobs:
                    seen_ids.add(pj["external_id"])
                    seen_titles.add(pj["title"])
                jobs.extend(page_jobs)
            except Exception as e:
                logger.error(f"Lancersスクレイプエラー ({search_url}): {e}")
            await asyncio.sleep(2)

        # 各案件の詳細ページを取得
        for job in jobs:
            try:
                resp = await client.get(job["url"])
                resp.raise_for_status()
                _enrich_job_detail(job, resp.text)
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Lancers詳細取得エラー ({job['url']}): {e}")

    return jobs


def _parse_job_list(html: str, known_ids: set[str], seen_titles: set[str] | None = None) -> list[dict]:
    """案件一覧ページHTMLをパース"""
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    for item in soup.select(LC_SELECTORS["job_list_item"]):
        try:
            link = item.select_one(LC_SELECTORS["job_link"])
            if not link:
                continue
            href = link.get("href", "")
            id_match = re.search(r'/detail/(\d+)', href)
            if not id_match:
                continue

            external_id = f"lc_{id_match.group(1)}"
            if external_id in known_ids:
                continue

            title = link.get_text(strip=True)
            if seen_titles and title in seen_titles:
                continue

            title = link.get_text(strip=True)
            url = f"https://www.lancers.jp{href}" if href.startswith("/") else href

            budget_el = item.select_one(LC_SELECTORS["price"])
            if not budget_el:
                budget_el = item.select_one(".p-search-job-media__price, [class*='price']")
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget_min, budget_max, budget_type = _parse_budget(budget_text)

            # 事前フィルタ: 明らかに対象外な案件はAI評価せず即スキップ
            if is_low_quality(title, budget_min, budget_max, budget_type):
                logger.debug(f"Lancers事前フィルタで除外: {title[:40]}")
                continue

            jobs.append({
                "platform": "lancers",
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
            logger.debug(f"Lancersパースエラー: {e}")
            continue

    return jobs


def _enrich_job_detail(job: dict, html: str) -> None:
    """詳細ページからdescription/client/budget情報を追加"""
    soup = BeautifulSoup(html, "lxml")

    desc_el = soup.select_one(LC_SELECTORS["description"])
    if desc_el:
        job["description"] = desc_el.get_text(strip=True)[:3000]
    else:
        for sel in ["dd[class*='description']", "[class*='postscript-description']"]:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 30:
                job["description"] = el.get_text(strip=True)[:3000]
                break

    if not job.get("budget_min"):
        price_els = soup.select(LC_SELECTORS["detail_price"])
        if price_els:
            price_text = " ".join(el.get_text(strip=True) for el in price_els)
            bmin, bmax, btype = _parse_budget(price_text)
            if bmin:
                job["budget_min"] = bmin
                job["budget_max"] = bmax
                job["budget_type"] = btype

    client_el = soup.select_one(LC_SELECTORS["client_name"])
    if client_el:
        raw = client_el.get_text(strip=True)
        name_match = re.match(r'^(.+?)\s*(?:\(|（|--)', raw)
        job["client_name"] = name_match.group(1) if name_match else raw[:50]
    else:
        heading = soup.select_one(".p-work-detail-sub-heading__client")
        if heading:
            raw = heading.get_text(strip=True)
            name_match = re.match(r'^(.+?)\s*(?:\(|（|募集)', raw)
            job["client_name"] = name_match.group(1) if name_match else raw[:50]

    good_el = soup.select_one(LC_SELECTORS["client_rating_good"])
    bad_el = soup.select_one(LC_SELECTORS["client_rating_bad"])
    if good_el:
        try:
            good = int(good_el.get_text(strip=True))
            bad = int(bad_el.get_text(strip=True)) if bad_el else 0
            total = good + bad
            if total > 0:
                job["client_rating"] = round(good / total * 5, 1)
                job["client_review_count"] = total
        except (ValueError, TypeError):
            pass

    rate_el = soup.select_one(LC_SELECTORS["client_order_rate"])
    if rate_el:
        rate_text = rate_el.get_text(strip=True)
        rate_match = re.search(r'(\d+)', rate_text)
        if rate_match:
            logger.debug(f"発注率: {rate_match.group(1)}%")


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


def _classify_category(title: str) -> str:
    """タイトルからカテゴリを推定"""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["ec", "ショップ", "ネットショップ", "shopify", "通販"]):
        return "ec_site"
    if any(kw in title_lower for kw in ["seo", "マーケ", "広告", "集客", "リスティング"]):
        return "seo_marketing"
    return "web_development"


# 明らかに対象外のキーワード。AI評価コール前に即除外する（コスト削減 + ノイズ通知防止）
PREFILTER_OUT_PATTERNS = re.compile(
    r"(コピペ|簡単スマホ|スマホ作業のみ|アンケート回答|データ入力|"
    r"未経験OK|主婦歓迎|副業歓迎|タスク報酬|タイピング|"
    r"動画視聴|ゲーム配信|モニター調査|商品レビュー|"
    r"在宅ワーク[未初]|タップ|転送|簡単作業|"
    r"アフィリエイト紹介|MLM|ネットワークビジネス|"
    r"アダルト|出会い系|チャットレディ)"
)


def is_low_quality(title: str, budget_min: int | None = None, budget_max: int | None = None, budget_type: str | None = None) -> bool:
    """明らかに対象外と分かる案件は事前除外"""
    if PREFILTER_OUT_PATTERNS.search(title):
        return True
    # 固定3000円未満は除外（明らかに低価格）
    if budget_type == "fixed" and budget_max is not None and budget_max < 3000:
        return True
    # 時給800円未満も除外
    if budget_type == "hourly" and budget_max is not None and budget_max < 800:
        return True
    return False


async def submit_application(
    job_url: str, proposal_text: str, proposed_budget: Optional[int] = None
) -> bool:
    """応募送信（Playwright除去により無効化）"""
    logger.warning("Lancers応募送信はPlaywright除去により無効化されています")
    return False
