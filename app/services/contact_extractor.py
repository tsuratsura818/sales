import re
import httpx
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# 問い合わせページを示すキーワード
CONTACT_KEYWORDS = [
    "contact", "inquiry", "inquire", "問い合わせ", "お問い合わせ",
    "contact-us", "contactus", "toiawase",
]


async def extract_contact(url: str, client: httpx.AsyncClient) -> dict:
    """サイトからメールアドレスと問い合わせページURLを抽出する"""
    result = {"contact_email": None, "contact_page_url": None}

    try:
        resp = await client.get(url, follow_redirects=True, timeout=10)
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # 1. mailto: リンクからメールアドレスを抽出
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                email = href[7:].split("?")[0].strip()
                if EMAIL_PATTERN.match(email):
                    result["contact_email"] = email
                    break

        # 2. テキスト内のメールアドレスを正規表現で抽出（fallback）
        if not result["contact_email"]:
            emails = EMAIL_PATTERN.findall(html)
            # 画像ファイル等を除外
            valid_emails = [e for e in emails if not any(ext in e for ext in [".png", ".jpg", ".gif", ".svg"])]
            # info@ / contact@ / sales@ を優先
            priority = [e for e in valid_emails if e.split("@")[0] in ("info", "contact", "sales", "mail", "support")]
            if priority:
                result["contact_email"] = priority[0]
            elif valid_emails:
                result["contact_email"] = valid_emails[0]

        # 3. 問い合わせページURLを検出
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if any(kw in href or kw in text for kw in CONTACT_KEYWORDS):
                full_url = urljoin(base_url, a["href"])
                result["contact_page_url"] = full_url
                break

    except Exception:
        pass

    return result
