"""
Lancers案件取得スクリプト（ローカルPC実行用）

使い方: py lancers_local.py
→ ローカルPCからLancersをスクレイピング
→ サーバーに送信してAI評価→LINE通知
"""
import asyncio
import json
import re
import sys

import httpx
from bs4 import BeautifulSoup

SERVER_URL = "https://sales-6g78.onrender.com"
HEARTBEAT_URL = SERVER_URL + "/api/heartbeat/lancers_local"


def send_heartbeat(status="ok", message="", count=None):
    try:
        payload = {"status": status, "message": message[:500]}
        if count is not None:
            payload["count"] = int(count)
        httpx.post(HEARTBEAT_URL, json=payload, timeout=10)
    except Exception:
        pass

LC_SELECTORS = {
    "job_list_item": ".c-search-result__item, .p-search-job__item, .c-media",
    "job_link": "a[href*='/work/detail/']",
    "price": ".p-search-job-media__price, .c-media__price, .price",
}

SEARCH_URLS = [
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=80",
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=90",
    "https://www.lancers.jp/work/search?open=1&show_description=0&sort=started&work_category_ids%5B%5D=100",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}


def parse_job_list(html, known_ids, known_titles):
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
            if title in known_titles:
                continue

            url = f"https://www.lancers.jp{href}" if href.startswith("/") else href

            budget_el = item.select_one(LC_SELECTORS["price"])
            if not budget_el:
                budget_el = item.select_one(".p-search-job-media__price, [class*='price']")
            budget_text = budget_el.get_text(strip=True) if budget_el else ""
            budget_min, budget_max, budget_type = parse_budget(budget_text)

            if is_low_quality(title, budget_min, budget_max, budget_type):
                continue

            jobs.append({
                "platform": "lancers",
                "external_id": external_id,
                "url": url,
                "title": title,
                "description": "",
                "category": classify_category(title),
                "budget_min": budget_min,
                "budget_max": budget_max,
                "budget_type": budget_type,
            })
        except Exception:
            continue
    return jobs


def parse_budget(text):
    if not text:
        return None, None, None
    text = text.replace(",", "").replace("\uff0c", "")
    budget_type = "hourly" if "\u6642\u9593" in text else "fixed"
    numbers = re.findall(r'(\d+)', text)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), budget_type
    elif len(numbers) == 1:
        return int(numbers[0]), int(numbers[0]), budget_type
    return None, None, budget_type


def classify_category(title):
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["ec", "\u30b7\u30e7\u30c3\u30d7", "\u30cd\u30c3\u30c8\u30b7\u30e7\u30c3\u30d7", "shopify", "\u901a\u8ca9"]):
        return "ec_site"
    if any(kw in title_lower for kw in ["seo", "\u30de\u30fc\u30b1", "\u5e83\u544a", "\u96c6\u5ba2", "\u30ea\u30b9\u30c6\u30a3\u30f3\u30b0"]):
        return "seo_marketing"
    return "web_development"


PREFILTER_OUT_PATTERNS = re.compile(
    r"(\u30b3\u30d4\u30da|\u7c21\u5358\u30b9\u30de\u30db|\u30b9\u30de\u30db\u4f5c\u696d\u306e\u307f|\u30a2\u30f3\u30b1\u30fc\u30c8\u56de\u7b54|\u30c7\u30fc\u30bf\u5165\u529b|"
    r"\u672a\u7d4c\u9a13OK|\u4e3b\u5a66\u6b53\u8fce|\u526f\u696d\u6b53\u8fce|\u30bf\u30b9\u30af\u5831\u916c|\u30bf\u30a4\u30d4\u30f3\u30b0|"
    r"\u52d5\u753b\u8996\u8074|\u30b2\u30fc\u30e0\u914d\u4fe1|\u30e2\u30cb\u30bf\u30fc\u8abf\u67fb|\u5546\u54c1\u30ec\u30d3\u30e5\u30fc|"
    r"\u30bf\u30c3\u30d7|\u8ee2\u9001|\u7c21\u5358\u4f5c\u696d|"
    r"\u30a2\u30d5\u30a3\u30ea\u30a8\u30a4\u30c8\u7d39\u4ecb|MLM|\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u30d3\u30b8\u30cd\u30b9|"
    r"\u30a2\u30c0\u30eb\u30c8|\u51fa\u4f1a\u3044\u7cfb|\u30c1\u30e3\u30c3\u30c8\u30ec\u30c7\u30a3)"
)


def is_low_quality(title, budget_min, budget_max, budget_type):
    if PREFILTER_OUT_PATTERNS.search(title):
        return True
    if budget_type == "fixed" and budget_max is not None and budget_max < 3000:
        return True
    if budget_type == "hourly" and budget_max is not None and budget_max < 800:
        return True
    return False


async def main():
    print("=" * 50)
    print("Lancers案件取得スクリプト")
    print("=" * 50)

    # 1. サーバーから既知の案件を取得
    print("\n[1/3] サーバーから既知案件を取得中...")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{SERVER_URL}/api/job-monitor/known")
            resp.raise_for_status()
            known = resp.json()
            known_ids = set(known["external_ids"])
            known_titles = set(known["titles"])
            print(f"  既知: {len(known_ids)}件")
        except Exception as e:
            print(f"  サーバー接続エラー: {e}")
            sys.exit(1)

    # 2. Lancersをスクレイピング
    print("\n[2/3] Lancersから案件を取得中...")
    jobs = []
    seen_ids = set(known_ids)
    seen_titles = set(known_titles)

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for url in SEARCH_URLS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                page_jobs = parse_job_list(resp.text, seen_ids, seen_titles)
                for pj in page_jobs:
                    seen_ids.add(pj["external_id"])
                    seen_titles.add(pj["title"])
                jobs.extend(page_jobs)
                cat_id = url.split("=")[-1]
                print(f"  カテゴリ{cat_id}: {len(page_jobs)}件")
            except Exception as e:
                print(f"  エラー: {e}")
            await asyncio.sleep(2)

    print(f"  合計新規: {len(jobs)}件")

    if not jobs:
        print("\n新規案件なし。終了します。")
        send_heartbeat(status="ok_no_jobs", message="新規案件なし", count=0)
        return

    # 3. サーバーに送信
    print(f"\n[3/3] サーバーに送信中（AI評価 + LINE通知）...")
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        try:
            resp = await client.post(
                f"{SERVER_URL}/api/job-monitor/import",
                json={"jobs": jobs},
            )
            resp.raise_for_status()
            result = resp.json()
            print(f"\n  {result['message']}")
            send_heartbeat(
                status="ok",
                message=result.get("message", ""),
                count=result.get("notified_count") or result.get("new_count") or len(jobs),
            )
        except Exception as e:
            print(f"  送信エラー: {e}")
            send_heartbeat(status="error", message=str(e)[:300])
            sys.exit(1)

    print("\n完了!")


if __name__ == "__main__":
    asyncio.run(main())
