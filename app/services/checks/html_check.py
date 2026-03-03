import re
from datetime import datetime
import httpx
from bs4 import BeautifulSoup


async def check_html(url: str, client: httpx.AsyncClient) -> dict:
    """HTMLを解析してコピーライト年・モバイル対応・Flash・CMS・デザイン・EC・SEO項目を検出する"""
    result = {
        "copyright_year": None,
        "has_viewport": None,
        "has_flash": None,
        "cms_type": None,
        "cms_version": None,
        # Phase 1 追加: デザイン系
        "has_og_image": None,
        "has_favicon": None,
        "has_table_layout": None,
        "missing_alt_count": None,
        # Phase 1 追加: EC系
        "is_ec_site": None,
        "ec_platform": None,
        "has_site_search": None,
        "has_product_schema": None,
        # Phase 1 追加: SEO系
        "has_structured_data": None,
        "has_breadcrumb": None,
    }

    try:
        resp = await client.get(url, follow_redirects=True, timeout=10)
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # コピーライト年の検出
        result["copyright_year"] = _extract_copyright_year(html)

        # viewportメタタグ（モバイル対応）
        viewport = soup.find("meta", attrs={"name": re.compile(r"viewport", re.I)})
        result["has_viewport"] = viewport is not None

        # Flash使用検出
        has_flash = bool(
            soup.find("object") or
            soup.find("embed") or
            re.search(r'\.swf', html, re.I)
        )
        result["has_flash"] = has_flash

        # CMS種別の検出
        cms_type, cms_version = _detect_cms(html, soup, resp.headers)
        result["cms_type"] = cms_type
        result["cms_version"] = cms_version

        # --- Phase 1 追加チェック ---

        # デザイン系
        result["has_og_image"] = _check_og_image(soup)
        result["has_favicon"] = _check_favicon(soup)
        result["has_table_layout"] = _check_table_layout(soup)
        result["missing_alt_count"] = _count_missing_alt(soup)

        # EC系
        ec_info = _detect_ec(html, soup)
        result["is_ec_site"] = ec_info["is_ec_site"]
        result["ec_platform"] = ec_info["ec_platform"]
        result["has_site_search"] = _check_site_search(soup)
        result["has_product_schema"] = _check_product_schema(html)

        # SEO系
        result["has_structured_data"] = _check_structured_data(html, soup)
        result["has_breadcrumb"] = _check_breadcrumb(html, soup)

    except Exception:
        pass

    return result


def _extract_copyright_year(html: str) -> int | None:
    current_year = datetime.now().year
    # コピーライト表記から年を抽出
    patterns = [
        r'[Cc]opyright\s*[©&copy;]*\s*(\d{4})',
        r'©\s*(\d{4})',
        r'&copy;\s*(\d{4})',
        r'コピーライト\s*(\d{4})',
    ]
    years = []
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for m in matches:
            year = int(m)
            if 1990 <= year <= current_year:
                years.append(year)

    if years:
        return max(years)  # 最新のコピーライト年を返す
    return None


def _detect_cms(html: str, soup: BeautifulSoup, headers) -> tuple[str | None, str | None]:
    # WordPress
    if re.search(r'/wp-content/|/wp-includes/', html):
        version = None
        # 方法1: <meta name="generator"> タグ
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator:
            content = generator.get("content", "")
            wp_ver = re.search(r'WordPress\s*([\d.]+)', content, re.I)
            if wp_ver:
                version = wp_ver.group(1)
        # 方法2: wp-includes/js/ や wp-includes/css/ 内の ?ver= パラメータ
        if not version:
            ver_matches = re.findall(
                r'wp-(?:includes|content)[^"\']*\?ver=([\d.]+)', html
            )
            if ver_matches:
                # 最も多く出現するバージョンを採用
                from collections import Counter
                counter = Counter(ver_matches)
                version = counter.most_common(1)[0][0]
        # 方法3: wp-emoji-release.min.js?ver= パターン
        if not version:
            emoji_ver = re.search(r'wp-emoji-release\.min\.js\?ver=([\d.]+)', html)
            if emoji_ver:
                version = emoji_ver.group(1)
        return "WordPress", version

    # Wix
    if "wix.com" in html or "_wix" in html:
        return "Wix", None

    # Jimdo
    if "jimdo.com" in html or "jimdofree.com" in html:
        return "Jimdo", None

    # STUDIO
    if "studio.design" in html or "studio.site" in html:
        return "STUDIO", None

    # Shopify
    if "myshopify.com" in html or "shopify" in html.lower():
        return "Shopify", None

    # X-Powered-By ヘッダー
    powered_by = headers.get("x-powered-by", "")
    if powered_by:
        return powered_by, None

    return None, None


