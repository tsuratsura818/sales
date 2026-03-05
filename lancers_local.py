"""
Lancers案件取得ローカルサーバー
ダッシュボードの「Lancers案件を取得」ボタンから呼び出される

起動方法: py lancers_local.py
停止: Ctrl+C
"""
import asyncio
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx
from bs4 import BeautifulSoup

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
    text = text.replace(",", "").replace("，", "")
    budget_type = "hourly" if "時間" in text else "fixed"
    numbers = re.findall(r'(\d+)', text)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), budget_type
    elif len(numbers) == 1:
        return int(numbers[0]), int(numbers[0]), budget_type
    return None, None, budget_type


def classify_category(title):
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["ec", "ショップ", "ネットショップ", "shopify", "通販"]):
        return "ec_site"
    if any(kw in title_lower for kw in ["seo", "マーケ", "広告", "集客", "リスティング"]):
        return "seo_marketing"
    return "web_development"


async def fetch_lancers(known_ids, known_titles):
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
                print(f"  {url.split('=')[-1]}: {len(page_jobs)}件")
            except Exception as e:
                print(f"  エラー: {e}")
            await asyncio.sleep(2)

    return jobs


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path != "/scrape-lancers":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}

        known_ids = set(body.get("known_ids", []))
        known_titles = set(body.get("known_titles", []))

        print(f"\nLancers取得開始（既知: {len(known_ids)}件）")
        jobs = asyncio.run(fetch_lancers(known_ids, known_titles))
        print(f"新規案件: {len(jobs)}件")

        response = json.dumps({"jobs": jobs}, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    port = 8765
    server = HTTPServer(("localhost", port), Handler)
    print(f"Lancersローカルサーバー起動: http://localhost:{port}")
    print("ダッシュボードの「Lancers案件を取得」ボタンを押してください")
    print("停止: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")
