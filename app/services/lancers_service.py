import asyncio
import logging
import re
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
LC_STATE_FILE = AUTH_STATE_DIR / "lancers_state.json"

# CSSセレクター（サイト構造変更時はここだけ修正）
LC_SELECTORS = {
    "job_list_item": ".c-search-result__item, .p-search-job__item, .c-media",
    "job_link": "a[href*='/work/detail/']",
    # 一覧ページの価格
    "price": ".p-search-job-media__price, .c-media__price, .price",
    # 詳細ページの説明文
    "description": "dd.c-definition-list__description, .p-work-detail-lancer__postscript-description",
    # 詳細ページの予算（price-block は複数あるので親要素で取る）
    "detail_price": ".price-block",
    # クライアント名
    "client_name": ".client_name, .p-work-detail-sub-heading__client",
    # クライアント評価（Good/Bad）
    "client_rating_good": ".p-work-detail-client-box-feedback-info__number-good",
    "client_rating_bad": ".p-work-detail-client-box-feedback-info__number-bad",
    # 発注率
    "client_order_rate": ".p-work-detail-client-box-feedback-info__percent",
    # Playwright専用セレクター（BeautifulSoupでは使わない）
    "apply_button_pw": 'a:has-text("提案する"), button:has-text("提案する"), a:has-text("応募する")',
    "proposal_textarea": 'textarea[name*="proposal"], textarea[name*="message"], textarea.p-proposal__textarea',
    "budget_input": 'input[name*="price"], input[name*="budget"]',
    "submit_button": 'button[type="submit"]',
}

# 検索URL（新着順、カテゴリ別）
SEARCH_URLS = [
    # Webサイト制作・デザイン
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=80",
    # ECサイト・ネットショップ
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=90",
    # SEO・Webマーケティング
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=100",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def _get_context(playwright) -> BrowserContext:
    """認証済みブラウザコンテキストを取得（Cookie再利用）"""
    browser = await playwright.chromium.launch(headless=True)

    if LC_STATE_FILE.exists():
        try:
            context = await browser.new_context(
                storage_state=str(LC_STATE_FILE),
                viewport={"width": 1280, "height": 800},
                user_agent=UA,
            )
            page = await context.new_page()
            # domcontentloadedで高速チェック（networkidleはLancersで頻繁にタイムアウトする）
            await page.goto("https://www.lancers.jp/mypage",
                            wait_until="domcontentloaded", timeout=20000)
            # リダイレクト完了を少し待つ
            await asyncio.sleep(2)
            # セッション有効: loginにもverify_codeにもリダイレクトされない
            if "/login" not in page.url and "/verify_code" not in page.url:
                logger.info("Lancersセッション復元成功")
                await page.close()
                return context
            # verify_code画面に飛ばされた場合は2FA処理
            if "/verify_code" in page.url:
                logger.info("Lancersセッション期限切れ、2FA再認証中...")
                await page.close()
                await _handle_2fa(context)
                return context
            await page.close()
            await context.close()
        except Exception as e:
            logger.warning(f"Lancersセッション復元失敗: {e}")

    # 新規ログイン
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=UA,
    )
    await _login(context)
    return context


async def _handle_2fa(context: BrowserContext) -> None:
    """Lancers 2FA認証コードをGmailから取得して入力"""
    from app.services.gmail_service import fetch_verification_code

    page = await context.new_page()
    try:
        # verify_code画面でなければ遷移
        if "verify_code" not in page.url:
            await page.goto("https://www.lancers.jp/user/verify_code",
                            wait_until="domcontentloaded", timeout=15000)

        logger.info("Lancers 2FA認証コード画面を検出、Gmailからコード取得中...")
        code = await fetch_verification_code(
            sender_filter="lancers",
            subject_filter="認証",
            code_pattern=r'\b(\d{4,6})\b',
            max_wait_sec=90,
        )
        if not code:
            raise RuntimeError("Lancers認証コードをGmailから取得できませんでした")

        code_input = await page.query_selector(
            'input[placeholder*="認証コード"], input[name*="code"], input[type="text"]'
        )
        if not code_input:
            raise RuntimeError("Lancers認証コード入力欄が見つかりません")

        await code_input.fill(code)
        verify_btn = await page.query_selector(
            'button[type="submit"], button:has-text("認証する")'
        )
        if verify_btn:
            await verify_btn.click()
            await page.wait_for_url("**/mypage**", timeout=15000)

        await context.storage_state(path=str(LC_STATE_FILE))
        logger.info("Lancers 2FA認証成功")
    finally:
        await page.close()


