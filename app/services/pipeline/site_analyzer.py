"""
site_analyzer.py — 企業サイトの個別分析（ローカル・AI不使用）

salesプロジェクトの analyzer.py / claude_service.py の設計思想を踏襲し、
各企業サイトをスクレイプして具体的な課題を抽出、個別提案文を生成。
"""
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup


# ============================================================
# サイト分析結果
# ============================================================

@dataclass
class SiteAnalysis:
    url: str = ""
    title: str = ""
    description: str = ""
    # 技術・CMS
    cms_type: str = ""         # WordPress / Shopify / BASE / STORES / Wix / Squarespace / None
    is_https: bool = False
    has_viewport: bool = False       # モバイル対応
    has_og_image: bool = False       # SNS対応
    has_favicon: bool = False
    copyright_year: int | None = None
    # EC判定
    is_ec_site: bool = False
    ec_platform: str = ""
    has_cart: bool = False
    # 問い合わせ・フォーム
    has_contact_form: bool = False
    has_contact_link: bool = False
    # コンテンツ
    has_news: bool = False           # お知らせ欄
    last_news_year: int | None = None
    news_freshness: str = ""          # fresh / stale / unknown
    # SNSリンク
    has_sns: bool = False
    sns_platforms: list[str] = field(default_factory=list)
    # メール
    email: str = ""
    # 抽出した事業特徴
    notable_keywords: list[str] = field(default_factory=list)
    # 検出された課題
    issues: list[dict] = field(default_factory=list)
    # 分析エラー
    error: str = ""


# ============================================================
# CMS判定
# ============================================================

def detect_cms(html: str) -> tuple[str, str, bool]:
    """(cms_type, ec_platform, is_ec_site)"""
    h = html.lower()

    if "cdn.shopify.com" in h or "myshopify.com" in h:
        return "Shopify", "Shopify", True
    if "wp-content" in h or "wp-includes" in h or "wordpress" in h:
        # WordPress + WooCommerce で EC
        if "woocommerce" in h:
            return "WordPress", "WooCommerce", True
        return "WordPress", "", False
    if "base.shop" in h or "thebase.in" in h:
        return "BASE", "BASE", True
    if "stores.jp" in h:
        return "STORES", "STORES", True
    if "shop-pro.jp" in h or "color-me" in h:
        return "カラーミー", "カラーミー", True
    if "squarespace" in h:
        return "Squarespace", "", False
    if "wixstatic.com" in h or 'content="wix.com"' in h:
        return "Wix", "", False
    if "makeshop" in h:
        return "MakeShop", "MakeShop", True
    if "jimdo" in h:
        return "Jimdo", "", False

    # カート判定
    has_cart = any(k in h for k in ["カートに入れる", "add to cart", "shopping cart", "カートへ"])
    if has_cart:
        return "自社EC(不明)", "自社EC", True

    return "不明", "", False


# ============================================================
# ページ解析
# ============================================================

def analyze_html(html: str, url: str) -> SiteAnalysis:
    result = SiteAnalysis(url=url)
    soup = BeautifulSoup(html, "html.parser")

    # タイトル・description
    if soup.title and soup.title.string:
        result.title = soup.title.string.strip()[:100]
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        result.description = meta_desc["content"].strip()[:200]

    # HTTPS
    result.is_https = url.startswith("https://")

    # モバイル対応
    viewport = soup.find("meta", attrs={"name": "viewport"})
    result.has_viewport = bool(viewport and viewport.get("content"))

    # OGイメージ
    og_img = soup.find("meta", attrs={"property": "og:image"})
    result.has_og_image = bool(og_img and og_img.get("content"))

    # Favicon
    favicon = soup.find("link", rel=lambda r: r and ("icon" in r.lower()))
    result.has_favicon = bool(favicon and favicon.get("href"))

    # CMS判定
    cms, ec_platform, is_ec = detect_cms(html)
    result.cms_type = cms
    result.ec_platform = ec_platform
    result.is_ec_site = is_ec
    result.has_cart = "カート" in html or "cart" in html.lower()

    # Copyright年
    body_text = soup.get_text(" ", strip=True)[:8000]
    copyright_match = re.search(r"(?:©|Copyright|copyright|\(c\))\s*(?:\d{4}\s*[-–—]\s*)?(\d{4})", body_text)
    if copyright_match:
        year = int(copyright_match.group(1))
        current = datetime.now().year
        if 2000 <= year <= current + 1:
            result.copyright_year = year

    # お知らせ・ブログ更新日（最新年を探す）
    date_years = re.findall(r"20(1[5-9]|2[0-6])[\.\-/年]", body_text)
    if date_years:
        max_yr = max(int("20" + y) for y in date_years)
        result.has_news = True
        result.last_news_year = max_yr
        current = datetime.now().year
        if max_yr >= current - 1:
            result.news_freshness = "fresh"
        elif max_yr >= current - 2:
            result.news_freshness = "stale"
        else:
            result.news_freshness = "unknown"

    # 問い合わせ
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        text = (a.get_text() or "").lower()
        if "contact" in href or "お問い合わせ" in text or "問合" in text:
            result.has_contact_link = True
            break

    # フォーム
    forms = soup.find_all("form")
    for form in forms:
        inputs = form.find_all(["input", "textarea"])
        if len(inputs) >= 3:
            action = (form.get("action") or "").lower()
            if "contact" in action or "form" in action or "inquiry" in action or not action:
                result.has_contact_form = True
                break

    # SNS
    sns_map = {
        "instagram.com": "Instagram",
        "facebook.com": "Facebook",
        "twitter.com": "X",
        "x.com": "X",
        "youtube.com": "YouTube",
        "tiktok.com": "TikTok",
        "line.me": "LINE",
    }
    found_sns = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        for domain, name in sns_map.items():
            if domain in href:
                found_sns.add(name)
                break
    result.sns_platforms = sorted(found_sns)
    result.has_sns = len(found_sns) > 0

    return result


