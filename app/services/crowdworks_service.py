import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext
from bs4 import BeautifulSoup

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Cookie永続化パス
AUTH_STATE_DIR = Path("data/auth_state")
AUTH_STATE_DIR.mkdir(parents=True, exist_ok=True)
CW_STATE_FILE = AUTH_STATE_DIR / "crowdworks_state.json"

# CSSセレクター（サイト構造変更時はここだけ修正）
CW_SELECTORS = {
    "job_list_item": ".job_listing, .job-list-item, .job_search_results_item",
    "job_link": "a[href*='/jobs/']",
    "price": ".job_listing__price, .job-list-item__price, .payment",
    "description": ".job_offer_detail_description, .job-detail__description",
    "client_name": ".client-info__name, .employer-info__name",
    "client_rating": ".client-info__rating, .rating-score",
    "deadline": ".job-detail__deadline, .deadline",
    "apply_button": 'a:has-text("応募する"), a:has-text("提案する"), button:has-text("応募する")',
    "proposal_textarea": 'textarea[name*="description"], textarea[name*="message"], textarea.proposal-textarea',
    "budget_input": 'input[name*="price"], input[name*="budget"], input[name*="amount"]',
    "submit_button": 'button[type="submit"]:has-text("送信"), input[type="submit"], button:has-text("提案を送信"), button:has-text("応募を送信")',
}

# 検索URL（新着順）
SEARCH_URLS = [
    "https://crowdworks.jp/public/jobs/group/web_production?order=new",
    "https://crowdworks.jp/public/jobs/group/web_design?order=new",
    "https://crowdworks.jp/public/jobs/group/hp?order=new",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def _get_context(playwright) -> BrowserContext:
    """認証済みブラウザコンテキストを取得（Cookie再利用）"""
    browser = await playwright.chromium.launch(headless=True)

    if CW_STATE_FILE.exists():
        try:
            context = await browser.new_context(
                storage_state=str(CW_STATE_FILE),
                viewport={"width": 1280, "height": 800},
                user_agent=UA,
            )
            page = await context.new_page()
            await page.goto("https://crowdworks.jp/mypage",
                            wait_until="networkidle", timeout=15000)
            if "/login" not in page.url and "/sign_in" not in page.url:
                await page.close()
                return context
            await page.close()
            await context.close()
        except Exception as e:
            logger.warning(f"CWセッション復元失敗: {e}")

    # 新規ログイン
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=UA,
    )
    await _login(context)
    return context


async def _login(context: BrowserContext) -> None:
    """CrowdWorksにログインしてCookieを保存"""
    page = await context.new_page()
    try:
        await page.goto("https://crowdworks.jp/login",
                        wait_until="networkidle", timeout=30000)
        # ログインフォームの入力欄を待つ
        await page.wait_for_selector('input[name="username"]', timeout=10000)
        email_input = await page.query_selector('input[name="username"]')
        if email_input:
            await email_input.fill(settings.CROWDWORKS_EMAIL)
        password_input = await page.query_selector('input[name="password"]')
        if password_input:
            await password_input.fill(settings.CROWDWORKS_PASSWORD)
        submit_btn = await page.query_selector('button[type="submit"], input[type="submit"], button:has-text("ログイン")')
        if submit_btn:
            await submit_btn.click()
        await page.wait_for_url("**/mypage**", timeout=15000)
        await context.storage_state(path=str(CW_STATE_FILE))
        logger.info("CrowdWorks ログイン成功")
    except Exception as e:
        logger.error(f"CrowdWorks ログイン失敗: {e}")
        raise
    finally:
        await page.close()


async def fetch_new_jobs(known_external_ids: set[str]) -> list[dict]:
    """CrowdWorksから新着案件をスクレイピング"""
    jobs = []
    async with async_playwright() as p:
        context = await _get_context(p)
        try:
            page = await context.new_page()
            for search_url in SEARCH_URLS:
                try:
                    await page.goto(search_url, wait_until="networkidle",
                                    timeout=20000)
                    await page.wait_for_selector(
                        CW_SELECTORS["job_list_item"], timeout=10000)
                    content = await page.content()
                    page_jobs = _parse_job_list(content, known_external_ids)
                    jobs.extend(page_jobs)
                except Exception as e:
                    logger.error(f"CWスクレイプエラー ({search_url}): {e}")
                await asyncio.sleep(2)  # レート制限

            # 各案件の詳細ページを取得
            for job in jobs:
                try:
                    await page.goto(job["url"], wait_until="networkidle",
                                    timeout=15000)
                    detail_html = await page.content()
                    _enrich_job_detail(job, detail_html)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"CW詳細取得エラー ({job['url']}): {e}")

            await context.storage_state(path=str(CW_STATE_FILE))
        finally:
            await context.close()

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
    """予算テキストをパース。例: '50,000円 ~ 100,000円', '1,000円/時間'"""
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
    """Playwrightで応募フォームに自動入力・送信"""
    async with async_playwright() as p:
        context = await _get_context(p)
        try:
            page = await context.new_page()
            await page.goto(job_url, wait_until="networkidle", timeout=20000)

            # 応募ボタンをクリック
            apply_btn = await page.query_selector(CW_SELECTORS["apply_button"])
            if not apply_btn:
                logger.error(f"CW応募ボタンが見つかりません: {job_url}")
                return False

            await apply_btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)

            # 提案文を入力
            textarea = await page.query_selector(CW_SELECTORS["proposal_textarea"])
            if textarea:
                await textarea.fill(proposal_text)

            # 予算を入力（該当する場合）
            if proposed_budget:
                budget_input = await page.query_selector(CW_SELECTORS["budget_input"])
                if budget_input:
                    await budget_input.fill(str(proposed_budget))

            # 送信
            submit_btn = await page.query_selector(CW_SELECTORS["submit_button"])
            if submit_btn:
                await submit_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)

                # 成功確認
                content = await page.content()
                if any(kw in content for kw in ["ありがとうございます", "応募が完了", "提案を送信"]):
                    logger.info(f"CW応募完了: {job_url}")
                    await context.storage_state(path=str(CW_STATE_FILE))
                    return True
                if "proposals" in page.url or "complete" in page.url:
                    logger.info(f"CW応募完了（URL確認）: {job_url}")
                    await context.storage_state(path=str(CW_STATE_FILE))
                    return True

            logger.error(f"CW応募送信の確認ができません: {job_url}")
            return False

        except Exception as e:
            logger.error(f"CW応募エラー ({job_url}): {e}")
            return False
        finally:
            await context.close()