async def _login(context: BrowserContext) -> None:
    """Lancersにログインしてステートを保存（2FA対応）"""
    page = await context.new_page()
    try:
        await page.goto("https://www.lancers.jp/user/login",
                        wait_until="domcontentloaded", timeout=20000)
        # ログインフォームの入力欄を待つ
        await page.wait_for_selector('input#UserEmail, input[name="data[User][email]"]', timeout=10000)
        email_input = await page.query_selector('input#UserEmail, input[name="data[User][email]"]')
        if email_input:
            await email_input.fill(settings.LANCERS_EMAIL)
        password_input = await page.query_selector('input#UserPassword, input[name="data[User][password]"]')
        if password_input:
            await password_input.fill(settings.LANCERS_PASSWORD)
        submit_btn = await page.query_selector('button[type="submit"], input[type="submit"], button:has-text("ログイン")')
        if submit_btn:
            await submit_btn.click()

        # 認証コード画面 or マイページへの遷移を待つ
        await page.wait_for_url(
            re.compile(r"(verify_code|mypage)"), timeout=20000
        )

        # 2FA認証コード画面に遷移した場合
        if "verify_code" in page.url:
            await page.close()
            await _handle_2fa(context)
            return

        await context.storage_state(path=str(LC_STATE_FILE))
        logger.info("Lancers ログイン成功")
    except Exception as e:
        logger.error(f"Lancers ログイン失敗: {e}")
        raise
    finally:
        if not page.is_closed():
            await page.close()


async def fetch_new_jobs(known_external_ids: set[str]) -> list[dict]:
    """Lancersから新着案件をスクレイピング"""
    jobs = []
    seen_ids: set[str] = set()
    async with async_playwright() as p:
        context = await _get_context(p)
        try:
            page = await context.new_page()
            for search_url in SEARCH_URLS:
                try:
                    await page.goto(search_url, wait_until="domcontentloaded",
                                    timeout=20000)
                    await page.wait_for_selector(
                        LC_SELECTORS["job_list_item"], timeout=15000)
                    content = await page.content()
                    # 既知ID + 今回のサイクルで取得済みIDの両方で重複除外
                    page_jobs = _parse_job_list(content, known_external_ids | seen_ids)
                    for pj in page_jobs:
                        seen_ids.add(pj["external_id"])
                    jobs.extend(page_jobs)
                except Exception as e:
                    logger.error(f"Lancersスクレイプエラー ({search_url}): {e}")
                await asyncio.sleep(2)

            # 各案件の詳細ページを取得
            for job in jobs:
                try:
                    await page.goto(job["url"], wait_until="domcontentloaded",
                                    timeout=15000)
                    # 動的コンテンツの読み込みを少し待つ
                    await asyncio.sleep(2)
                    detail_html = await page.content()
                    _enrich_job_detail(job, detail_html)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Lancers詳細取得エラー ({job['url']}): {e}")

            await context.storage_state(path=str(LC_STATE_FILE))
        finally:
            await context.close()

    return jobs


def _parse_job_list(html: str, known_ids: set[str]) -> list[dict]:
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
            url = f"https://www.lancers.jp{href}" if href.startswith("/") else href

            # 一覧ページの価格（複数セレクターにフォールバック）
            budget_el = item.select_one(LC_SELECTORS["price"])
            if not budget_el:
                budget_el = item.select_one(".p-search-job-media__price, [class*='price']")
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget_min, budget_max, budget_type = _parse_budget(budget_text)

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

    # 説明文の取得
    desc_el = soup.select_one(LC_SELECTORS["description"])
    if desc_el:
        job["description"] = desc_el.get_text(strip=True)[:3000]
    else:
        logger.debug("説明文セレクター不一致、フォールバック検索")
        for sel in ["dd[class*='description']", "[class*='postscript-description']"]:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 30:
                job["description"] = el.get_text(strip=True)[:3000]
                break

    # 予算の取得（一覧で取れなかった場合の補完）
    if not job.get("budget_min"):
        price_els = soup.select(LC_SELECTORS["detail_price"])
        if price_els:
            price_text = " ".join(el.get_text(strip=True) for el in price_els)
            bmin, bmax, btype = _parse_budget(price_text)
            if bmin:
                job["budget_min"] = bmin
                job["budget_max"] = bmax
                job["budget_type"] = btype

    # クライアント名
    client_el = soup.select_one(LC_SELECTORS["client_name"])
    if client_el:
        # "MakotoEdit (MakotoEdit)--本人確認..." から名前部分だけ抽出
        raw = client_el.get_text(strip=True)
        name_match = re.match(r'^(.+?)\s*(?:\(|（|--)', raw)
        job["client_name"] = name_match.group(1) if name_match else raw[:50]
    else:
        heading = soup.select_one(".p-work-detail-sub-heading__client")
        if heading:
            raw = heading.get_text(strip=True)
            name_match = re.match(r'^(.+?)\s*(?:\(|（|募集)', raw)
            job["client_name"] = name_match.group(1) if name_match else raw[:50]

    # クライアント評価（Good/Bad比率を5点満点に変換）
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

    # 発注率
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