# ============================================================
# 課題検出
# ============================================================

def detect_issues(a: SiteAnalysis, category: str) -> list[dict]:
    """検出された課題を（severity, key, text）のリストで返す"""
    issues = []
    current_year = datetime.now().year

    # 共通課題
    if not a.is_https:
        issues.append({"severity": "high", "key": "https", "text": "サイトがHTTPS化されておらず、Google検索順位とユーザー信頼性に影響している"})
    if not a.has_viewport:
        issues.append({"severity": "high", "key": "mobile", "text": "スマートフォン対応（viewport設定）がされておらず、モバイルユーザーの離脱率が高い可能性"})
    if not a.has_og_image:
        issues.append({"severity": "low", "key": "og_image", "text": "SNSシェア時のサムネイル画像（OGP）が設定されておらず、SNS経由の集客機会を逃している"})
    if not a.has_favicon:
        issues.append({"severity": "low", "key": "favicon", "text": "ファビコンが未設定で、ブラウザタブでの視認性・ブランド認知が弱い"})
    if a.copyright_year and a.copyright_year < current_year - 1:
        issues.append({"severity": "mid", "key": "copyright", "text": f"Copyright表記が {a.copyright_year} 年のまま更新されておらず、サイトの鮮度が古く見える"})
    if a.last_news_year and a.last_news_year < current_year - 1:
        issues.append({"severity": "mid", "key": "news_stale", "text": f"お知らせ欄の最終更新が {a.last_news_year} 年で、SEO流入・信頼性に影響している可能性"})
    if not a.has_contact_form and not a.has_contact_link:
        issues.append({"severity": "high", "key": "no_contact", "text": "問い合わせフォーム・連絡先導線が弱く、見込み顧客の取りこぼしが発生している可能性"})
    if not a.has_sns:
        issues.append({"severity": "low", "key": "no_sns", "text": "SNS連携リンクがサイトに設置されておらず、ブランド発信力が弱い"})

    # カテゴリ別の課題
    if category == "A":  # D2C EC
        if not a.is_ec_site:
            issues.append({"severity": "high", "key": "no_ec", "text": "自社ECサイトが無く、販路がモール・実店舗に限定されている"})
        elif a.ec_platform in ("BASE", "STORES", "カラーミー", "MakeShop"):
            issues.append({"severity": "mid", "key": "ec_upgrade", "text": f"{a.ec_platform}でのEC運用だが、Shopifyに移行することでブランド表現・機能拡張の幅が大きく広がる"})
        if a.cms_type == "WordPress" and a.ec_platform == "WooCommerce":
            issues.append({"severity": "mid", "key": "woo_to_shopify", "text": "WooCommerceは拡張の自由度が高い反面、運用・セキュリティ負荷が重いため、Shopifyへの乗り換えで保守を削減可能"})

    elif category == "B":  # WordPress コーポレート
        if a.cms_type not in ("WordPress",):
            issues.append({"severity": "mid", "key": "cms_consider", "text": f"現行CMSは「{a.cms_type}」。WordPressなら自社で記事追加・採用ページの更新が容易で、運用コストが下がる"})

    elif category == "C":  # LP
        # ランディングページ系の課題
        if a.has_contact_form and not a.has_contact_link:
            pass
        issues.append({"severity": "mid", "key": "lp_opportunity", "text": "サービス訴求に特化したLP（ランディングページ）があれば、広告運用・CVR改善に大きく寄与する"})

    elif category == "D":  # 飲食EC
        if not a.is_ec_site:
            issues.append({"severity": "high", "key": "no_ec_d", "text": "通販・お取り寄せ機能が無く、来店以外の売上機会を逃している"})
        if not a.has_sns:
            issues.append({"severity": "mid", "key": "no_sns_d", "text": "InstagramなどのSNS連携が弱く、SNS世代の集客・来店促進機会を逃している"})

    # 重要度の高いものを優先
    severity_order = {"high": 0, "mid": 1, "low": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))
    return issues


