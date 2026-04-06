"""情報抽出モジュール（eigyoから移植）"""
import re
from .config import TARGET_AREAS, EXCLUDE_NAMES

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
EXCLUDE_EMAIL_DOMAINS = {"example.com", "test.com", "sentry.io", "wixpress.com", "shopify.com"}


def extract_emails(text: str) -> list[str]:
    """テキストからメールアドレスを抽出（除外フィルタ付き）"""
    matches = EMAIL_RE.findall(text)
    result = []
    for e in matches:
        e_lower = e.lower()
        domain = e_lower.split("@")[1]
        if domain in EXCLUDE_EMAIL_DOMAINS:
            continue
        if e_lower.startswith(("noreply", "no-reply", "test@", "example@", "abuse@", "postmaster@")):
            continue
        if e_lower.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            continue
        if "rakuten" in domain or "yahoo.co.jp" == domain or "amazon" in domain:
            continue
        result.append(e)
    return list(dict.fromkeys(result))


def extract_company(text: str) -> str:
    """特商法ページから販売業者名を抽出"""
    patterns = [
        r"(?:販売業者|事業者の名称|事業者名|会社名|運営会社|法人名)[：:\s]*([^\n\r]{2,60})",
        r"(?:ショップ名|店舗名|屋号)[：:\s]*([^\n\r]{2,60})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s*(所在地|住所|代表|電話|メール|運営).*$", "", name)
            if len(name) > 1:
                return name
    return ""


def extract_address(text: str) -> str:
    """住所を抽出"""
    patterns = [
        r"(?:所在地|事業者の所在地|事業者の住所|住所)[：:\s]*(〒?\d{3}-?\d{4}[^\n\r]{5,80})",
        r"(?:所在地|事業者の住所|住所)[：:\s]*([^\n\r]{5,80})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            addr = m.group(1).strip()
            addr = re.sub(r"\s*(電話|TEL|Tel|代表|メール|FAX).*$", "", addr)
            return addr
    return ""


def is_kansai(text: str) -> bool:
    """関西エリアに該当するか"""
    return any(area in text for area in TARGET_AREAS)


def is_excluded(company: str) -> bool:
    """大手企業除外チェック"""
    return any(exc in company for exc in EXCLUDE_NAMES)


def detect_ec_platform(html: str) -> str:
    """HTMLからECプラットフォームを検出"""
    html_lower = html.lower()
    if "cdn.shopify.com" in html_lower or "myshopify.com" in html_lower:
        return "Shopify構築済み"
    if "base.shop" in html_lower or "thebase.in" in html_lower:
        return "BASE利用中"
    if "stores.jp" in html_lower:
        return "STORES利用中"
    if "shop-pro.jp" in html_lower:
        return "カラーミー利用中"
    if "makeshop" in html_lower:
        return "MakeShop利用中"
    if "futureshop" in html_lower:
        return "FutureShop利用中"
    # カート判定は複合条件で偽陽性を抑制（カートボタン+商品ページの両方が存在）
    has_cart = "cart" in html_lower or "カートに入れる" in html_lower or "add to cart" in html_lower
    has_product = "商品" in html_lower or "product" in html_lower or "price" in html_lower
    if has_cart and has_product:
        return "自社ECあり"
    return ""