async def submit_application(
    job_url: str, proposal_text: str, proposed_budget: Optional[int] = None
) -> bool:
    """Playwrightで応募フォームに自動入力・送信"""
    async with async_playwright() as p:
        context = await _get_context(p)
        try:
            page = await context.new_page()
            await page.goto(job_url, wait_until="networkidle", timeout=30000)

            # 案件IDを抽出して提案ページに直接遷移
            id_match = re.search(r'/detail/(\d+)', job_url)
            if not id_match:
                logger.error(f"Lancers案件IDを抽出できません: {job_url}")
                return False
            propose_url = f"https://www.lancers.jp/work/propose_start/{id_match.group(1)}"
            await page.goto(propose_url, wait_until="networkidle", timeout=30000)

            # ログインリダイレクトされた場合
            if "/login" in page.url or "/verify_code" in page.url:
                logger.warning("提案ページでログインリダイレクト検出")
                await page.close()
                if "/verify_code" in page.url:
                    await _handle_2fa(context)
                else:
                    await _login(context)
                page = await context.new_page()
                await page.goto(propose_url, wait_until="networkidle", timeout=30000)

            await page.screenshot(path="data/lc_proposal_form.png")

            # Step1: 提案文を入力
            desc_textarea = await page.query_selector("textarea#ProposalDescription")
            if not desc_textarea:
                logger.error("提案文テキストエリア(#ProposalDescription)が見つかりません")
                return False
            await desc_textarea.fill(proposal_text)

            # 見積もり欄を入力（プロジェクト方式で必須）
            est_textarea = await page.query_selector("textarea#ProposalEstimate")
            if est_textarea and await est_textarea.is_visible():
                estimate_text = (
                    "【お見積もり】\n"
                    "・デザイン制作: ご予算内で対応\n"
                    "・コーディング: レスポンシブ対応込み\n"
                    "・修正対応: 2回まで含む\n"
                    "・納期: ご相談の上決定\n\n"
                    "詳細はヒアリング後にお見積りいたします。"
                )
                await est_textarea.fill(estimate_text)

            # 計画（ProposalOption）の必須フィールドを入力
            opt_title = await page.query_selector("input#ProposalOption0Title")
            if opt_title and await opt_title.is_visible():
                await opt_title.fill("基本プラン")

            opt_desc = await page.query_selector("textarea#ProposalOption0Description")
            if opt_desc and await opt_desc.is_visible():
                await opt_desc.fill("ヒアリング→デザイン→コーディング→納品の流れで対応いたします。")

            opt_amount = await page.query_selector("input#ProposalOption0contractAmount")
            if opt_amount and await opt_amount.is_visible():
                # 予算の下限を使用（なければ50000）
                amount = str(proposed_budget) if proposed_budget else "50000"
                await opt_amount.fill(amount)

            # マイルストーン納期を設定（hidden fields）
            from datetime import datetime as dt, timedelta
            delivery = dt.now() + timedelta(days=30)
            await page.evaluate(f'''() => {{
                const setVal = (name, val) => {{
                    const el = document.querySelector('input[name="' + name + '"]');
                    if (el) el.value = val;
                }};
                setVal('data[Milestone][10][schedule][year]', '{delivery.year}');
                setVal('data[Milestone][10][schedule][month]', '{delivery.month}');
                setVal('data[Milestone][10][schedule][day]', '{delivery.day}');
            }}''')

            # 「内容を確認する」ボタンをクリック → 確認画面へ
            confirm_btn = await page.query_selector('input[type="submit"][value="内容を確認する"]')
            if not confirm_btn:
                confirm_btn = await page.query_selector('input[type="submit"]')
            if not confirm_btn:
                logger.error("確認ボタンが見つかりません")
                return False

            await confirm_btn.scroll_into_view_if_needed()
            await confirm_btn.click()
            await page.wait_for_load_state("networkidle", timeout=20000)
            await page.screenshot(path="data/lc_confirm_page.png")

            # Step2: 確認画面で最終送信
            final_btn = await page.query_selector(
                'input[type="submit"], button[type="submit"], '
                'button:has-text("提案する"), button:has-text("送信")'
            )
            if final_btn:
                await final_btn.scroll_into_view_if_needed()
                await final_btn.click()
                await page.wait_for_load_state("networkidle", timeout=20000)

            await page.screenshot(path="data/lc_submit_result.png")

            # 完了確認
            content = await page.content()
            current_url = page.url
            if any(kw in content for kw in ["提案が完了", "ありがとう", "送信しました", "提案を送信"]):
                logger.info(f"Lancers応募完了: {job_url}")
                await context.storage_state(path=str(LC_STATE_FILE))
                return True
            if "complete" in current_url or "proposals" in current_url:
                logger.info(f"Lancers応募完了（URL確認）: {job_url}")
                await context.storage_state(path=str(LC_STATE_FILE))
                return True

            logger.error(f"Lancers応募送信の確認ができません: {job_url} (URL: {current_url})")
            return False

        except Exception as e:
            logger.error(f"Lancers応募エラー ({job_url}): {e}")
            try:
                await page.screenshot(path="data/lc_apply_error.png")
            except Exception:
                pass
            return False
        finally:
            await context.close()