# ============================================================
# 提案文生成（ローカル・ルールベース）
# ============================================================

CATEGORY_TITLES = {
    "A": "Shopifyを活用した自社EC構築",
    "B": "WordPressでのコーポレートサイトリニューアル",
    "C": "サービス訴求LP制作",
    "D": "通販・お取り寄せEC構築",
}

CATEGORY_HEADLINES = {
    "A": "{company}様のブランド世界観を活かすShopify ECのご相談",
    "B": "{company}様のコーポレートサイト改善のご相談",
    "C": "{company}様のサービス訴求LP制作のご相談",
    "D": "{company}様の通販EC構築のご相談",
}

CATEGORY_OPENING = {
    "A": "{company}様のブランドストーリー・{industry}としての魅力を自社EC上で最大限に表現するためのご提案をお送りいたします。",
    "B": "{company}様の{industry}としての信頼性・実績を最大限に伝えるサイト改修のご提案をお送りいたします。",
    "C": "{company}様の{industry}サービスの魅力を最大限に訴求するLP制作のご提案をお送りいたします。",
    "D": "{company}様の{industry}の味・品質を全国のお客様にお届けする通販EC構築のご提案をお送りいたします。",
}

PRICE_BY_CAT = {
    "A": "初期 50〜100万円 + 月額保守 1.5万円〜",
    "B": "初期 30〜60万円 + 月額保守 1万円〜",
    "C": "初期 15〜30万円",
    "D": "初期 50万円〜 + 月額保守 4千円〜",
}


def build_personalized_proposal(
    company: str,
    industry: str,
    category: str,
    prefecture: str,
    analysis: SiteAnalysis,
) -> dict:
    """個別分析結果に基づくパーソナライズ提案文"""
    company = company or "貴社"
    industry = industry or "事業者"

    headline = CATEGORY_HEADLINES.get(category, CATEGORY_HEADLINES["B"]).format(
        company=company, industry=industry
    )
    opening = CATEGORY_OPENING.get(category, CATEGORY_OPENING["B"]).format(
        company=company, industry=industry
    )

    # サイト検出の言及（最初に個別性を出す）
    site_observations = []
    if analysis.title:
        site_observations.append(f"「{analysis.title[:40]}」")
    if analysis.cms_type and analysis.cms_type != "不明":
        site_observations.append(f"{analysis.cms_type}で構築")
    if analysis.ec_platform:
        site_observations.append(f"{analysis.ec_platform}ご利用中")
    if analysis.has_sns and analysis.sns_platforms:
        site_observations.append(f"{'・'.join(analysis.sns_platforms[:3])}運用中")

    observation_text = ""
    if site_observations:
        observation_text = f"貴社サイト（{', '.join(site_observations)}）を拝見し、"

    # 検出課題（上位3〜4件）
    top_issues = analysis.issues[:4]
    issues_block = ""
    if top_issues:
        lines = [f"・{it['text']}" for it in top_issues]
        issues_block = "【サイト拝見時に気になった点】\n" + "\n".join(lines)

    # 具体提案（カテゴリ×検出課題）
    proposal_lines = []
    if category == "A":
        proposal_lines.append(f"{CATEGORY_TITLES['A']}により、ブランド世界観の統一・顧客データ蓄積・LTV向上を実現します。")
        if any(i["key"] == "ec_upgrade" for i in top_issues):
            proposal_lines.append(f"現在の{analysis.ec_platform}から段階的にShopifyへ移行するプランもご提案可能です。")
    elif category == "B":
        proposal_lines.append(f"{CATEGORY_TITLES['B']}により、検索流入・問い合わせ導線・ブランドイメージを強化します。")
        if any(i["key"] == "mobile" for i in top_issues):
            proposal_lines.append("特にスマートフォン対応を最優先で改善します。")
    elif category == "C":
        proposal_lines.append(f"{CATEGORY_TITLES['C']}により、広告運用の効率化・獲得単価の圧縮を実現します。")
        proposal_lines.append("ファーストビュー・CTA設計・A/Bテストで継続的にCVRを改善します。")
    elif category == "D":
        proposal_lines.append(f"{CATEGORY_TITLES['D']}により、お取り寄せ・ギフト需要・来店以外の新たな売上軸を構築します。")

    proposal_text = "【ご提案】\n" + "\n".join(f"・{p}" for p in proposal_lines)

    # 構成
    body = f"""{company} ご担当者様

はじめてご連絡させていただきます。
大阪のWeb制作会社TSURATSURAの西川と申します。

{observation_text}{opening}

{issues_block}

{proposal_text}

【想定プラン】
{PRICE_BY_CAT.get(category, '')}

【納期】
約6〜10週間

ご興味ございましたら、オンラインでの30分無料相談にて、{company}様に合わせた具体的なご提案をさせていただきます。

お忙しいところ恐れ入りますが、ご検討のほどよろしくお願いいたします。

──────────────
TSURATSURA 西川
{prefecture or '全国'}対応
──────────────"""

    return {
        "subject": headline,
        "body": body.strip(),
    }