# --- Phase 1: デザイン系チェック ---

def _check_og_image(soup: BeautifulSoup) -> bool:
    """OGP画像(og:image)の有無を確認"""
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content", "").strip():
        return True
    return False


def _check_favicon(soup: BeautifulSoup) -> bool:
    """ファビコンの設定有無を確認"""
    for rel in ["icon", "shortcut icon", "apple-touch-icon"]:
        if soup.find("link", attrs={"rel": re.compile(rel, re.I)}):
            return True
    return False


def _check_table_layout(soup: BeautifulSoup) -> bool:
    """テーブルレイアウト(入れ子table)を検出"""
    for table in soup.find_all("table"):
        if table.find("table"):
            return True
    return False


def _count_missing_alt(soup: BeautifulSoup) -> int:
    """alt属性が欠落しているimg要素の数"""
    count = 0
    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt is None or alt.strip() == "":
            count += 1
    return count


# --- Phase 1: EC系チェック ---

def _detect_ec(html: str, soup: BeautifulSoup) -> dict:
    """ECサイトかどうか・ECプラットフォームを検出"""
    result = {"is_ec_site": False, "ec_platform": None}

    # ECプラットフォーム検出
    platforms = [
        ("BASE", [r"thebase\.in", r"base\.shop"]),
        ("STORES", [r"stores\.jp"]),
        ("Shopify", [r"myshopify\.com", r"cdn\.shopify"]),
        ("カラーミーショップ", [r"shop-pro\.jp"]),
        ("MakeShop", [r"makeshop\.jp"]),
        ("EC-CUBE", [r"ec-cube", r"/shopping/cart"]),
        ("楽天", [r"rakuten\.co\.jp/gold/", r"item\.rakuten\.co\.jp"]),
    ]
    for name, patterns in platforms:
        for p in patterns:
            if re.search(p, html, re.I):
                result["is_ec_site"] = True
                result["ec_platform"] = name
                return result

    # カート・商品ページの一般的な手がかり
    ec_signals = [
        r"cart|カート|買い物かご",
        r"add.to.cart|カートに入れる|購入する",
        r"checkout|お支払い|注文確認",
        r"商品一覧|商品詳細|price|価格",
    ]
    signal_count = sum(1 for p in ec_signals if re.search(p, html, re.I))
    if signal_count >= 2:
        result["is_ec_site"] = True

    return result


def _check_site_search(soup: BeautifulSoup) -> bool:
    """サイト内検索フォームの有無"""
    for inp in soup.find_all("input"):
        input_type = (inp.get("type") or "").lower()
        input_name = (inp.get("name") or "").lower()
        if input_type == "search":
            return True
        if any(kw in input_name for kw in ["search", "query", "keyword", "q"]):
            return True
    return False


def _check_product_schema(html: str) -> bool:
    """schema.org/Product 構造化データの有無"""
    return bool(re.search(r'schema\.org[/"].*?Product|"@type"\s*:\s*"Product"', html, re.I))


# --- Phase 1: SEO系チェック ---

def _check_structured_data(html: str, soup: BeautifulSoup) -> bool:
    """構造化データ(JSON-LD/microdata)の有無"""
    if soup.find("script", attrs={"type": "application/ld+json"}):
        return True
    if re.search(r'itemscope|itemtype="http://schema\.org', html, re.I):
        return True
    return False


def _check_breadcrumb(html: str, soup: BeautifulSoup) -> bool:
    """パンくずリストの有無"""
    if soup.find(attrs={"class": re.compile(r"breadcrumb", re.I)}):
        return True
    if soup.find(attrs={"id": re.compile(r"breadcrumb", re.I)}):
        return True
    if re.search(r'BreadcrumbList', html):
        return True
    return False
