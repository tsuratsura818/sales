"""全国カテゴリ収集コレクター（list_generator_v3_1 からの移植）

DuckDuckGo検索で全国47都道府県×業種カテゴリ(A/B/C/D)のリード収集。
list_generator_v3_1 のロジックをSellBuddyの CollectedLead 形式に合わせて統合。

- A: Shopify D2C (食品・化粧品・アパレル・雑貨 等の自社ブランド)
- B: WordPress コーポレート (士業・製造・建設・不動産・商社)
- C: LP制作 (スクール・クリニック・BtoBサービス)
- D: 飲食店EC (焼肉・寿司・カフェ・精肉店・鮮魚店)
"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import RATE_LIMIT_SEC, random_ua
from .site_analyzer import (
    analyze_html, extract_emails, _same_domain,
    find_contact_urls, detect_issues,
)

log = logging.getLogger("pipeline.category")


# ============================================================
# カテゴリ定義
# ============================================================

CATEGORIES = {
    "A": {"name": "Shopify D2C", "description": "自社ブランドを持つD2Cメーカー"},
    "B": {"name": "WordPress コーポレート", "description": "中小企業コーポレートサイト"},
    "C": {"name": "LP制作", "description": "キャンペーン/サービスLP"},
    "D": {"name": "飲食店EC", "description": "通販未対応の飲食店・食品店"},
}

SUBCATEGORIES = {
    "A": [
        "和菓子 メーカー", "洋菓子 ブランド", "調味料 メーカー",
        "クラフトビール 醸造所", "日本酒 蔵元", "ワイナリー",
        "化粧品 D2C", "スキンケア ブランド", "オーガニック化粧品",
        "アパレルブランド", "ファッション D2C", "靴 メーカー",
        "バッグブランド", "ジュエリー デザイナー", "眼鏡 ブランド",
        "雑貨メーカー", "インテリア ブランド", "工芸品 ブランド",
        "伝統工芸", "家具メーカー", "キッチン用品 ブランド",
        "オーガニック食品 メーカー", "サステナブル ブランド",
    ],
    "B": [
        "税理士事務所", "社労士事務所", "司法書士事務所",
        "行政書士事務所", "弁護士事務所",
        "総合建設会社", "不動産管理会社", "建築設計事務所",
        "リフォーム会社", "工務店",
        "金属加工 メーカー", "プラスチック成形", "精密機械 メーカー",
        "電子部品 メーカー", "化学製品 メーカー", "食品製造",
        "食品卸", "医療機器 商社", "建材 商社",
        "人材派遣会社", "印刷会社", "物流会社", "清掃サービス", "警備会社",
    ],
    "C": [
        "プログラミングスクール", "英会話スクール", "ビジネススクール",
        "オンライン講座", "資格スクール", "コーチングスクール",
        "歯科クリニック 審美", "美容クリニック", "整体院",
        "整骨院", "エステサロン", "パーソナルジム", "ヨガスタジオ",
        "経営コンサル", "マーケティング会社", "助成金コンサル",
        "人事コンサル", "BtoB SaaS",
        "保険代理店", "ファイナンシャルプランナー",
        "注文住宅", "リノベーション",
    ],
    "D": [
        "焼肉店 老舗", "ホルモン専門店", "ステーキハウス", "肉バル",
        "日本料理店", "寿司店 高級", "割烹", "懐石料理",
        "フレンチレストラン", "イタリアン", "ビストロ",
        "ラーメン店 名店", "うどん専門店", "そば専門店",
        "精肉店", "鮮魚店", "八百屋 老舗", "食肉卸", "水産卸",
        "カフェ 人気店", "パティスリー", "パン屋 人気店",
        "日本酒 専門店", "ワインショップ",
    ],
}

PREFECTURES = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島",
    "東京", "神奈川", "埼玉", "千葉", "茨城", "栃木", "群馬",
    "新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜", "静岡", "愛知",
    "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口",
    "徳島", "香川", "愛媛", "高知",
    "福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄",
]

PRIORITY_PREFECTURES = [
    "東京", "大阪", "愛知", "神奈川", "福岡",
    "京都", "兵庫", "埼玉", "千葉", "北海道",
]

SCALE_KEYWORDS = ["中小", "個人経営", "老舗", ""]

TARGET_MODIFIERS = {
    "A": ["自社ブランド", "オンラインショップ", "通販", "D2C"],
    "B": ["公式サイト", "中小企業", "", "コーポレート"],
    "C": ["個人", "", "新規 キャンペーン", ""],
    "D": ["人気", "", "有名店", "老舗"],
}


# ============================================================
# 除外・分類ロジック（list_generator_v3_1 から）
# ============================================================

EXCLUDE_KEYWORDS = {
    "web_agency": [
        "web制作", "ホームページ制作", "webデザイン", "web開発",
        "ウェブ制作", "web制作会社", "広告代理店", "デザイン事務所",
    ],
    "portal_media": [
        "まとめ", "ランキング", "おすすめ.*選", "比較サイト",
        "口コミサイト", "アフィリエイト",
    ],
    "blog_personal": [
        "個人ブログ", "はてなブログ", "アメブロ", "note.com",
    ],
}

EXCLUDED_DOMAINS = {
    "hotpepper.jp", "tabelog.com", "retty.me", "gnavi.co.jp",
    "rakuten.co.jp", "amazon.co.jp", "yahoo.co.jp",
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "wikipedia.org", "note.com", "ameblo.jp", "hatenablog.com",
    "prtimes.jp", "biglobe.ne.jp", "mynavi.jp", "doda.jp",
}

CATEGORY_KEYWORDS = {
    "A": [
        ("和菓子", 1.5), ("洋菓子", 1.5), ("調味料", 1.3), ("クラフトビール", 1.8),
        ("化粧品", 1.5), ("スキンケア", 1.5), ("コスメ", 1.3),
        ("アパレル", 1.5), ("d2c", 2.0), ("自社ブランド", 1.8),
        ("オンラインショップ", 1.5), ("shopify", 1.5),
    ],
    "B": [
        ("税理士", 2.0), ("社労士", 2.0), ("司法書士", 2.0),
        ("行政書士", 2.0), ("弁護士", 1.8),
        ("工務店", 1.8), ("建設", 1.5), ("製造", 1.3),
        ("商社", 1.3), ("卸売", 1.3), ("印刷会社", 1.5),
    ],
    "C": [
        ("プログラミングスクール", 1.8), ("英会話", 1.5),
        ("歯科", 1.5), ("美容クリニック", 1.8),
        ("整体", 1.8), ("エステ", 1.8), ("パーソナルジム", 1.8),
        ("経営コンサル", 1.5), ("保険代理店", 1.5),
    ],
    "D": [
        ("焼肉", 2.0), ("ステーキ", 1.5), ("寿司", 1.5),
        ("割烹", 1.8), ("ラーメン", 1.5),
        ("精肉店", 2.0), ("鮮魚店", 2.0),
        ("カフェ", 1.0), ("パティスリー", 1.5), ("パン屋", 1.3),
    ],
}


def _is_excluded(text_lower: str) -> str | None:
    """除外判定"""
    for group in ("web_agency", "portal_media", "blog_personal"):
        count = sum(1 for kw in EXCLUDE_KEYWORDS[group] if re.search(kw, text_lower))
        if count >= 3:
            reasons = {
                "web_agency": "同業他社(Web制作会社)",
                "portal_media": "ポータル・メディア",
                "blog_personal": "個人ブログ",
            }
            return reasons[group]
    return None


def _score_category(text_lower: str, hint_category: str) -> tuple[str, float]:
    scores = {c: 0.0 for c in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for pattern, weight in keywords:
            if re.search(pattern, text_lower):
                scores[cat] += weight
    if hint_category in scores:
        scores[hint_category] += 1.0
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]
    if best_score < 0.8:
        return "none", 0.15
    confidence = min(best_score / 6.0, 1.0) * 0.5 + 0.35
    return best_cat, min(confidence, 1.0)


# ============================================================
# クエリ生成
# ============================================================

def generate_queries(
    category: str,
    prefectures: list[str] = None,
    subcategories: list[str] = None,
    max_queries: int = None,
) -> list[dict]:
    """カテゴリベースのクエリ生成（軸マトリクス）"""
    prefs = prefectures or PREFECTURES
    subs = subcategories or SUBCATEGORIES.get(category, [])
    scales = SCALE_KEYWORDS
    mods = TARGET_MODIFIERS.get(category, [""])

    queries = []
    for pref in prefs:
        for sub in subs:
            for scale in scales:
                for mod in mods:
                    parts = [pref, sub]
                    if scale:
                        parts.append(scale)
                    if mod:
                        parts.append(mod)
                    q = " ".join(parts)
                    queries.append({
                        "query": q,
                        "axis": {
                            "category": category,
                            "prefecture": pref,
                            "subcategory": sub,
                            "scale": scale or "none",
                        },
                    })
                    if max_queries and len(queries) >= max_queries:
                        return queries
    return queries


# ============================================================
# CollectedLead
# ============================================================

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
    # カテゴリ情報（category_collector 固有）
    category: str = ""
    confidence: float = 0.0
    subcategory: str = ""


# ============================================================
# DuckDuckGo 検索
# ============================================================

def _search_ddg_sync(query: str, max_results: int = 10) -> list[dict]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, region="jp-jp", max_results=max_results))
    except Exception as e:
        log.debug(f"DDG error [{query[:30]}]: {e}")
        return []


async def _search_ddg(query: str, max_results: int = 10) -> list[dict]:
    last_exc = None
    for attempt in range(3):
        try:
            return await asyncio.to_thread(_search_ddg_sync, query, max_results)
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt * 2
            await asyncio.sleep(wait)
    log.error(f"DDG全リトライ失敗: {last_exc}")
    return []


# ============================================================
# メイン収集関数
# ============================================================

async def collect(
    seen_emails: set[str],
    category: str = "B",
    prefectures: list[str] | None = None,
    subcategories: list[str] | None = None,
    max_queries: int = 100,
    max_urls: int = 300,
    on_progress=None,
) -> list[CollectedLead]:
    """全国カテゴリ収集（DuckDuckGo + ローカル分類 + サイト分析）"""
    log.info(f"カテゴリ[{category}]収集開始: max_queries={max_queries}, max_urls={max_urls}")

    queries = generate_queries(
        category, prefectures, subcategories, max_queries=max_queries
    )
    log.info(f"生成クエリ: {len(queries)}件")

    leads: list[CollectedLead] = []
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Step 1: DDGで検索 → URL収集
        collected_urls = []
        for i, q in enumerate(queries, 1):
            if on_progress and i % 10 == 0:
                on_progress(f"カテゴリ{category} 検索 ({i}/{len(queries)})")

            results = await _search_ddg(q["query"], max_results=10)
            for r in results:
                url = r.get("href", "")
                if not url or url in seen_urls:
                    continue
                # 除外ドメイン
                if any(d in url.lower() for d in EXCLUDED_DOMAINS):
                    continue
                # ドメイン重複排除
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.lower().lstrip("www.")
                    if domain.startswith("www."):
                        domain = domain[4:]
                    if domain in seen_domains:
                        continue
                    seen_domains.add(domain)
                except Exception:
                    continue
                seen_urls.add(url)
                collected_urls.append({"url": url, "axis": q["axis"]})

                if len(collected_urls) >= max_urls:
                    break
            if len(collected_urls) >= max_urls:
                break
            await asyncio.sleep(RATE_LIMIT_SEC)

        log.info(f"URL収集: {len(collected_urls)}件")

        # Step 2: 各URLをスクレイプ + 分類 + メール抽出
        sem = asyncio.Semaphore(10)
        completed = [0]
        total = len(collected_urls)

        async def process_url(item):
            async with sem:
                url = item["url"]
                axis = item["axis"]
                try:
                    r = await client.get(url, headers=random_ua(), timeout=12)
                    if r.status_code != 200:
                        return None
                    html = r.text
                except Exception:
                    return None

                # サイト分析
                analysis = analyze_html(html, url)
                text_lower = analysis.title.lower() + " " + (analysis.description or "").lower()

                # 除外判定
                exclusion = _is_excluded(text_lower)
                if exclusion:
                    return None

                # カテゴリ分類
                cat, confidence = _score_category(text_lower, axis.get("category", category))
                if cat == "none" or confidence < 0.3:
                    return None

                # メール抽出
                soup_text = BeautifulSoup(html, "html.parser").get_text(" ")
                emails = extract_emails(soup_text)
                email = next((e for e in emails if _same_domain(e, url)), None)

                if not email:
                    # 連絡先ページへ
                    for contact_url in find_contact_urls(html, url, max_urls=3):
                        try:
                            r2 = await client.get(contact_url, headers=random_ua(), timeout=10)
                            if r2.status_code != 200:
                                continue
                            t2 = BeautifulSoup(r2.text, "html.parser").get_text(" ")
                            emails2 = extract_emails(t2)
                            email = next((e for e in emails2 if _same_domain(e, url)), None)
                            if email:
                                break
                            if emails2 and not email:
                                email = emails2[0]
                        except Exception:
                            continue

                if not email or email.lower() in seen_emails:
                    return None
                seen_emails.add(email.lower())

                # 業種ラベル
                industry = axis.get("subcategory", "")

                lead = CollectedLead(
                    email=email,
                    company=analysis.title[:60] if analysis.title else "",
                    industry=industry,
                    location=axis.get("prefecture", ""),
                    website=url,
                    platform=analysis.cms_type or "",
                    ec_status=analysis.ec_platform or ("自社ECあり" if analysis.is_ec_site else ""),
                    source="category",
                    category=cat,
                    confidence=confidence,
                    subcategory=industry,
                )
                return lead

        async def _worker(item):
            result = await process_url(item)
            completed[0] += 1
            if on_progress and completed[0] % 20 == 0:
                on_progress(f"カテゴリ{category} 分析 ({completed[0]}/{total})")
            return result

        tasks = [_worker(item) for item in collected_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, CollectedLead):
                leads.append(r)

    log.info(f"カテゴリ[{category}] 結果: {len(leads)}件")
    return leads