# ============================================================
# メール抽出（既存ロジックから移植）
# ============================================================

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EXCLUDE_EMAIL_DOMAINS = {
    "example.com", "example.co.jp", "test.com", "sentry.io",
    "wixpress.com", "shopify.com", "sendgrid.net",
    "googleapis.com", "google.com", "w3.org", "schema.org",
}
EXCLUDE_EMAIL_LOCAL_PREFIXES = (
    "noreply", "no-reply", "donotreply", "postmaster", "abuse",
    "test@", "example@", "sample@",
)


def extract_emails(text: str) -> list[str]:
    matches = EMAIL_RE.findall(text)
    result = []
    for e in matches:
        e_lower = e.lower()
        if "@" not in e_lower:
            continue
        domain = e_lower.split("@")[1]
        if domain in EXCLUDE_EMAIL_DOMAINS:
            continue
        if e_lower.startswith(EXCLUDE_EMAIL_LOCAL_PREFIXES):
            continue
        if e_lower.endswith((".png", ".jpg", ".gif", ".svg", ".webp", ".jpeg")):
            continue
        if len(domain) > 50 or "." not in domain:
            continue
        result.append(e)
    return list(dict.fromkeys(result))


def _same_domain(email: str, site_url: str) -> bool:
    try:
        ed = email.split("@")[1].lower()
        sd = urlparse(site_url).netloc.lower()
        if sd.startswith("www."):
            sd = sd[4:]
        return ed.split(".")[-2:] == sd.split(".")[-2:]
    except Exception:
        return False


CONTACT_KEYWORDS = [
    "特定商取引", "tokushoho",
    "お問い合わせ", "お問合わせ", "お問合せ", "contact",
    "会社概要", "会社情報", "company", "about",
]


def find_contact_urls(html: str, base_url: str, max_urls: int = 3) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").lower()
        combined = (text + " " + href).lower()
        for kw in CONTACT_KEYWORDS:
            if kw.lower() in combined:
                try:
                    full = urljoin(base_url, href)
                except Exception:
                    continue
                if full not in seen and full.startswith("http"):
                    seen.add(full)
                    urls.append(full)
                    if len(urls) >= max_urls:
                        return urls
                break
    return urls


async def analyze_and_extract_email(
    url: str, client: httpx.AsyncClient, user_agent: str,
) -> tuple[SiteAnalysis, str | None]:
    """トップページ分析 + メール抽出（連絡先ページも辿る）"""
    headers = {"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.8"}
    analysis = SiteAnalysis(url=url)

    try:
        r = await client.get(url, headers=headers, timeout=12, follow_redirects=True)
        if r.status_code != 200:
            analysis.error = f"HTTP {r.status_code}"
            return analysis, None
        html = r.text
    except Exception as e:
        analysis.error = type(e).__name__
        return analysis, None

    analysis = analyze_html(html, url)

    # メール抽出
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    emails = extract_emails(text)
    email = None
    for e in emails:
        if _same_domain(e, url):
            email = e
            break

    # 連絡先ページを辿る
    if not email:
        for contact_url in find_contact_urls(html, url, max_urls=3):
            try:
                r2 = await client.get(contact_url, headers=headers, timeout=10, follow_redirects=True)
                if r2.status_code != 200:
                    continue
                text2 = BeautifulSoup(r2.text, "html.parser").get_text(" ")
                emails2 = extract_emails(text2)
                for e in emails2:
                    if _same_domain(e, url):
                        email = e
                        break
                if email:
                    break
                if emails2 and not emails:
                    emails = emails2
            except Exception:
                continue
        if not email and emails:
            email = emails[0]

    analysis.email = email or ""
    return analysis, email
